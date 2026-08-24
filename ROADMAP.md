# SentinAL Roadmap

Source: this project's own sequenced plan in `CONTAINMENT_ARCHITECTURE.md` §7
(S1–S7, "ordered by dependency, not ambition") and `PHASE_TASK_BOARD.md`'s
Phase 2 task list, reconciled against what has actually shipped. Kept in this
shape rather than rewritten because the sequencing argument in
`CONTAINMENT_ARCHITECTURE.md` §7 is still correct: containment (S4) is "the
gate on all autonomy" and belongs ahead of the cognitive-layer work
(`PHASE_TASK_BOARD.md`'s P2-1/P2-2/P2-3), not after it — building planning
capability before the sandbox that contains its mistakes is the exact
failure shape that document exists to avoid. Every item below cites the
commit/file that closed it; nothing here is estimated or assumed done.

Overlap note: validation/sandboxing (path denylist), the postcondition
observer's process/filesystem/window/vlm tiers, the security fuzz suite, and
the classifier/router already existed before this roadmap and are not
re-counted here.

---

## S1 — Complete the observe loop (done)
Gate: silent-failure rate measurable per intent, not just per pipeline.

- [x] Filesystem tiers (`path_exists`/`path_absent`/`glob_recent`) added to
      `observe_postcondition()` — pre-dates this roadmap.
- [x] `expected_state` derived for `DataModelingIntent` and
      `AcademicResearchIntent` (EDA heatmap PNG, research summary `.txt`,
      both real timestamped artifacts to `DATA_DIR`) — 2026-08-23,
      `9630f33`.
- [x] New query-based "memory" tier for `SchedulerIntent`
      (`task_description_recent` / `task_cancelled`, reading SQLite
      directly since it has no filesystem artifact) — 2026-08-24,
      `db48703`.
- [x] Result: **13 of 19 intents** have live effect verification (11
      synchronous + 2 async-supervised), up from 10. The remaining 6
      (`InformationRetrievalIntent`, `ConversationalIntent`,
      `ContinuationIntent`, `SysUtilityIntent`, `MediaControlIntent`,
      `DictationIntent`) are read-only/conversational or leave no durable
      OS-state fact — closing them needs a different mechanism (e.g.
      VLM/screen-state confirmation), not another observer tier. See
      README's Known Limitations for the exact list.

## S2 — Task benchmark (done)
Gate: success rate is a tracked number, not an estimate.

- [x] `benchmarks/tasks.py` + `benchmarks/run_benchmark.py` — independent
      OS-state verification (not the pipeline's own self-report), 95%
      Wilson confidence interval, no score-inflating retries.
- [x] Task suite corrected after the stub-intent fixes — 4 tasks that
      tested honest refusal became wrong once those intents were
      genuinely implemented; replaced with `scheduler`/`research_analysis`
      categories that verify real OS-state artifacts — 2026-08-16,
      `0fd7cf4`.
- [x] Current result: **96.7%** (95% CI 91.7–98.7%, 116/120) — re-run and
      published 2026-08-17, `44045ed`.

## S3 — Fix what the benchmark exposed: GUI grounding (done)
Gate: success rate materially above the pre-fix baseline; specifically, the
pixel-coordinate fragility the benchmark's own methodology couldn't measure
directly (it can't simulate a DPI/resolution change) but the architecture
docs flagged as the most likely tail-risk.

- [x] `resolve_element()` reordered UIA-first (via `pywinauto`, searching
      the foreground window when no window title is known) instead of
      image-match-first — pixel matching is now the fallback for
      image-only requests, not the default path for anything the
      accessibility tree can resolve by name — 2026-08-23, `f550324`.
- [x] Along the way: found `pywinauto` and `pygetwindow` were undeclared
      in `requirements.txt` despite being load-bearing — a clean install
      would have silently disabled both the UIA tier and the
      postcondition observer's `window_exists()` checks. Fixed in the
      same commit.
- [x] Live-verified against a real running window (not mocked) — 2026-08-24.
      `find_control_by_label("", "Close")` resolved a real Notepad "Close"
      button's coordinates, matching an independent manual `pywinauto`
      probe exactly, and the exact-match lookup correctly distinguished
      it from a same-window "Close Tab" button with different text — the
      collision a naive fuzzy match would have hit. Documented in
      `gui_resolver.py` next to `resolve_element()`.
- [x] Found along the way, not currently reachable in production: apps
      that host multiple top-level windows under one process (Windows
      11's modern Notepad — confirmed live, 10 accumulated windows shared
      one PID) break `process_absent` as a postcondition for "did closing
      THIS window close the app." Not a live bug — `GeneralizedOSIntent`'s
      "gui"/"click" action derives no postcondition today — but recorded
      as a note for whoever wires one later: `window_exists` (this window
      gone) is the correct check for a click-to-close action, not
      `process_absent` (this app entirely gone).
- [ ] Still not done: no benchmark task currently exercises a non-default
      DPI/resolution/multi-monitor configuration, so S3's lift on the
      tracked success-rate number is unmeasured — the fix is now both
      code-inspection-confirmed AND live-verified against a real window,
      but S2's benchmark still can't prove the delta the way it proved
      the intent-verification lift in S1. Left open — simulating a real
      DPI/resolution change safely on a live dev machine is its own,
      separate scope, not a quick addition.

---

## S4 — Containment substrate (not started — the gate on all autonomy)
Gate (per `CONTAINMENT_ARCHITECTURE.md` §6/§7): a T1→T2 tier reversal
demonstrated under test — i.e. proof that a compromised or hallucinating
plan is physically contained, not just discouraged by a path denylist.

- [ ] Overlay writes / snapshots so a sandboxed action's filesystem effect
      is provisional until approved, not immediate.
- [ ] Budgets (time/action-count ceilings per plan).
- [ ] Capability broker replacing the current allowlist-plus-sandbox-check
      model with an explicit grant per action.
- [ ] Sandboxed execution tier (Docker or Windows Sandbox) for
      `CodeActIntent` + `DependencyInstallIntent` specifically —
      `SENTINAL_V2_RECONCILED_ARCHITECTURE.md` §2/§8 calls this the
      "Sandboxed Tier," explicitly split from the already-substantially-
      built "Host-Supervised Tier" (allowlist, sandbox path checks,
      postcondition observer, process supervisor — all of which already
      exist and are not part of this item).

**Do not start S5 or S6 before this is real.** That's not a stylistic
preference — it's `CONTAINMENT_ARCHITECTURE.md` §7's explicit corrected
ordering, written specifically because the original phase plan
(`AGENTIC_OS_ROADMAP_AND_THESIS_PLAN.md`) put the cognitive layer (planner)
ahead of containment, which builds capability ahead of the thing that makes
its mistakes cheap.

## S5 — Planner + critic split (not started)
Gate: multi-step tasks succeed where single-shot fails.
Maps to `PHASE_TASK_BOARD.md`'s **P2-1** (LangGraph planner graph:
plan→act→observe→reflect, wrapping the existing pipeline). Corrected
residency per `SENTINAL_V2_RECONCILED_ARCHITECTURE.md` §3: critic resident,
planner invoked only when the router's own multi-step determination fires —
not on every request.

- [ ] Goal graph replacing the current flat step list.
- [ ] Planner gated behind router's multi-step signal (§3).
- [ ] Critic resident, integrated with the existing postcondition observer
      rather than duplicating it.

## S6 — Proactive autonomy (not started)
Gate: runs unattended for a week with no unwanted action.
Maps to `PHASE_TASK_BOARD.md`'s **P2-2** (semantic memory / local vector
store) and **P2-3** (procedural memory / cached task recipes), reframed
per `SENTINAL_V2_RECONCILED_ARCHITECTURE.md` §5/§7: event bus is
`watchdog` + `APScheduler`, not MCP; local knowledge-graph memory
(bi-temporal `graph_nodes`/`graph_edges`) folds into the existing SQLite
database via `memory_hook.py`, not a new server.

- [ ] Event bus for background goals under budget + tier policy (needs S4's
      budgets to exist first).
- [ ] Semantic memory tier + retrieval.
- [ ] Procedural memory: learned task recipes cached and reused.
- [ ] `PHASE_TASK_BOARD.md`'s **P2-4** (MCP tool contracts) — explicitly
      scoped to capability schemas only, not the event bus.
- [ ] `PHASE_TASK_BOARD.md`'s **P2-5** (risk-tiered policy engine:
      auto/notify/confirm/forbid in the validator) — natural companion to
      S4's capability broker; likely belongs partly in S4, partly here.

