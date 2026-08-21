import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

with patch("dotenv.load_dotenv"):
    from main import ChatMessage, ChatRequest, chat


class ChatEndpointConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_accepts_a_non_ark_provider_configuration(self):
        env = {
            "LLM_PROVIDER": "custom",
            "LLM_API_KEY": "custom-secret",
            "LLM_MODEL": "vendor-model",
            "LLM_BASE_URL": "https://llm.example.com/v1",
        }
        request = ChatRequest(messages=[ChatMessage(role="user", content="你好")])

        with patch.dict(os.environ, env, clear=True):
            response = await chat(request)

        self.assertIsInstance(response, StreamingResponse)

    async def test_chat_rejects_an_incomplete_provider_configuration(self):
        request = ChatRequest(messages=[ChatMessage(role="user", content="你好")])

        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek", "DEEPSEEK_MODEL": "deepseek-test"},
            clear=True,
        ):
            with self.assertRaises(HTTPException) as context:
                await chat(request)

        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("DEEPSEEK_API_KEY", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
