"""OpenTelemetry traces of turns, for whoever runs Echo.

The agent SDK emits the spans (each turn, model call, tool call and subagent) and the harness wires
an exporter only when OTEL_TRACES_EXPORTER is set, with the endpoint and headers from the standard
OTEL_EXPORTER_OTLP_* variables. Echo's part is what goes into them: spans name Echo as the service,
and message content (prompts, replies, system prompts, tool inputs and results, remembered facts) is
redacted unless ECHO_TRACE_CONTENT=true, because it holds the user's code and whatever their tools
read, and a trace backend is one more place that would have to be secured for it.
"""

import os
from collections.abc import MutableMapping

from strands.telemetry import tracer as sdk_tracer

CONTENT = "ECHO_TRACE_CONTENT"
OPT_IN = "OTEL_SEMCONV_STABILITY_OPT_IN"
# With an empty list the SDK redacts every attribute it treats as content.
REDACT_ALL = "gen_ai_unredacted_attributes="
# The SDK writes memory searches and additions without its redaction, so Echo redacts them itself.
MEMORY_EVENTS = frozenset({"memory.query", "memory.results", "memory.content"})


def content_on(environ: MutableMapping[str, str] = os.environ) -> bool:
    return environ.get(CONTENT, "").strip().lower() == "true"


def configure(environ: MutableMapping[str, str] = os.environ) -> None:
    """Run before any agent is built: the SDK reads these settings once, when its tracer is made."""
    environ.setdefault("OTEL_SERVICE_NAME", "echo")
    tokens = [t.strip() for t in environ.get(OPT_IN, "").split(",") if t.strip()]
    # An operator's own unredacted list is replaced too: content is all or nothing in Echo.
    tokens = [t for t in tokens if not t.startswith("gen_ai_unredacted_attributes=")]
    if not content_on(environ):
        tokens.append(REDACT_ALL)
    environ[OPT_IN] = ",".join(tokens)
    _redact_memory_events()


def _redact_memory_events() -> None:
    original = sdk_tracer.Tracer._add_event
    if getattr(original, "_echo_redacts_memory", False):
        return

    def add_event(self, span, event_name, event_attributes, to_span_attributes=False):
        if event_name in MEMORY_EVENTS and self._redaction_enabled and event_attributes:
            event_attributes = dict.fromkeys(event_attributes, sdk_tracer.REDACTED_VALUE)
        return original(self, span, event_name, event_attributes, to_span_attributes)

    add_event._echo_redacts_memory = True
    sdk_tracer.Tracer._add_event = add_event


def turn_attributes(user_id: str, workspace_id: str, chat_id: str) -> dict[str, str]:
    """What a turn's spans carry so a backend can group them: Echo's opaque ids, never an email."""
    return {"user.id": user_id, "session.id": chat_id, "echo.workspace_id": workspace_id}
