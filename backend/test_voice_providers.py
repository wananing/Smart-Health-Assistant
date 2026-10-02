"""Deterministic tests for ASR/TTS provider resolution (voice/providers)."""
import asyncio
import unittest

from voice.cues import CUE_TEXTS, CueCache
from voice.providers import (
    SpeechConfigurationError,
    create_asr_provider,
    create_tts_provider,
    load_speech_providers,
    resolve_speech_settings,
)
from voice.providers.fake import FakeAsrProvider, FakeTtsProvider


class SpeechSettingsTests(unittest.TestCase):
    def test_unset_provider_disables_voice_with_a_clear_message(self):
        with self.assertRaisesRegex(SpeechConfigurationError, "ASR_PROVIDER is not set"):
            resolve_speech_settings({}, purpose="asr")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(SpeechConfigurationError, "Unsupported TTS_PROVIDER"):
            resolve_speech_settings({"TTS_PROVIDER": "acme"}, purpose="tts")

    def test_fake_needs_no_credentials(self):
        settings = resolve_speech_settings({"ASR_PROVIDER": "fake"}, purpose="asr")
        self.assertEqual(settings.provider, "fake")
        self.assertIsInstance(create_asr_provider(settings), FakeAsrProvider)

    def test_volcengine_accepts_an_api_key_or_an_app_token_pair(self):
        by_key = resolve_speech_settings(
            {"ASR_PROVIDER": "doubao", "VOLC_SPEECH_API_KEY": "key"}, purpose="asr"
        )
        self.assertEqual(by_key.provider, "volcengine")
        self.assertTrue(by_key.endpoint.startswith("wss://"))
        by_pair = resolve_speech_settings(
            {"ASR_PROVIDER": "volc", "VOLC_SPEECH_APP_ID": "app", "VOLC_SPEECH_ACCESS_TOKEN": "tok"},
            purpose="asr",
        )
        self.assertEqual((by_pair.app_id, by_pair.access_token), ("app", "tok"))
        with self.assertRaisesRegex(SpeechConfigurationError, "VOLC_SPEECH_API_KEY"):
            resolve_speech_settings({"ASR_PROVIDER": "volcengine", "VOLC_SPEECH_APP_ID": "app"}, purpose="asr")

    def test_volcengine_tts_defaults_and_secrets_stay_out_of_repr(self):
        env = {"TTS_PROVIDER": "volcengine", "VOLC_VOICE_API_KEY": "secret-key"}
        settings = resolve_speech_settings(env, purpose="tts")
        self.assertEqual(settings.voice, "zh_female_shuangkuaisisi_moon_bigtts")
        self.assertEqual(settings.resource_id, "seed-tts-1.0")
        self.assertEqual(settings.endpoint, "wss://openspeech.bytedance.com/api/v3/tts/bidirection")
        self.assertNotIn("secret-key", repr(settings))
        self.assertEqual(
            resolve_speech_settings({**env, "TTS_SPEAKER": "v2"}, purpose="tts").voice, "v2"
        )

    def test_the_users_volcengine_env_names_are_accepted(self):
        env = {
            "ASR_PROVIDER": "volcengine",
            "VOLC_VOICE_API_KEY": "k",
            "ASR_URL": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream",
            "ASR_RESOURCE_ID": "volc.seedasr.sauc.duration",
            "ASR_MODEL_NAME": "bigmodel",
            "ASR_END_WINDOW_MS": "800",
        }
        settings = resolve_speech_settings(env, purpose="asr")
        self.assertEqual(settings.api_key, "k")
        self.assertTrue(settings.endpoint.endswith("bigmodel_nostream"))
        self.assertEqual((settings.model, settings.end_window_ms), ("bigmodel", 800))
        default = resolve_speech_settings({"ASR_PROVIDER": "volcengine", "VOLC_VOICE_API_KEY": "k"}, purpose="asr")
        self.assertTrue(default.endpoint.endswith("bigmodel_async"))
        with self.assertRaises(SpeechConfigurationError):
            resolve_speech_settings({**env, "ASR_URL": "https://x"}, purpose="asr")
        with self.assertRaises(SpeechConfigurationError):
            resolve_speech_settings({**env, "ASR_END_WINDOW_MS": "50"}, purpose="asr")

    def test_volcengine_capabilities_depend_on_the_endpoint(self):
        from voice.providers.volcengine import VolcAsrProvider, VolcTtsProvider

        base = {"ASR_PROVIDER": "volcengine", "VOLC_VOICE_API_KEY": "k"}
        stream = create_asr_provider(resolve_speech_settings(base, purpose="asr"))
        self.assertIsInstance(stream, VolcAsrProvider)
        self.assertTrue(stream.capabilities.partials)
        self.assertTrue(stream.capabilities.endpoint_events)
        self.assertFalse(stream.capabilities.confidence)
        self.assertAlmostEqual(stream.capabilities.silence_lag, 0.6)
        nostream = create_asr_provider(resolve_speech_settings(
            {**base, "ASR_URL": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"}, purpose="asr"
        ))
        self.assertFalse(nostream.capabilities.partials)
        self.assertTrue(nostream.capabilities.endpoint_events)
        tts = create_tts_provider(resolve_speech_settings(
            {"TTS_PROVIDER": "volcengine", "VOLC_VOICE_API_KEY": "k"}, purpose="tts"
        ))
        self.assertIsInstance(tts, VolcTtsProvider)
        self.assertTrue(tts.capabilities.speed_control)
        self.assertEqual(tts.capabilities.sample_rate, 24000)

    def test_generic_names_override_provider_names(self):
        settings = resolve_speech_settings(
            {"TTS_PROVIDER": "volcengine", "VOLC_SPEECH_API_KEY": "a", "TTS_API_KEY": "b",
             "VOLC_TTS_VOICE": "v1", "TTS_VOICE": "v2", "TTS_SAMPLE_RATE": "16000"},
            purpose="tts",
        )
        self.assertEqual((settings.api_key, settings.voice, settings.sample_rate), ("b", "v2", 16000))
        with self.assertRaises(SpeechConfigurationError):
            resolve_speech_settings({"TTS_PROVIDER": "fake", "TTS_SAMPLE_RATE": "11"}, purpose="tts")

    def test_unimplemented_adapters_refuse_at_configuration_time(self):
        for purpose, factory, env in (
            ("asr", create_asr_provider, {"ASR_PROVIDER": "bailian", "DASHSCOPE_API_KEY": "k"}),
            ("tts", create_tts_provider, {"TTS_PROVIDER": "dashscope", "DASHSCOPE_API_KEY": "k", "DASHSCOPE_TTS_VOICE": "v"}),
        ):
            with self.subTest(env=env):
                settings = resolve_speech_settings(env, purpose=purpose)
                with self.assertRaisesRegex(SpeechConfigurationError, "not implemented"):
                    factory(settings)

    def test_load_speech_providers_builds_both(self):
        asr, tts = load_speech_providers({"ASR_PROVIDER": "fake", "TTS_PROVIDER": "mock"})
        self.assertIsInstance(asr, FakeAsrProvider)
        self.assertIsInstance(tts, FakeTtsProvider)


class DependencyTests(unittest.TestCase):
    def test_websockets_is_a_direct_dependency(self):
        import tomllib
        from pathlib import Path

        project = tomllib.loads(Path(__file__).with_name("pyproject.toml").read_text(encoding="utf-8"))
        names = [dep.split(">")[0].split("=")[0].split("[")[0].strip() for dep in project["project"]["dependencies"]]
        self.assertIn("websockets", names, "uvicorn needs it to serve /api/voice")


class FakeProviderAndCueTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_asr_replays_scripted_events_and_flushes_the_partial(self):
        provider = FakeAsrProvider()
        stream = await provider.open_stream(sample_rate=16000, hotwords=("头疼",))
        self.assertEqual(provider.hotwords, ("头疼",))
        await stream.send_audio(b"\x00\x00")
        stream.push("partial", "头疼")
        event = await anext(stream.events())
        self.assertEqual((event.kind, event.text), ("partial", "头疼"))
        flushed = await stream.flush()
        self.assertEqual((flushed.kind, flushed.text), ("final", "头疼"))
        self.assertEqual(stream.frames_received, 1)

    async def test_cues_are_synthesised_once_and_cached(self):
        tts = FakeTtsProvider(ms_per_char=1.0)
        cache = CueCache(tts, speed=0.85)
        first = await cache.get("opening")
        second = await cache.get("opening")
        self.assertIs(first.pcm, second.pcm)
        self.assertEqual(tts.spoken, [CUE_TEXTS["opening"]])
        self.assertEqual(tts.speeds, [0.85])

    async def test_a_failed_cue_is_screen_only(self):
        cue = await CueCache(FakeTtsProvider(fail=True)).get("safety")
        self.assertIsNone(cue.pcm)
        self.assertEqual(cue.text, CUE_TEXTS["safety"])


if __name__ == "__main__":
    unittest.main()
