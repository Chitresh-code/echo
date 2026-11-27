from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from strands.telemetry import tracer as sdk_tracer

from apps.usage.services import tracing


def test_content_is_redacted_unless_asked_for():
    env = {"OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental,gen_ai_unredacted_attributes=gen_ai.output.*"}
    tracing.configure(env)
    # The operator's own allow list is dropped: content is all or nothing.
    assert env["OTEL_SEMCONV_STABILITY_OPT_IN"] == "gen_ai_latest_experimental,gen_ai_unredacted_attributes="
    assert env["OTEL_SERVICE_NAME"] == "echo"

    env = {"ECHO_TRACE_CONTENT": "true", "OTEL_SERVICE_NAME": "echo-staging"}
    tracing.configure(env)
    assert "gen_ai_unredacted_attributes" not in env["OTEL_SEMCONV_STABILITY_OPT_IN"]
    assert env["OTEL_SERVICE_NAME"] == "echo-staging"


def _spans(monkeypatch, opt_in):
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", opt_in)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = sdk_tracer.Tracer()
    tracer.tracer = provider.get_tracer("test")
    tracing.configure({"OTEL_SEMCONV_STABILITY_OPT_IN": opt_in, "ECHO_TRACE_CONTENT": "true"})
    span = tracer.tracer.start_span("memory.add")
    tracer._add_event(span, "memory.content", {"content": "the user's secret"})
    tracer._add_event(span, "other", {"content": "kept"})
    span.end()
    return {e.name: dict(e.attributes) for e in exporter.get_finished_spans()[0].events}


def test_memory_events_follow_the_redaction(monkeypatch):
    events = _spans(monkeypatch, "gen_ai_unredacted_attributes=")
    assert events["memory.content"] == {"content": "[REDACTED]"}
    assert events["other"] == {"content": "kept"}
    assert _spans(monkeypatch, "")["memory.content"] == {"content": "the user's secret"}


def test_spans_carry_ids_not_emails():
    assert tracing.turn_attributes("u1", "w1", "c1") == {"user.id": "u1", "session.id": "c1", "echo.workspace_id": "w1"}
