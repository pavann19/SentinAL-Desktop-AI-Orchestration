# Agent Work Verification Protocol

**Purpose:** Prove an agent's output actually works before a phase/task is marked complete.
**Threat being defended against:** hollow work — code that imports, looks plausible, passes self-written tests, but does nothing. (Precedent: the 2026-07-10 stub incident in this repo, where `def speak(...): pass` masked a dead voice layer.)

**Core principle:** *The agent that writes the code never certifies it.* Verification is done by a different party — a dedicated integrator role, or a second independent agent — using evidence the implementing agent could not fabricate.

---

## The 5-Gate Acceptance Ladder

A task is **DONE** only when all 5 gates pass. Each gate is harder to fake than the last.

### Gate 1 — Diff is real (anti-stub)
- `git diff` shows actual logic, not `pass` / `return None` / `raise NotImplementedError` / `TODO`.
- Line count of *executable* statements matches the task's complexity. A "planner" that is 15 lines is a stub.
- Mechanical check: `grep -rn "pass$\|NotImplementedError\|TODO\|FIXME\|raise Exception('stub')" <changed_files>` returns nothing unexpected.

### Gate 2 — Independent tests pass
- Tests are written by a **different agent than the implementer** (or by the integrator role), against the *spec*, before or without seeing the implementation.
- Run: `venv\Scripts\python.exe -m pytest tests/<module> -v`
- The implementer's own tests count for coverage but NOT for acceptance.

### Gate 3 — Coverage delta (anti-dead-code)
- New code must be *executed* by tests: `pytest --cov=<module> --cov-report=term-missing`.
- New lines with 0% coverage = unverified = not done. Threshold: new code ≥ 70% line coverage (repo standard).

### Gate 4 — Runtime observation (anti-"works-on-paper")
- The feature is driven end-to-end against the running system and produces an **observable artifact**, not a log line that says "success":
  - Planner task → a saved plan JSON + a trace showing steps executed.
  - Observe-act loop → a screenshot/UIA snapshot pair (before/after) proving state changed.
  - Memory tier → query returns a fact that was written in a *previous* session (persistence proof).
  - Tracing → an actual OpenTelemetry span tree exported to file.
- Evidence file is saved under `_evidence/<task-id>/` and referenced in the task board.

### Gate 5 — Adversarial / regression
- Full suite still green: `pytest tests/ -q` (must stay ≥ 247 passed).
- For security-touching modules: the injection/fuzz suite (`test_security_fuzz.py`) must pass AND one new adversarial case for the new surface.
- Negative test: feed the feature bad input, confirm it fails safely (not silently).

---

## Who runs the gates

| Gate | Run by | Cost |
|---|---|---|
| 1 Diff-real | Integrator role — reads diff | cheap |
| 2 Independent tests | test-author agent writes; integrator runs | cheap to run |
| 3 Coverage | scripted (`pytest --cov`) | free |
| 4 Runtime artifact | Integrator drives + saves evidence | medium |
| 5 Regression | scripted (full pytest) | free |

**Rule:** Gates 3 and 5 are scripted so they cost almost no agent tokens. Gates 1 and 4 are where the integrator role spends effort — keep them focused per-task.

---

## Definition of "Phase Complete"

A phase is complete when **every task in it has all 5 gates green AND**:
- The system still boots (`python main.py` → `/api/health` 200).
- An end-to-end demo scenario for that phase runs and its evidence is saved.
- Internal task-tracking log updated, git committed, tagged (`git tag phase-1-complete`).

No self-report. No "should work." Evidence file or it didn't happen.