## S7 — World context and drift detection (deferred, further out)
Per `CONTAINMENT_ARCHITECTURE.md` §10.3/§10.4: a live environment model
built on S1's snapshot mechanism, so the planner can query current state
and per-capability success-rate trend is tracked over time. Explicitly
gated on S1 (verification) and S2 (benchmark baseline) existing first —
both are now done, but this item itself has had no design work yet beyond
the one paragraph in §10.4.

---

## Cross-cutting / not gated on the S-sequence

These don't block or get blocked by S4–S7 — they're independent, and worth
picking up opportunistically:

- [ ] **Installer/packaging** — no Docker image or installable package yet;
      installation is fully manual (`README.md` Known Limitations).
- [ ] **External benchmark** — `benchmarks/tasks.py` is still self-authored,
      not drawn from an independently-curated task set; all measurements
      come from a single Windows machine.
- [x] **Repo hygiene** — `.gitignore` now covers the whole `data/` runtime
      directory instead of three incomplete per-file entries; stray
      AI-authored planning files (`Gemini_plans/`,
      `_antigravity_prompt_postcondition_expansion.md`) and a scratch
      script moved out of the repo; `main`'s README synced to
      `public-release` (three sections had gone stale across prior
      cherry-picks) — 2026-08-24.
- [ ] **"format " false-positive** in the keyword filter — deferred to a
      future risk-tiered check (would live inside S4/S6's capability
      broker work above, not fixed standalone).

---

## Explicitly deferred

Not started, not scheduled — revisit only once S4 is real and benchmarked:
full MCP tool-contract migration beyond capability schemas, cross-platform
support (currently Windows-only by design, per README), a resident
event-bus-driven "runs unattended" mode (S6's actual gate), and anything in
`AGENTIC_OS_ROADMAP_AND_THESIS_PLAN.md`'s original Phase 3/4 that
`SENTINAL_V2_RECONCILED_ARCHITECTURE.md` reordered behind S4.
