import os
import unittest
from unittest.mock import patch

from agents.llm import (
    LLMConfigurationError,
    get_chat_llm,
    resolve_model_settings,
)


class ModelSettingsTests(unittest.TestCase):
    def test_legacy_ark_configuration_remains_the_default(self):
        settings = resolve_model_settings({"ARK_API_KEY": "ark-secret"})

        self.assertEqual(settings.provider, "ark")
        self.assertEqual(settings.model, "doubao-seed-1-6-flash-250828")
        self.assertEqual(settings.base_url, "https://ark.cn-beijing.volces.com/api/v3")
        self.assertEqual(settings.extra_body, {"thinking": {"type": "disabled"}})

    def test_named_openai_compatible_providers_use_their_own_credentials(self):
        cases = [
            (
                {
                    "LLM_PROVIDER": "openai",
                    "OPENAI_API_KEY": "openai-secret",
                    "OPENAI_MODEL": "gpt-test",
                },
                "openai",
                "gpt-test",
                None,
            ),
            (
                {
                    "LLM_PROVIDER": "deepseek",
                    "DEEPSEEK_API_KEY": "deepseek-secret",
                    "DEEPSEEK_MODEL": "deepseek-test",
                },
                "deepseek",
                "deepseek-test",
                "https://api.deepseek.com",
            ),
            (
                {
                    "LLM_PROVIDER": "qwen",
                    "DASHSCOPE_API_KEY": "qwen-secret",
                    "QWEN_MODEL": "qwen-test",
                },
                "qwen",
                "qwen-test",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            (
                {
                    "LLM_PROVIDER": "glm",
                    "ZAI_API_KEY": "zhipu-secret",
                    "ZHIPU_MODEL": "glm-test",
                },
                "zhipu",
                "glm-test",
                "https://open.bigmodel.cn/api/paas/v4",
            ),
        ]

        for env, provider, model, base_url in cases:
            with self.subTest(provider=provider):
                settings = resolve_model_settings(env)
                self.assertEqual(settings.provider, provider)
                self.assertEqual(settings.model, model)
                self.assertEqual(settings.base_url, base_url)

    def test_generic_configuration_supports_any_compatible_provider(self):
        settings = resolve_model_settings(
            {
                "LLM_PROVIDER": "openai-compatible",
                "LLM_API_KEY": "custom-secret",
                "LLM_MODEL": "vendor-model",
                "LLM_BASE_URL": "https://llm.example.com/v1",
            }
        )

        self.assertEqual(settings.provider, "custom")
        self.assertEqual(settings.model, "vendor-model")
        self.assertEqual(settings.base_url, "https://llm.example.com/v1")
        self.assertIsNone(settings.extra_body)

    def test_vision_can_override_the_chat_model_while_reusing_the_provider(self):
        settings = resolve_model_settings(
            {
                "LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "openai-secret",
                "OPENAI_MODEL": "text-model",
                "VISION_MODEL": "vision-model",
            },
            purpose="vision",
        )

        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.model, "vision-model")
        self.assertEqual(settings.api_key, "openai-secret")

    def test_separate_vision_provider_uses_its_own_credentials(self):
        settings = resolve_model_settings(
            {
                "LLM_PROVIDER": "openai",
                "LLM_API_KEY": "chat-secret",
                "LLM_MODEL": "text-model",
                "VISION_PROVIDER": "qwen",
                "DASHSCOPE_API_KEY": "vision-secret",
                "QWEN_VISION_MODEL": "qwen-vision-model",
            },
            purpose="vision",
        )

        self.assertEqual(settings.provider, "qwen")
        self.assertEqual(settings.api_key, "vision-secret")
        self.assertEqual(settings.model, "qwen-vision-model")

    def test_missing_provider_credentials_raise_a_safe_configuration_error(self):
        with self.assertRaises(LLMConfigurationError) as context:
            resolve_model_settings(
                {"LLM_PROVIDER": "deepseek", "DEEPSEEK_MODEL": "deepseek-test"}
            )

        message = str(context.exception)
        self.assertIn("LLM_API_KEY", message)
        self.assertIn("DEEPSEEK_API_KEY", message)
        self.assertNotIn("deepseek-test", message)

    def test_custom_provider_requires_a_base_url(self):
        with self.assertRaisesRegex(LLMConfigurationError, "LLM_BASE_URL"):
            resolve_model_settings(
                {
                    "LLM_PROVIDER": "custom",
                    "LLM_API_KEY": "custom-secret",
                    "LLM_MODEL": "vendor-model",
                }
            )

    def test_factory_builds_chat_openai_from_generic_settings(self):
        env = {
            "LLM_PROVIDER": "custom",
            "LLM_API_KEY": "custom-secret",
            "LLM_MODEL": "vendor-model",
            "LLM_BASE_URL": "https://llm.example.com/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            llm = get_chat_llm("precise", streaming=False)

        self.assertEqual(llm.model_name, "vendor-model")
        self.assertEqual(str(llm.openai_api_base), "https://llm.example.com/v1")
        self.assertEqual(llm.temperature, 0.2)
        self.assertFalse(llm.streaming)
        self.assertIsNone(llm.extra_body)


if __name__ == "__main__":
    unittest.main()
