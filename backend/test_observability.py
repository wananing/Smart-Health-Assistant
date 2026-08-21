import os
import unittest
from unittest.mock import patch

from observability import (
    ObservabilityConfigurationError,
    build_trace_config_kwargs,
    configure_observability,
    resolve_observability_settings,
)


class ObservabilitySettingsTests(unittest.TestCase):
    def test_observability_is_disabled_without_an_explicit_backend(self):
        settings = resolve_observability_settings({})

        self.assertEqual(settings.provider, "none")
        self.assertEqual(settings.service_name, "smart-health-assistant")
        self.assertFalse(settings.trace_content)
        self.assertFalse(settings.trace_images)

    def test_existing_langsmith_key_keeps_backward_compatibility(self):
        settings = resolve_observability_settings(
            {"LANGCHAIN_API_KEY": "langsmith-secret"}
        )

        self.assertEqual(settings.provider, "langsmith")

    def test_current_langsmith_environment_names_are_supported(self):
        settings = resolve_observability_settings(
            {
                "LANGSMITH_API_KEY": "langsmith-secret",
                "LANGSMITH_PROJECT": "current-project",
            }
        )

        self.assertEqual(settings.provider, "langsmith")
        self.assertEqual(settings.langsmith_project, "current-project")

    def test_otel_uses_standard_environment_names(self):
        settings = resolve_observability_settings(
            {
                "OBSERVABILITY_PROVIDER": "otel",
                "OTEL_SERVICE_NAME": "health-agent",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://collector:4318/v1/traces",
                "TRACE_CONTENT": "true",
                "TRACE_IMAGES": "1",
            }
        )

        self.assertEqual(settings.provider, "otel")
        self.assertEqual(settings.service_name, "health-agent")
        self.assertEqual(
            settings.otlp_endpoint, "http://collector:4318/v1/traces"
        )
        self.assertTrue(settings.trace_content)
        self.assertTrue(settings.trace_images)

    def test_otel_accepts_the_shared_exporter_endpoint(self):
        settings = resolve_observability_settings(
            {
                "OBSERVABILITY_PROVIDER": "otel",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/",
            }
        )

        self.assertEqual(
            settings.otlp_endpoint, "http://collector:4318/v1/traces"
        )

    def test_medical_content_is_hidden_by_default(self):
        settings = resolve_observability_settings(
            {"OBSERVABILITY_PROVIDER": "otel"}
        )

        trace_config = build_trace_config_kwargs(settings)

        for field in (
            "hide_inputs",
            "hide_outputs",
            "hide_input_messages",
            "hide_output_messages",
            "hide_input_text",
            "hide_output_text",
            "hide_input_images",
            "hide_llm_invocation_parameters",
            "hide_prompts",
            "hide_llm_tools",
            "hide_choices",
            "hide_embeddings_text",
            "hide_embedding_vectors",
        ):
            self.assertTrue(trace_config[field], field)

    def test_privacy_policy_matches_the_installed_openinference_api(self):
        from openinference.instrumentation import TraceConfig

        settings = resolve_observability_settings(
            {"OBSERVABILITY_PROVIDER": "otel"}
        )

        config = TraceConfig(**build_trace_config_kwargs(settings))

        self.assertTrue(config.hide_inputs)

    def test_langchain_spans_redact_medical_content_by_default(self):
        from langchain_core.runnables import RunnableLambda
        from openinference.instrumentation import TraceConfig, using_attributes
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        settings = resolve_observability_settings(
            {"OBSERVABILITY_PROVIDER": "otel"}
        )
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        instrumentor = LangChainInstrumentor()
        instrumentor.instrument(
            tracer_provider=provider,
            config=TraceConfig(**build_trace_config_kwargs(settings)),
        )
        try:
            with using_attributes(
                session_id="eval:test-case",
                tags=["evaluation"],
            ):
                RunnableLambda(lambda value: f"result:{value}").invoke(
                    "PRIVATE-MEDICAL-CONTENT"
                )
        finally:
            instrumentor.uninstrument()
            provider.shutdown()

        attributes = " ".join(
            str(dict(span.attributes)) for span in exporter.get_finished_spans()
        )
        self.assertNotIn("PRIVATE-MEDICAL-CONTENT", attributes)
        self.assertIn("__REDACTED__", attributes)
        self.assertIn("eval:test-case", attributes)

    def test_openai_spans_redact_vision_inputs_by_default(self):
        import httpx
        from openai import OpenAI
        from openinference.instrumentation import TraceConfig
        from openinference.instrumentation.openai import OpenAIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "vision-test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        settings = resolve_observability_settings(
            {"OBSERVABILITY_PROVIDER": "otel"}
        )
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        instrumentor = OpenAIInstrumentor()
        instrumentor.instrument(
            tracer_provider=provider,
            config=TraceConfig(**build_trace_config_kwargs(settings)),
        )
        try:
            client = OpenAI(
                api_key="test-secret",
                base_url="https://example.test/v1",
                http_client=httpx.Client(transport=httpx.MockTransport(respond)),
            )
            client.chat.completions.create(
                model="vision-test",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "read report"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,PRIVATE-REPORT-IMAGE"
                                },
                            },
                        ],
                    }
                ],
            )
        finally:
            instrumentor.uninstrument()
            provider.shutdown()

        attributes = " ".join(
            str(dict(span.attributes)) for span in exporter.get_finished_spans()
        )
        self.assertNotIn("PRIVATE-REPORT-IMAGE", attributes)
        self.assertNotIn("read report", attributes)
        self.assertIn("__REDACTED__", attributes)

    def test_image_tracing_requires_a_separate_opt_in(self):
        settings = resolve_observability_settings(
            {
                "OBSERVABILITY_PROVIDER": "otel",
                "TRACE_CONTENT": "true",
            }
        )

        trace_config = build_trace_config_kwargs(settings)

        self.assertTrue(trace_config["hide_inputs"])
        self.assertFalse(trace_config["hide_output_text"])
        self.assertTrue(trace_config["hide_input_images"])
        self.assertTrue(trace_config["hide_embedding_vectors"])

    def test_image_data_cannot_leak_through_the_generic_input_value(self):
        from langchain_core.language_models.fake_chat_models import (
            FakeListChatModel,
        )
        from langchain_core.messages import HumanMessage
        from openinference.instrumentation import TraceConfig
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        settings = resolve_observability_settings(
            {
                "OBSERVABILITY_PROVIDER": "otel",
                "TRACE_CONTENT": "true",
                "TRACE_IMAGES": "false",
            }
        )
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        instrumentor = LangChainInstrumentor()
        instrumentor.instrument(
            tracer_provider=provider,
            config=TraceConfig(**build_trace_config_kwargs(settings)),
        )
        try:
            FakeListChatModel(responses=["ok"]).invoke(
                [
                    HumanMessage(
                        content=[
                            {"type": "text", "text": "report"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,PRIVATE-IMAGE-DATA"
                                },
                            },
                        ]
                    )
                ]
            )
        finally:
            instrumentor.uninstrument()
            provider.shutdown()

        attributes = " ".join(
            str(dict(span.attributes)) for span in exporter.get_finished_spans()
        )
        self.assertNotIn("PRIVATE-IMAGE-DATA", attributes)

    def test_invalid_provider_fails_fast(self):
        with self.assertRaisesRegex(
            ObservabilityConfigurationError, "OBSERVABILITY_PROVIDER"
        ):
            resolve_observability_settings({"OBSERVABILITY_PROVIDER": "unknown"})


