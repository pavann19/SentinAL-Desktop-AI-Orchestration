# agentic_core/skill_abstraction.py
# S8-1 — typed-slot abstraction.
#
# Procedural memory (S6) stores the VERBATIM structure of a repeatedly-
# successful multi-step plan, and replays it only for a near-identical goal.
# A learned SKILL generalises: given several successful concrete instances of
# the same plan structure that differ only in literal values (a filename, an
# app, a URL), abstract the varying spans into typed slots so the recipe can
# be reused for a goal with different literals.
#
# Pure functions, stdlib only. This module produces a template; registering,
# validating and using it are S8-2 .. S8-5.

from __future__ import annotations

import hashlib
import json
import re

# terminal-node intent -> the kind of postcondition that proves the skill worked
_POSTCONDITION_KIND = {
    "FileDeletionIntent": "file_absent",
    "ProjectScaffoldIntent": "path_glob_recent",
    "ApplicationLaunchIntent": "process_running",
    "WebNavigationIntent": "browser_on_site",
    "MediaStreamingIntent": "browser_on_site",
    "SchedulerIntent": "sqlite_scheduler_row",
    "DataModelingIntent": "path_glob_recent",
    "AcademicResearchIntent": "path_glob_recent",
    "ProcessManagementIntent": "process_not_running",
}

_PATH_RE = re.compile(r"""^([A-Za-z]:[\\/]|[\\/]|~[\\/]|%[A-Za-z_]+%[\\/])|[\\/].+\.\w{1,6}$""")
_URL_RE = re.compile(r"^(https?://|[\w-]+(\.[\w-]+){1,}(/|$))", re.IGNORECASE)
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_SINGLE_TOKEN_RE = re.compile(r"^[\w.-]{1,24}$")


def _canon(graph_dict: dict) -> dict:
    from agentic_core.procedural_memory import _canonical
    return _canonical(graph_dict)


def _ordered_node_ids(canon: dict) -> list[str]:
    return sorted(canon.get("nodes", {}).keys())


def _structural_fp(canon: dict) -> str:
    """A fingerprint of the plan SHAPE only — intent + dependency edges per
    node, NOT the target literals. This is deliberately looser than
    procedural_memory._fingerprint (which includes targets): a skill is the
    generalisation across instances that differ only in literals."""
    shape = [
        {"intent": nd.get("intent"), "depends_on": sorted(nd.get("depends_on", []))}
        for _, nd in sorted(canon.get("nodes", {}).items())
    ]
    blob = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _infer_type(values: list[str]) -> str:
    vals = [v for v in values if v]
    if not vals:
        return "text"
    if all(_NUM_RE.match(v) for v in vals):
        return "number"
    if all(_PATH_RE.search(v) for v in vals):
        return "path"
    if all(_URL_RE.match(v) for v in vals):
        return "url"
    if all(_SINGLE_TOKEN_RE.match(v) for v in vals):
        return "app"
    if any(len(v.split()) >= 3 for v in vals):
        return "query"
    return "text"


def _common_frame(values: list[str]) -> tuple[str, str]:
    """Longest common prefix and suffix shared by every value (case-sensitive)."""
    if not values:
        return "", ""
    pre = values[0]
    for v in values[1:]:
        i = 0
        while i < min(len(pre), len(v)) and pre[i] == v[i]:
            i += 1
        pre = pre[:i]
        if not pre:
            break
    suf = values[0]
    for v in values[1:]:
        i = 0
        while i < min(len(suf), len(v)) and suf[-1 - i] == v[-1 - i]:
            i += 1
        suf = suf[len(suf) - i:] if i else ""
        if not suf:
            break
    # don't let prefix and suffix overlap on the shortest value
    shortest = min(len(v) for v in values)
    if len(pre) + len(suf) > shortest:
        suf = suf[len(pre) + len(suf) - shortest:]
    return pre, suf


def abstract_skill(instances: list[dict]) -> dict | None:
    """`instances` is a list of {"prompt": str, "graph": <GoalGraph.to_dict()>}
    that all completed successfully. Returns a skill template, or None if there
    are fewer than two instances or they do not share one plan structure.

    Never raises."""
    try:
        if not instances or len(instances) < 2:
            return None
        canons = [_canon(i["graph"]) for i in instances]
        fps = {_structural_fp(c) for c in canons}
        if len(fps) != 1:
            return None  # not the same plan structure — nothing to generalise
        fingerprint = fps.pop()

        node_ids = _ordered_node_ids(canons[0])
        skeleton: list[dict] = []
        slots: list[dict] = []
        slot_names: set[str] = set()

        for nid in node_ids:
            nodes_per_instance = [c["nodes"][nid] for c in canons]
            intent = nodes_per_instance[0].get("intent")
            depends_on = list(nodes_per_instance[0].get("depends_on", []))
            targets = [str(n.get("target", "")) for n in nodes_per_instance]

            if len(set(targets)) == 1:
                target_template = targets[0]
            else:
                pre, suf = _common_frame(targets)
                middles = [
                    t[len(pre): len(t) - len(suf)] if (len(pre) + len(suf)) <= len(t) else t
                    for t in targets
                ]
                # type is inferred from the FULL reconstructed values (the
                # frame carries the signal — "C:/tmp/" says path even when the
                # varying middle is just "a.txt")
                stype = _infer_type([pre + m + suf for m in middles])
                base = f"{(intent or 'x').replace('Intent', '').lower()}_{stype}"
                name = base
                k = 2
                while name in slot_names:
                    name = f"{base}{k}"
                    k += 1
                slot_names.add(name)

                # is the slot value lifted straight from the prompt each time?
                from_prompt = all(
                    m and m in inst["prompt"] for m, inst in zip(middles, instances)
                )
                slots.append({
                    "name": name,
                    "type": stype,
                    "node_step_id": nid,
                    "examples": middles[:5],
                    "from_prompt": from_prompt,
                })
                target_template = f"{pre}{{{name}}}{suf}"

            skeleton.append({
                "step_id": nid,
                "intent": intent,
                "depends_on": depends_on,
                "target_template": target_template,
            })

        terminal_intent = skeleton[-1]["intent"] if skeleton else None
        return {
            "fingerprint": fingerprint,
            "goal_examples": [i["prompt"] for i in instances][:5],
            "skeleton": skeleton,
            "slots": slots,
            "postcondition_kind": _POSTCONDITION_KIND.get(terminal_intent or ""),
            "origin": "learned",
            "n_instances": len(instances),
        }
    except Exception:
        return None


def fill_skeleton(template: dict, slot_values: dict) -> list[dict] | None:
    """Materialise a template's skeleton into concrete pipeline steps by
    substituting {slot} placeholders. Returns None if a required slot is
    missing. Never raises."""
    try:
        needed = {s["name"] for s in template.get("slots", [])}
        if not needed.issubset(slot_values.keys()):
            return None
        steps: list[dict] = []
        for node in template.get("skeleton", []):
            target = node.get("target_template", "")
            for name, val in slot_values.items():
                target = target.replace(f"{{{name}}}", str(val))
            steps.append({
                "step_id": node["step_id"],
                "intent": node["intent"],
                "target": target,
                "prompt": target,
                "depends_on": list(node.get("depends_on", [])),
            })
        return steps
    except Exception:
        return None
