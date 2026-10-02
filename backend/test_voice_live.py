"""
Manual live check of the voice providers and the /api/voice endpoint.

Calls the real Volcengine speech services (and, for ``e2e``, the configured
LLM). Needs VOLC_VOICE_API_KEY etc. in .env. Run it explicitly; it is never
part of the deterministic suite. Uses only synthetic sentences.

    uv run python test_voice_live.py loopback
        TTS synthesises a few sentences; that audio is fed to the ASR provider
        in real-time 20 ms frames. Prints transcripts, partial counts, time to
        first TTS audio and time from end of speech to the ASR final.

    uv run python test_voice_live.py e2e [--url ws://localhost:8000/api/voice] [--calls 2]
        One call through a running backend (uvicorn main:app): TTS-synthesised
        speech is streamed as the uplink (8-byte header framing); the script
        answers follow-ups by voice, says 对的 to the read-back and reports the
        timings. Start a fresh server first; with --calls 2 the first call is
        the cold one (first after process start) and the second is warm.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

from voice.protocol import UPLINK_FRAME_SAMPLES, pack_uplink_audio, unpack_downlink_audio  # noqa: E402
from voice.providers import create_asr_provider, create_tts_provider, resolve_speech_settings  # noqa: E402

FRAME_BYTES = UPLINK_FRAME_SAMPLES * 2  # 20 ms of 16 kHz PCM16
SENTENCES = ["我头疼三天了，比较严重。", "还有点恶心，晚上睡不好。", "没有发烧。"]


def _providers(tts_rate: int = 16_000):
    asr = create_asr_provider(resolve_speech_settings(purpose="asr"))
    tts_settings = dataclasses.replace(resolve_speech_settings(purpose="tts"), sample_rate=tts_rate)
    return asr, create_tts_provider(tts_settings)


async def synthesize(tts, text: str) -> tuple[bytes, float]:
    start = time.perf_counter()
    first = None
    chunks = []
    async for chunk in tts.synthesize(text):
        if first is None:
            first = time.perf_counter() - start
        chunks.append(chunk)
    return b"".join(chunks), (first or 0.0)


async def loopback() -> None:
    asr, tts = _providers()
    print(f"ASR endpoint mode={asr.mode} capabilities={asr.capabilities}")
    print(f"TTS voice={tts.settings.voice} resource={tts.settings.resource_id}")
    for text in SENTENCES:
        pcm, first_audio = await synthesize(tts, text)
        stream = await asr.open_stream(sample_rate=16_000)
        partials, finals, events_at = 0, [], {}
        speech_end = None

        async def pump():
            nonlocal partials
            async for event in stream.events():
                if event.kind == "partial":
                    partials += 1
                elif event.kind == "final":
                    finals.append(event.text)
                    events_at.setdefault("final", time.perf_counter())
                elif event.kind == "silence":
                    events_at.setdefault("silence", time.perf_counter())

        reader = asyncio.create_task(pump())
        start = time.perf_counter()
        padded = pcm + b"\x00\x00" * 16_000 * 2  # 2 s of trailing silence (open mic)
        for offset in range(0, len(padded), FRAME_BYTES):
            await stream.send_audio(padded[offset:offset + FRAME_BYTES])
            if offset + FRAME_BYTES >= len(pcm) and speech_end is None:
                speech_end = time.perf_counter()
            target = start + (offset + FRAME_BYTES) / 2 / 16_000
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
            if "final" in events_at:
                break
            if not asr.capabilities.partials and "silence" in events_at:
                break  # no-partials mode: the energy endpointer said "done" → flush
        flushed = None
        if not finals:
            before = time.perf_counter()
            flushed = await stream.flush()
            events_at.setdefault("final", time.perf_counter())
            if flushed:
                finals.append(flushed.text)
            print(f"  (final came from flush, {int((time.perf_counter() - before) * 1000)} ms)")
        await stream.close()
        reader.cancel()
        final_ms = int((events_at["final"] - speech_end) * 1000) if speech_end and "final" in events_at else None
        print(
            f"said={text!r} heard={''.join(finals)!r} partials={partials} "
            f"tts_first_audio_ms={int(first_audio * 1000)} audio_ms={len(pcm) // 32} "
            f"speech_end_to_final_ms={final_ms}"
        )
    await tts.aclose()


async def one_call(url: str, tts) -> dict:
    """One full call; returns the timings (seconds) the report needs."""
    import websockets

    frames: list[tuple[float, dict]] = []
    sentence_first_audio: dict[int, float] = {}
    t0 = time.perf_counter()

    def now() -> float:
        return time.perf_counter() - t0

    ws = await websockets.connect(url, additional_headers={"Origin": "http://localhost:5173"}, max_size=None)

    async def receiver():
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    _, sentence_id, _, _ = unpack_downlink_audio(message)
                    sentence_first_audio.setdefault(sentence_id, now())
                else:
                    frames.append((now(), json.loads(message)))
        except websockets.ConnectionClosed:
            pass
        frames.append((now(), {"type": "_closed", "code": ws.close_code}))

    def seen(kind, pred=lambda f: True, after=0.0):
        return [(t, f) for t, f in frames if t >= after and f.get("type") == kind and pred(f)]

    async def wait(kind, pred=lambda f: True, after=0.0, timeout=120.0):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            hits = seen(kind, pred, after)
            if hits:
                return hits[0]
            await asyncio.sleep(0.02)
        raise TimeoutError(f"no {kind} within {timeout}s")

    async def spoken_at(text: str, after: float) -> float | None:
        """When the first audio of the (non-cue) sentence starting ``text`` arrived."""
        _, sentence = await wait("tts.sentence", lambda f: not f.get("cue") and text.startswith(f["text"][:6]), after)
        await wait("state", lambda f: f["value"] == "listening", after)
        return sentence_first_audio.get(sentence["sentence_id"])

    seq = 0
    sample_offset = 0

    async def send_pcm(pcm: bytes) -> None:
        nonlocal seq, sample_offset
        start = time.perf_counter()
        for offset in range(0, len(pcm), FRAME_BYTES):
            chunk = pcm[offset:offset + FRAME_BYTES].ljust(FRAME_BYTES, b"\x00")
            await ws.send(pack_uplink_audio(seq, sample_offset, chunk))
            seq += 1
            sample_offset += len(chunk) // 2
            target = start + (offset + FRAME_BYTES) / 2 / 16_000
            await asyncio.sleep(max(0.0, target - time.perf_counter()))

    async def say(text: str) -> float:
        """Speak ``text`` then keep the mic open (silence) until the turn commits."""
        pcm, _ = await synthesize(tts, text)
        mark = now()
        await send_pcm(pcm)
        end = now()
        while not seen("stt.final", after=mark):
            await send_pcm(b"\x00\x00" * UPLINK_FRAME_SAMPLES * 5)
            if now() - end > 15:
                raise TimeoutError("turn never committed")
        commit_t, final = seen("stt.final", after=mark)[0]
        print(f"  [{commit_t:6.2f}s] committed {int((commit_t - end) * 1000)} ms after speech end: {final['text']!r}")
        return commit_t

    reader = asyncio.create_task(receiver())
    await ws.send(json.dumps({
        "type": "hello",
        "user_info": {"name": "测试用户"},
        "caps": {"aec": True, "sample_rate": 16000, "playback_receipts": False},
    }))
    await wait("session")
    await wait("state", lambda f: f["value"] == "listening")

    metrics: dict = {"followup_spoken": [], "readback_spoken": []}
    answer = "大概三天了，疼得比较厉害，没有别的症状。"
    commit = await say("我头疼。")
    confirm_commit = None
    for _ in range(5):
        deadline = time.perf_counter() + 120
        while time.perf_counter() < deadline:
            if seen("interrupt", after=commit) or seen("card", after=commit) or seen("error", after=commit):
                break
            await asyncio.sleep(0.05)
        if seen("card", after=commit) or seen("error", after=commit):
            break
        t, interrupt = seen("interrupt", after=commit)[0]
        audio_t = await spoken_at(interrupt["content"], commit)
        key = "readback_spoken" if interrupt["kind"] == "confirm" else "followup_spoken"
        metrics[key].append(audio_t - commit if audio_t else None)
        print(f"  [{t:6.2f}s] {interrupt['kind']}: {interrupt['content']!r} — spoken {int((audio_t - commit) * 1000) if audio_t else None} ms after commit")
        if interrupt["kind"] == "confirm":
            commit = confirm_commit = await say("对的。")
        else:
            commit = await say(answer)

    errors = seen("error")
    if errors:
        print("  errors:", [f for _, f in errors])
    if confirm_commit is not None and seen("card", after=confirm_commit):
        text_t = seen("text", after=confirm_commit)[0][0]
        card_t, card = seen("card", after=confirm_commit)[0]
        fillers = {"我还在整理建议，请稍等。"}
        spoken = seen("tts.sentence", lambda f: f["text"] not in fillers, after=confirm_commit)
        audio_t = None
        if spoken:
            await wait("state", lambda f: f["value"] == "listening", after=max(spoken[0][0], card_t))
            audio_t = sentence_first_audio.get(spoken[0][1]["sentence_id"])
        metrics.update(
            conclusion_first_text=text_t - confirm_commit,
            conclusion_first_audio=(audio_t - confirm_commit) if audio_t else None,
            conclusion_card=card_t - confirm_commit,
            conclusion_spoken=[f["text"] for _, f in spoken],
            fillers=[f["text"] for _, f in seen("tts.sentence", lambda f: f["text"] in fillers, after=confirm_commit)],
            summary=card["payload"]["data"]["summary"],
        )
    await ws.send(json.dumps({"type": "bye"}))
    await asyncio.wait_for(reader, 10)
    summary = seen("summary")
    closed = seen("_closed")
    metrics["status"] = summary[0][1]["payload"]["data"]["status"] if summary else None
    metrics["close"] = closed[0][1]["code"] if closed else None
    return metrics


async def e2e(url: str, calls: int) -> None:
    _, tts = _providers()
    for index in range(calls):
        label = "cold (first call after server start)" if index == 0 else "warm"
        print(f"call {index + 1} — {label}")
        m = await one_call(url, tts)

        def ms(value):
            return f"{int(value * 1000)}" if isinstance(value, (int, float)) else "-"

        print(
            f"  follow-up spoken after commit: {[ms(v) for v in m['followup_spoken']]} ms; "
            f"read-back spoken after commit: {[ms(v) for v in m['readback_spoken']]} ms"
        )
        print(
            f"  conclusion after confirm: first text {ms(m.get('conclusion_first_text'))} ms, "
            f"first spoken audio {ms(m.get('conclusion_first_audio'))} ms, card {ms(m.get('conclusion_card'))} ms"
        )
        print(f"  spoken conclusion={m.get('conclusion_spoken')} fillers={m.get('fillers')}")
        print(f"  card summary={m.get('summary')!r} status={m['status']} close={m['close']}")
    await tts.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("loopback", "e2e"))
    parser.add_argument("--url", default=os.environ.get("VOICE_WS_URL", "ws://localhost:8000/api/voice"))
    parser.add_argument("--calls", type=int, default=1, help="consecutive calls on one server (1st = cold)")
    args = parser.parse_args()
    asyncio.run(loopback() if args.mode == "loopback" else e2e(args.url, args.calls))


if __name__ == "__main__":
    main()
