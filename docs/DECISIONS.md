# SentinAL — Goals, Decisions, and State of the Project

Last updated 2026-09-19. This is the continuity document: someone (or something) with no
prior context should be able to read this plus `CONTRIBUTING.md`, `ROADMAP.md` and
`CONTAINMENT_ARCHITECTURE.md` and continue the work at the same standard.

## 1. What this is

SentinAL is a voice/text-controlled desktop agent for Windows with a deterministic
security layer: every action an LLM proposes is validated before it runs, and verified
against real OS state afterwards. It is a B.Tech thesis project and a public open-source
research prototype (`pavann19/SentinAL-Desktop-AI-Orchestration`).

**Positioning.** Gatekeeper decides whether a prompt may reach a model; SentinAL decides
whether an agent's proposed OS action may execute, and verifies that it worked.

**Goals.** (1) A desktop agent whose safety does not depend on model good behaviour.
(2) Evidence-backed claims: reproducible benchmarks with provenance. (3) Autonomy that
grows only as fast as containment (sandboxing, snapshot/restore, budgets, audit) makes
each step recoverable.

**Non-goals (for now).** Cross-platform support; unattended operation without the
containment gate; any capability that lets the system change its own policy.

## 2. Architecture in one screen

`voice/text → router (classifier) → processor/planner (LLM, untrusted) → validator
(deterministic) → capability broker/budgets → executor → postcondition observer → critic
(bounded replan)`. Map: `agentic_core/` (router, planner, critic, validator, executor,
memory, world model, skills, self-improvement), `capabilities/` (system, developer, web),
`config/` (tiers, contracts, constants — single auditable policy source), `interfaces/`
(voice, UI bridge), `eval/` + `benchmarks/` (measurement), `scripts/` (verification and
offline entry points), `tests/`, `thesis/`.

## 3. Decision log

Each entry: decision — reason — where it lives.

1. **LLM is untrusted; control plane is deterministic code** — injection/compromise is
   assumed, so safety must be structural. `CONTAINMENT_ARCHITECTURE.md` §2.
2. **Verify OS state, never trust return values** — a clean return that did not happen
   was the largest source of false success. Postcondition observer; benchmark verifies
   by querying the OS, not the pipeline.
3. **Containment before autonomy (S4 gates S6+)** — planning ahead of the sandbox that
   contains its mistakes is the failure shape to avoid. `ROADMAP.md` ordering.
4. **Trained classifier replaced the zero-shot router** — logistic regression over
   all-MiniLM-L6-v2 embeddings (`classifier_v2_realdata.joblib`); low-margin ties defer to
   the LLM. Fast path resolves ~88% of requests with no LLM call.
5. **scikit-learn pinned to the artifact's version** — an unpickle across versions is
   not safe to assume.
6. **UIA-first GUI resolution; pixel matching only as fallback** — resolution/DPI
   independence.
7. **CodeAct and `npm install` run contained** (disposable Windows Sandbox / throwaway
   Docker container), with pre-action filesystem snapshot + restore for the T2 reversal
   half of the gate.
8. **New autonomy/learning features are default-off flags** — see §5.
9. **Frozen kernel files** (`validator.py`, `executor.py`, `benchmarks/tasks.py`,
   `main.py`) — changes need an explicit decision; the one deliberate `main.py` change
   was adding `GET /api/tasks[/{id}]`.
10. **Honest reporting over impressive reporting** — no score-inflating retries, Wilson
    intervals, reports pinned to a git commit, a self-authored benchmark said to be
    self-authored, external tasks added only where fairly testable.
11. **Broad `except Exception` is intentional** (fail-safe pipeline); CI ignores
    `BLE001`, `S110`, `S112`. All other lint findings are fixed, not ignored.
12. **ruff pinned to 0.16.0** in CI and dev extras — lint results were drifting with
    the installed version.
13. **Opt-in ONNX embedding backend** (`SENTINAL_EMBEDDING_BACKEND`, default `torch`) —
    ~82 MB / ~33% faster cold start, cosine similarity 0.999999+ to the torch path.
14. **`SENTINAL_OFFLINE=1`** — no cloud LLM, local Ollama if reachable else a
    deterministic mock LLM; text REPL replaces voice. Anyone can run and test with no keys.