class LangSmithCompatibilityTests(unittest.TestCase):
    def test_langsmith_provider_preserves_the_existing_environment_contract(self):
        settings = resolve_observability_settings(
            {
                "OBSERVABILITY_PROVIDER": "langsmith",
                "LANGCHAIN_API_KEY": "langsmith-secret",
                "LANGCHAIN_PROJECT": "health-evals",
            }
        )

        with patch.dict(os.environ, {}, clear=True):
            runtime = configure_observability(settings)

            self.assertEqual(runtime.provider, "langsmith")
            self.assertEqual(
                os.environ["LANGSMITH_API_KEY"], "langsmith-secret"
            )
            self.assertEqual(os.environ["LANGSMITH_TRACING"], "true")
            self.assertEqual(os.environ["LANGCHAIN_TRACING_V2"], "true")
            self.assertEqual(os.environ["LANGCHAIN_PROJECT"], "health-evals")
            self.assertEqual(os.environ["LANGSMITH_HIDE_INPUTS"], "true")
            self.assertEqual(os.environ["LANGSMITH_HIDE_OUTPUTS"], "true")
            self.assertEqual(os.environ["LANGSMITH_HIDE_METADATA"], "true")

    def test_explicit_langsmith_provider_requires_a_key(self):
        settings = resolve_observability_settings(
            {"OBSERVABILITY_PROVIDER": "langsmith"}
        )

        with self.assertRaisesRegex(
            ObservabilityConfigurationError, "LANGCHAIN_API_KEY"
        ):
            configure_observability(settings)


if __name__ == "__main__":
    unittest.main()
