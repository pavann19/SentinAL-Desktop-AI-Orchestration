# tests/test_skill_abstraction.py
# S8-1 — typed-slot abstraction. Pure functions, no DB, no LLM.

from __future__ import annotations

from agentic_core.skill_abstraction import abstract_skill, fill_skeleton


def _graph(steps, goal="do things"):
    """steps: [(intent, target), ...] -> a GoalGraph.to_dict()-shaped dict."""
    nodes, prev = {}, ""
    for i, (intent, target) in enumerate(steps, 1):
        sid = f"step_{i}"
        nodes[sid] = {
            "intent": intent, "target": target, "prompt": target,
            "depends_on": [prev] if prev else [], "step_id": sid,
            "status": "completed", "result": "ok",
        }
        prev = sid
    return {"goal_description": goal, "nodes": nodes}


def _inst(prompt, steps):
    return {"prompt": prompt, "graph": _graph(steps, prompt)}


# ── happy path ────────────────────────────────────────────────────────────

def test_abstracts_a_varying_filename_into_a_path_slot():
    tpl = abstract_skill([
        _inst("open notepad then delete C:/tmp/a.txt",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/a.txt")]),
        _inst("open notepad then delete C:/tmp/b.txt",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/b.txt")]),
        _inst("open notepad then delete C:/tmp/c.log",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/c.log")]),
    ])
    assert tpl is not None
    assert len(tpl["skeleton"]) == 2
    # step 1 target is a literal (never varied)
    assert tpl["skeleton"][0]["target_template"] == "notepad"
    # step 2 target became a framed slot
    assert tpl["skeleton"][1]["target_template"].startswith("C:/tmp/")
    assert "{" in tpl["skeleton"][1]["target_template"]
    assert len(tpl["slots"]) == 1
    slot = tpl["slots"][0]
    assert slot["type"] == "path"
    assert slot["node_step_id"] == "step_2"
    assert slot["from_prompt"] is True
    assert tpl["postcondition_kind"] == "file_absent"
    assert tpl["origin"] == "learned"
    assert tpl["n_instances"] == 3


def test_no_variation_yields_zero_slots_but_still_a_template():
    tpl = abstract_skill([
        _inst("open notepad and calc", [("ApplicationLaunchIntent", "notepad"),
                                        ("ApplicationLaunchIntent", "calc")]),
        _inst("open notepad and calc", [("ApplicationLaunchIntent", "notepad"),
                                        ("ApplicationLaunchIntent", "calc")]),
    ])
    assert tpl is not None
    assert tpl["slots"] == []
    assert tpl["skeleton"][0]["target_template"] == "notepad"


def test_query_slot_type_for_multiword_middle():
    tpl = abstract_skill([
        _inst("search for python tutorials and open notepad",
              [("InformationRetrievalIntent", "python tutorials"), ("ApplicationLaunchIntent", "notepad")]),
        _inst("search for rust memory safety and open notepad",
              [("InformationRetrievalIntent", "rust memory safety"), ("ApplicationLaunchIntent", "notepad")]),
    ])
    assert tpl is not None
    assert tpl["slots"][0]["type"] == "query"


# ── rejection ────────────────────────────────────────────────────────────

def test_returns_none_for_a_single_instance():
    assert abstract_skill([_inst("x", [("ApplicationLaunchIntent", "notepad")])]) is None


def test_returns_none_when_structures_differ():
    out = abstract_skill([
        _inst("a", [("ApplicationLaunchIntent", "notepad")]),
        _inst("b", [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "x")]),
    ])
    assert out is None


def test_never_raises_on_garbage():
    assert abstract_skill([{"prompt": "x", "graph": None}, {"prompt": "y", "graph": 42}]) is None
    assert abstract_skill([]) is None


# ── fill_skeleton ────────────────────────────────────────────────────────

def test_fill_skeleton_substitutes_slots():
    tpl = abstract_skill([
        _inst("open notepad then delete C:/tmp/a.txt",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/a.txt")]),
        _inst("open notepad then delete C:/tmp/b.csv",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/b.csv")]),
        _inst("open notepad then delete C:/tmp/c.log",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/c.log")]),
    ])
    slot = tpl["slots"][0]["name"]
    steps = fill_skeleton(tpl, {slot: "report.csv"})
    assert steps is not None
    assert steps[0]["target"] == "notepad"
    assert steps[1]["target"] == "C:/tmp/report.csv"
    assert steps[1]["intent"] == "FileDeletionIntent"
    assert steps[1]["depends_on"] == ["step_1"]


def test_fill_skeleton_rejects_missing_slot():
    tpl = abstract_skill([
        _inst("open notepad then delete C:/tmp/a.txt",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/a.txt")]),
        _inst("open notepad then delete C:/tmp/b.txt",
              [("ApplicationLaunchIntent", "notepad"), ("FileDeletionIntent", "C:/tmp/b.txt")]),
    ])
    assert fill_skeleton(tpl, {}) is None


def test_fill_skeleton_zero_slot_template_returns_steps():
    tpl = abstract_skill([
        _inst("open notepad and calc", [("ApplicationLaunchIntent", "notepad"),
                                        ("ApplicationLaunchIntent", "calc")]),
        _inst("open notepad and calc", [("ApplicationLaunchIntent", "notepad"),
                                        ("ApplicationLaunchIntent", "calc")]),
    ])
    steps = fill_skeleton(tpl, {})
    assert [s["target"] for s in steps] == ["notepad", "calc"]
