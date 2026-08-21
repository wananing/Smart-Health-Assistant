"""Provider-neutral tracing configuration for the agent runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import os


class ObservabilityConfigurationError(RuntimeError):
    """Raised when tracing is enabled with an invalid configuration."""


@dataclass(frozen=True)
class ObservabilitySettings:
    provider: str
    service_name: str
    otlp_endpoint: str
    trace_content: bool
    trace_images: bool
    langsmith_project: str
    langsmith_api_key: str = field(repr=False)


@dataclass
class ObservabilityRuntime:
    provider: str
    _shutdown_callback: Callable[[], None] | None = field(
        default=None, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._shutdown_callback is not None:
            self._shutdown_callback()


def _read_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ObservabilityConfigurationError(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off"
    )


def resolve_observability_settings(
    env: Mapping[str, str] | None = None,
) -> ObservabilitySettings:
    source = os.environ if env is None else env
    raw_provider = source.get("OBSERVABILITY_PROVIDER", "").strip().lower()
    langsmith_api_key = (
        source.get("LANGSMITH_API_KEY", "").strip()
        or source.get("LANGCHAIN_API_KEY", "").strip()
    )
    aliases = {
        "": "langsmith" if langsmith_api_key else "none",
        "off": "none",
        "disabled": "none",
        "opentelemetry": "otel",
    }
    provider = aliases.get(raw_provider, raw_provider)
    if provider not in {"none", "otel", "langsmith"}:
        raise ObservabilityConfigurationError(
            "OBSERVABILITY_PROVIDER must be one of: none, otel, langsmith"
        )

    otlp_endpoint = source.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", ""
    ).strip()
    if not otlp_endpoint:
        shared_endpoint = source.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if shared_endpoint:
            otlp_endpoint = f"{shared_endpoint.rstrip('/')}/v1/traces"
        else:
            otlp_endpoint = "http://localhost:4318/v1/traces"

    return ObservabilitySettings(
        provider=provider,
        service_name=source.get(
            "OTEL_SERVICE_NAME", "smart-health-assistant"
        ).strip()
        or "smart-health-assistant",
        otlp_endpoint=otlp_endpoint,
        trace_content=_read_bool(source, "TRACE_CONTENT", False),
        trace_images=_read_bool(source, "TRACE_IMAGES", False),
        langsmith_project=(
            source.get("LANGSMITH_PROJECT", "").strip()
            or source.get("LANGCHAIN_PROJECT", "").strip()
        )
        or "bigh-health-assistant",
        langsmith_api_key=langsmith_api_key,
    )


def build_trace_config_kwargs(settings: ObservabilitySettings) -> dict[str, bool]:
    """Build a conservative OpenInference privacy policy.

    Text content requires an explicit opt-in. Images and embedding vectors use
    stricter controls because reports can contain identity and medical data.
    """
    hide_content = not settings.trace_content
    hide_inputs = not (settings.trace_content and settings.trace_images)
    return {
        # LangChain also serializes image data into the generic input.value.
        # Keep the whole input hidden until both content flags are enabled.
        "hide_inputs": hide_inputs,
        "hide_outputs": hide_content,
        "hide_input_messages": hide_content,
        "hide_output_messages": hide_content,
        "hide_input_images": not settings.trace_images,
        "hide_input_text": hide_content,
        "hide_output_text": hide_content,
        "hide_embedding_vectors": True,
        "hide_embeddings_text": True,
        "hide_llm_invocation_parameters": hide_content,
        "hide_prompts": hide_content,
        "hide_llm_tools": hide_content,
        "hide_choices": hide_content,
    }


def _configure_otel(settings: ObservabilitySettings) -> ObservabilityRuntime:
    try:
        from openinference.instrumentation import TraceConfig
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from openinference.instrumentation.openai import OpenAIInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise ObservabilityConfigurationError(
            "OTel tracing dependencies are missing; run `uv sync` in backend/"
        ) from exc

    tracer_provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: settings.service_name})
    )
    exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)

    trace_config = TraceConfig(**build_trace_config_kwargs(settings))
    instrumentors = [LangChainInstrumentor(), OpenAIInstrumentor()]
    for instrumentor in instrumentors:
        instrumentor.instrument(
            tracer_provider=tracer_provider,
            config=trace_config,
        )

    def shutdown() -> None:
        for instrumentor in reversed(instrumentors):
            instrumentor.uninstrument()
        tracer_provider.shutdown()

    return ObservabilityRuntime(provider="otel", _shutdown_callback=shutdown)


def configure_observability(
    settings: ObservabilitySettings | None = None,
) -> ObservabilityRuntime:
    resolved = settings or resolve_observability_settings()
    if resolved.provider == "none":
        return ObservabilityRuntime(provider="none")
    if resolved.provider == "otel":
        return _configure_otel(resolved)

    if not resolved.langsmith_api_key:
        raise ObservabilityConfigurationError(
            "LANGSMITH_API_KEY (or legacy LANGCHAIN_API_KEY) is required when "
            "OBSERVABILITY_PROVIDER=langsmith"
        )
    os.environ.setdefault("LANGSMITH_API_KEY", resolved.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_API_KEY", resolved.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", resolved.langsmith_project)
    os.environ.setdefault("LANGCHAIN_PROJECT", resolved.langsmith_project)
    if not (resolved.trace_content and resolved.trace_images):
        os.environ.setdefault("LANGSMITH_HIDE_INPUTS", "true")
    if not resolved.trace_content:
        os.environ.setdefault("LANGSMITH_HIDE_OUTPUTS", "true")
        os.environ.setdefault("LANGSMITH_HIDE_METADATA", "true")
    return ObservabilityRuntime(provider="langsmith")
