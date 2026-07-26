"""OpenTelemetry tracing helpers for the SentinAL command pipeline."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

TRACE_ROOT_NAME = "pipeline.process_command"
TRACE_DIR = Path("logs") / "traces"

_LOCK = threading.Lock()
_CONFIGURED = False
_TRACER = None
_PROVIDER = None


def _hex_id(value: int, width: int) -> str:
    return format(value, f"0{width}x")


def _span_status(span: ReadableSpan) -> str:
    return "ERROR" if span.status.status_code == StatusCode.ERROR else "OK"


def _span_to_node(span: ReadableSpan) -> dict[str, Any]:
    start_ns = span.start_time or 0
    end_ns = span.end_time or start_ns
    return {
        "name": span.name,
        "span_id": _hex_id(span.context.span_id, 16),
        "parent_span_id": _hex_id(span.parent.span_id, 16) if span.parent else None,
        "start_time": start_ns,
        "end_time": end_ns,
        "duration_ms": (end_ns - start_ns) / 1_000_000,
        "status": _span_status(span),
        "attributes": dict(span.attributes or {}),
        "children": [],
    }


class FileSpanExporter(SpanExporter):
    """Writes one trace tree JSON file when the pipeline root span finishes."""

    def __init__(self, trace_dir: Path = TRACE_DIR):
        self.trace_dir = trace_dir
        self._spans_by_trace: dict[int, list[ReadableSpan]] = {}

    def export(self, spans: Iterable[ReadableSpan]) -> SpanExportResult:
        with _LOCK:
            for span in spans:
                trace_id = span.context.trace_id
                trace_spans = self._spans_by_trace.setdefault(trace_id, [])
                trace_spans.append(span)
                if span.name == TRACE_ROOT_NAME:
                    self._write_trace(trace_id, trace_spans)
                    self._spans_by_trace.pop(trace_id, None)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def _write_trace(self, trace_id: int, spans: list[ReadableSpan]) -> None:
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        nodes = {_hex_id(span.context.span_id, 16): _span_to_node(span) for span in spans}
        root = None

        for node in nodes.values():
            parent_id = node["parent_span_id"]
            if parent_id and parent_id in nodes:
                nodes[parent_id]["children"].append(node)
            elif node["name"] == TRACE_ROOT_NAME:
                root = node

        if root is None:
            return

        for node in nodes.values():
            node["children"].sort(key=lambda child: child["start_time"])

        document = {
            "request_id": str(uuid.uuid4()),
            "trace_id": _hex_id(trace_id, 32),
            "root": root,
        }
        output_path = self.trace_dir / f"trace_{document['request_id']}.json"
        output_path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def get_tracer():
    """Returns a module-level OpenTelemetry tracer configured with FileSpanExporter."""
    global _CONFIGURED, _TRACER, _PROVIDER

    with _LOCK:
        if not _CONFIGURED:
            _PROVIDER = TracerProvider()
            _PROVIDER.add_span_processor(SimpleSpanProcessor(FileSpanExporter()))
            _CONFIGURED = True
        if _TRACER is None:
            _TRACER = _PROVIDER.get_tracer(__name__)
        return _TRACER


@contextmanager
def traced_step(name: str, **attributes):
    """
    Context manager wrapping one pipeline stage.

    Records passed attributes, OK/ERROR status, exceptions, and real span duration.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        else:
            span.set_status(Status(StatusCode.OK))
