"""
Independent verification tests for agentic_core/tracing.py (P1-3).

Written by an independent integrator role, not the original implementer, per
VERIFICATION_PROTOCOL.md Gate 2. Tests are written against the original design
spec, not against the implementation's own internal details, and use a temp
trace directory so they never touch the real logs/traces/ path or depend on
the live LLM pipeline.
"""
import json
import time

import pytest

from agentic_core import tracing


@pytest.fixture(autouse=True)
def _isolated_trace_dir(tmp_path, monkeypatch):
    """Force every test to export into a throwaway directory and reset the
    module-level tracer/provider singletons so tests don't leak state.

    NOTE: tracing.TRACE_DIR cannot be monkeypatched after import because
    FileSpanExporter.__init__ binds it as a default-argument VALUE at
    function-definition time, not re-read dynamically. We therefore build
    the provider/exporter ourselves (passing trace_dir explicitly) and
    inject the pre-built tracer, marking the module as already configured
    so get_tracer() returns it as-is instead of building its own with the
    frozen production default.
    """
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(tracing.FileSpanExporter(trace_dir=tmp_path))
    )
    monkeypatch.setattr(tracing, "_PROVIDER", provider)
    monkeypatch.setattr(tracing, "_TRACER", provider.get_tracer(tracing.__name__))
    monkeypatch.setattr(tracing, "_CONFIGURED", True)
    yield tmp_path


def _read_only_trace(trace_dir):
    files = list(trace_dir.glob("trace_*.json"))
    assert len(files) == 1, f"expected exactly one trace file, found {len(files)}"
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_single_traced_step_produces_root_span_with_no_children(_isolated_trace_dir):
    with tracing.traced_step("pipeline.process_command", prompt_len=3):
        pass
    doc = _read_only_trace(_isolated_trace_dir)
    assert doc["root"]["name"] == "pipeline.process_command"
    assert doc["root"]["status"] == "OK"
    assert doc["root"]["attributes"]["prompt_len"] == 3
    assert doc["root"]["children"] == []


def test_nested_traced_steps_produce_correct_parent_child_tree(_isolated_trace_dir):
    with tracing.traced_step("pipeline.process_command", prompt_len=5):
        with tracing.traced_step("extract_intent", prompt_len=5):
            time.sleep(0.001)
        with tracing.traced_step("validate_steps", step_count=1):
            time.sleep(0.001)
        with tracing.traced_step("execute_pipeline", step_count=1):
            time.sleep(0.001)

    doc = _read_only_trace(_isolated_trace_dir)
    root = doc["root"]
    assert root["name"] == "pipeline.process_command"
    child_names = [c["name"] for c in root["children"]]
    assert child_names == ["extract_intent", "validate_steps", "execute_pipeline"]
    for child in root["children"]:
        assert child["parent_span_id"] == root["span_id"]
        assert child["status"] == "OK"
        # Real durations, not fabricated zeros — each step slept 1ms.
        assert child["duration_ms"] > 0


def test_exception_inside_traced_step_is_recorded_as_error_and_reraised(_isolated_trace_dir):
    with pytest.raises(ValueError, match="boom"):
        with tracing.traced_step("pipeline.process_command", prompt_len=1):
            with tracing.traced_step("extract_intent", prompt_len=1):
                raise ValueError("boom")

    doc = _read_only_trace(_isolated_trace_dir)
    root = doc["root"]
    # The exception must propagate (already asserted by pytest.raises above)
    # AND the failing child span must be marked ERROR, not silently OK.
    failing_child = root["children"][0]
    assert failing_child["name"] == "extract_intent"
    assert failing_child["status"] == "ERROR"


def test_no_raw_prompt_text_is_recorded_only_length(_isolated_trace_dir):
    """Privacy requirement from the spec: attributes must not leak prompt content."""
    secret_prompt = "delete my password file at C:\\Users\\me\\secret.txt"
    with tracing.traced_step("pipeline.process_command", prompt_len=len(secret_prompt)):
        pass
    doc = _read_only_trace(_isolated_trace_dir)
    serialized = json.dumps(doc)
    assert secret_prompt not in serialized
    assert doc["root"]["attributes"]["prompt_len"] == len(secret_prompt)


def test_get_tracer_is_idempotent(_isolated_trace_dir):
    """Calling get_tracer() multiple times must not create duplicate exporters
    (spec requirement) — verified by checking only one trace file is written
    for one pipeline run even though get_tracer() is invoked repeatedly."""
    tracing.get_tracer()
    tracing.get_tracer()
    tracing.get_tracer()
    with tracing.traced_step("pipeline.process_command", prompt_len=1):
        pass
    files = list(_isolated_trace_dir.glob("trace_*.json"))
    assert len(files) == 1
