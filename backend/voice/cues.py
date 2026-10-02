"""
Pre-synthesised prompt cache (提示语).

Openers, the long-wait prompt, "没听清", "您还在吗", the emergency safety line and the
goodbye are fixed sentences. They are synthesised once per TTS voice/speed
with the same voice as everything else, kept in memory, and never enter the
model context or the conversation history. If the TTS vendor goes down after
warm-up, these still play.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from voice.asr import SpeechProviderError
from voice.tts import TtsProvider

CUE_TEXTS: dict[str, str] = {
    "opening": "您好，请说说哪里不舒服。",
    "filler_wait": "我还在整理建议，请稍等。",
    "not_heard": "不好意思没听清，您再说一遍。",
    "not_heard_button": "您说完后可以点一下“说完了”，或者直接打字告诉我。",
    "push_to_talk": "识别不太顺利，您说完后请点一下“说完了”按钮。",
    "still_there": "您还在吗？",
    "slow": "抱歉，我这边有点慢，您再说一遍好吗？",
    # Spoken form of the CRITICAL safety message; "120" is written as it is read.
    "safety": (
        "您描述的情况可能很危险。请立即拨打一二零急救电话，"
        "或者让身边的人马上送您去最近的急诊。请不要自己开车。"
    ),
    "see_screen": "建议已经显示在屏幕上。",
    "handoff": "这个问题我在屏幕上回答您。",
    "emergency_resume": "好的，我们继续问诊。",
    "goodbye": "好的，本次问诊就到这里，小结已经显示在屏幕上，祝您早日康复。",
    "idle_goodbye": "我先挂断了，问诊小结已经显示在屏幕上，您可以随时用文字继续。",
}


@dataclass(frozen=True)
class Cue:
    cue_id: str
    text: str
    pcm: bytes | None  # None when synthesis failed: the cue is screen-only


class CueCache:
    """Per-voice, per-speed cache of synthesised cues."""

    def __init__(self, tts: TtsProvider, *, speed: float = 1.0) -> None:
        self._tts = tts
        self._speed = speed
        self._audio: dict[str, bytes] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def sample_rate(self) -> int:
        return self._tts.capabilities.sample_rate

    async def get(self, cue_id: str) -> Cue:
        text = CUE_TEXTS[cue_id]
        if cue_id in self._audio:
            return Cue(cue_id, text, self._audio[cue_id])
        lock = self._locks.setdefault(cue_id, asyncio.Lock())
        async with lock:
            if cue_id not in self._audio:
                try:
                    chunks = [chunk async for chunk in self._tts.synthesize(text, speed=self._speed)]
                except SpeechProviderError:
                    return Cue(cue_id, text, None)
                self._audio[cue_id] = b"".join(chunks)
        return Cue(cue_id, text, self._audio[cue_id])

    async def warm(self) -> None:
        """Synthesise every cue; failures are left for the next ``get``."""
        for cue_id in CUE_TEXTS:
            await self.get(cue_id)


_SHARED: dict[tuple[int, float], CueCache] = {}


def shared_cue_cache(tts: TtsProvider, *, speed: float = 1.0) -> CueCache:
    """Process-wide cache for one provider instance and speed."""
    key = (id(tts), speed)
    if key not in _SHARED:
        _SHARED[key] = CueCache(tts, speed=speed)
    return _SHARED[key]
