from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import os

def setup_tracing(app, service_name="api-gateway"):
    # Configure Resource identifying this service
    resource = Resource(attributes={
        "service.name": service_name
    })

    # Set up TracerProvider
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # Configure OTLP Exporter to send traces to Jaeger/Tempo
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    
    # Add BatchSpanProcessor
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    # Instrument FastAPI application
    FastAPIInstrumentor.instrument_app(app)
    
    return provider
