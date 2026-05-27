"""OpenTelemetry tracing setup (§7.4)."""

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_tracer: trace.Tracer | None = None


def configure_tracing(
    service_name: str = "studio",
    otlp_endpoint: str | None = None,
) -> None:
    """Configure OpenTelemetry with OTLP export (Jaeger) or console fallback."""
    resource = Resource(attributes={SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    global _tracer
    _tracer = trace.get_tracer(service_name)


def get_tracer() -> trace.Tracer:
    if _tracer is None:
        return trace.get_tracer("studio")
    return _tracer