15. **Router accuracy is reproducible without keys** — `scripts/reproduce_router_accuracy.py`
    wraps `eval/measure_intent_accuracy.py --mode router-only`.
16. **S10–S16 are scoped, not started** — each adds a new risk category and needs an
    explicit decision plus its containment prerequisite (`ROADMAP.md` "Beyond S9").

## 4. Current state (verified numbers)

| Metric | Value | Source |
|---|---|---|
| End-to-end task success (real machine, OS-verified) | 96.7% (116/120), 95% CI 91.7–98.7% | `benchmarks/` + `docs/reports/` |
| Router-only accuracy, full 3230-entry dataset | 91.11% | `scripts/reproduce_router_accuracy.py` |
| Real-world phrasing (MASSIVE) / out-of-distribution | 92.33% / 83.68% | `eval/` |
| Security fuzz suite | 66/66 blocked | `tests/test_security_fuzz.py` |
| Tests / coverage | 1,331 passing / 86.56% | Public-head CI command at `c415def` |

Weakest routed intents (router-only): `MediaControlIntent` 57.4%, `SchedulerIntent` 68.2%,
`InformationRetrievalIntent` 71.3%, `MediaStreamingIntent` 74.5% — thin training data.

Milestones: S1–S5 and S7 complete; S4 complete and live-verified; S6 code-complete (the
week-long unattended soak is wall-clock, not code); S8 and S9 gates met but **not
activated** (flags off; nothing reads the improvement store in the live path yet).

## 5. Feature flags (all default off unless noted)

`SENTINAL_OFFLINE`, `SENTINAL_EMBEDDING_BACKEND` (`torch` default), `SENTINAL_EVENT_BUS_ENABLED`,
`SENTINAL_AUTONOMOUS_GOALS_ENABLED`, `SENTINAL_SEMANTIC_MEMORY_ENABLED`,
`SENTINAL_PROCEDURAL_MEMORY_ENABLED`, `SENTINAL_ENV_MODEL_ENABLED`,
`SENTINAL_LEARNED_SKILLS_ENABLED`, `SENTINAL_SELF_IMPROVEMENT_ENABLED`,
`SENTINAL_REQUIRE_CONFIRMATION`. Tunables (`SENTINAL_PLAN_MAX_*`, `SENTINAL_SKILL_*`,
`SENTINAL_SEMANTIC_MEMORY_*`, `SENTINAL_PROCEDURAL_*`, `SENTINAL_SNAPSHOT_*`) are read in
`config/`. Security: `SENTINAL_API_TOKEN`, `SENTINAL_HOST` (keep on `127.0.0.1`).

## 6. Open items, in priority order

1. Voice: the wake-word engine needs a Picovoice key that is not configured; an
   `openWakeWord` swap is scoped, not built. Text/offline mode is unaffected.
2. Router blind spots: add real data for the four weak intents above, retrain, re-measure.
3. S6 soak: run the event bus unattended for a week; record the result.
4. S3 DPI/multi-monitor benchmark task (needs a physical setup).
5. Event bus increment 3 (`watchdog` filesystem triggers).
6. Live output tailing for background tasks (only final status is surfaced today).
7. Packaging/installer (install is manual).
8. `"format "` false-positive in the keyword filter — belongs in the capability broker.
9. Research-augmented planning (scoped, not built).
10. A third-party benchmark set larger than one task, as capabilities grow.
11. Housekeeping: replace remaining `BLE001`/`S110`/`S112` suppressions only if a
    specific failure mode is found; keep CI green at pinned ruff.

## 7. Wrap-up checklist (finishing the project)

- [ ] Full suite green on a clean venv; CI green on `main`.
- [ ] Re-run the end-to-end benchmark on the final commit (`--repeat 3`); update
      README and thesis numbers to exactly what it prints.
- [ ] Reconcile thesis text with `ROADMAP.md` (intent counts, test counts, limitations).
- [ ] README/roadmap/limitations honest and current; every link resolves.
- [ ] Tag a release; publish notes listing verified numbers and known limitations.
- [ ] Archive: signed tag, exported evidence (`benchmarks/results/`, `_evidence/`), and a
      dated backup of the repo outside the working tree.
