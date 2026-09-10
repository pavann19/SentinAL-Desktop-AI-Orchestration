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

## S4 — Containment substrate (buildable items complete — gate met)
Gate (per `CONTAINMENT_ARCHITECTURE.md` §6/§7): a T1→T2 tier reversal
demonstrated under test — i.e. proof that a compromised or hallucinating
plan is physically contained, not just discouraged by a path denylist.
**Met** — the capability broker supplies the tier (`ecda782`) and the
pre-action snapshot makes a T2/T3 filesystem effect undoable (`16c7f8e`);
`test_planner_critic_integration.py` demonstrates a failed multi-step plan
rolling back an earlier step's real file deletion. The two remaining open
items are a live verification (npm Docker round-trip) and a benchmark gap
(DPI/resolution), not unbuilt containment.

- [x] **Environment reality-check before committing to a plan** — 2026-08-29,
      **corrected 2026-09-10**. Docker Desktop here is WSL2-backed and only
      runs Linux containers, so `CodeActIntent`'s Windows-targeted PowerShell
      (`winget`, Windows paths per its own system prompt) can't run in it —
      that part still holds, and re-scoping to `npm_install()` first (cross-
      platform, a Linux container genuinely works) was still the right call.
      **What was wrong:** the original note said this machine is Windows 11
      Home with "no Hyper-V, so Windows Sandbox and Windows containers are
      unavailable." It is actually **Windows 11 Pro for Workstations** — a
      hypervisor is already running (VBS/HVCI + WSL2's Virtual Machine
      Platform), and Windows Sandbox / Windows containers / the full Hyper-V
      role are all edition-eligible. They are just not *enabled* yet
      (`vmms`, `WindowsSandbox.exe`, Hyper-V PS module all absent; the
      low-level `vmcompute`/`hns`/`HvHost` plumbing is present and running).
      So `CodeActIntent` containment (below) is **not blocked by hardware** —
      it needs Windows Sandbox turned on (elevation + reboot), then it is
      buildable here.
- [x] **`npm_install()` sandboxed in a throwaway Docker container** —
      2026-08-29, `cad4a85`/`af66436`. Runs inside `node:20-slim`, mounting
      the same target directory it already writes `node_modules` into.
      Contains the real threat this always had: an npm postinstall script
      running arbitrary code directly on the host with full user
      privileges (a known supply-chain attack vector), not a hypothetical
      one. `_docker_available()` checked fresh per call (not cached —
      Docker Desktop gets started/stopped between requests on this
      machine); falls back to a direct host install, in the same visible
      window, when Docker isn't running OR when the sandboxed install
      produces a native module (`*.node` file — a Linux binary, unusable
      by the host's Windows Node), detected by the generated script
      itself post-install rather than guessed at up front.
- [x] **`pip_install()` deliberately left unsandboxed** — it has no
      existing target-directory concept to redirect into a mount (always
      targets whichever interpreter environment is active); containing it
      needs a real `--target`/venv design decision, not a behavior change
      bolted on here.
- [ ] **Live end-to-end round-trip NOT verified** — real container
      execution was confirmed on this machine (a plain `python:3.12-slim`
      container ran and returned expected output), and all script-
      generation/fallback/availability-check logic is unit-tested (11 new
      tests). But a full live `npm install <pkg>` through the actual
      container was not completed: two live Docker Desktop starts on this
      machine dropped available RAM from single-digit GB to under 1 GB
      (0.66 GB / 94.6% used at the worst point, Docker self-terminated
      once already under similar pressure earlier in this same session).
      Stated as open rather than assumed — needs either more free RAM at
      test time or a deliberately time-boxed retry.
- [x] **Pre-action filesystem snapshot + restore** — 2026-09-10, `16c7f8e`.
      Windows has no native copy-on-write overlay FS, so §6's T2 model ("real
      writes + pre-action snapshot -> restore snapshot") is implemented as
      capture-and-restore. `config/snapshots.py` (store dir under DATA_DIR,
      retention, per-file copy size cap) + `agentic_core/snapshot.py`
      (`PathSnapshot`/`Snapshot`, non-raising: file existed -> copied aside;
      file absent -> delete if step created it; dir existed -> top-level entry
      manifest, restore removes only *additions*; dir absent -> rmtree if
      created). `api_wrapper._paths_for_step()` derives the write target for
      `FileDeletionIntent`, `ProjectScaffoldIntent`, mkdir-form
      `GeneralizedOSIntent`, and the `DATA_DIR` writers — `[]` for arbitrary
      shell / GUI / CodeAct (same unpredictability `_derive_expected_state`
      declines to guess). Wired into `execute_goal_graph_observed()`: capture
      before each step, then on plan SUCCESS discard, on ANY failure (step
      failed, budget spent, cancelled, validation denied mid-plan) restore
      newest-first. Result carries `snapshots: {taken, restored, restore_errors}`;
      `process_command()` surfaces it. This is the T2-reversal half of the S4
      gate — the broker gave the tier, this makes the effect undoable.
      `validator.py`/`executor.py` untouched. 12 snapshot tests + 8
      `_paths_for_step` + 2 end-to-end (failed plan rolls back an earlier
      step's real file deletion; successful plan discards).
- [x] **Budgets — per-plan action + wall-time ceilings** — 2026-09-10, `4c8b654`.
      `config/budgets.py` (env-overridable, autonomous ceilings strictly
      tighter: 12 actions / 120s vs 24 / 300s) + `agentic_core/budget.py`
      (`PlanBudget`, non-raising, monotonic clock; `budget_for(autonomous)`
      factory; `FAILURE_CATEGORY_BUDGET_EXCEEDED`). Wired into
      `execute_goal_graph_observed()`: checked at the top of the node loop and
      before each replan; when spent, remaining nodes are marked `skipped`
      (not run) and the result is `failure_category="budget_exceeded"`.
      `process_command()` surfaces `output["budget"]`. Single-step flat path
      untouched. 16 budget tests + 4 wiring tests; 114 pass across the
      affected suites, no regressions. `validator.py`/`executor.py` untouched.
- [x] **Capability broker — risk-tier decision layer** — 2026-09-10, `ecda782`.
      `config/capability_tiers.py` maps all 19 allowlisted intents to T0..T3
      (with `list`-vs-mutate sub-action overrides); `agentic_core/capability_broker.py`
      returns `GrantDecision(allowed, tier, requires_confirmation, reason)` for
      a step or a whole plan. Two caller contexts: `autonomous=False` (every
      caller today — T2/T3 flag confirmation, nothing newly blocked, no
      confirmation-provision channel exists yet); `autonomous=True` (S6, not
      built — T2/T3 denied outright). Wired into `process_command()` STAGE 1a
      as additive response fields (`capability_tier`, `requires_confirmation`,
      `capability_reason`), non-blocking, covering both the S5 and flat paths.
      `validator.py`/`executor.py` untouched. 46 broker tests + 3 wiring
      tests; 192 pass across the affected suites, no regressions.
      Still open here: nothing *enforces* `requires_confirmation` at the
      backend yet (`_requires_confirm` from `validate_steps()` is likewise
      captured-unused today) — that needs a two-phase confirm channel, a
      separate wiring task. The broker now produces the correct signal for
      whoever consumes it.
- [x] **`CodeActIntent` containment — disposable Windows Sandbox** —
      2026-09-10, `a284d1d`. Windows Sandbox enabled + reboot done same day.
      Each LLM-generated PowerShell script now runs inside a fresh Sandbox
      VM: only a single per-run dir is mapped in at `C:\shared` (the sole
      host path it can reach), and the VM plus everything it did is discarded
      when the window closes — the T3 throwaway-environment model §6 wants.
      `_sandbox_available()` (exe present + ≥3 GB free RAM, fresh per call);
      when unavailable, falls through to the pre-containment visible host
      PowerShell window and the response says plainly it is running
      uncontained. Completion sentinel written to `C:\shared` so the process
      supervisor observes it as before. Known limit: a fresh Sandbox has no
      `winget`, so winget-based install steps fail inside it (the response
      says so). `validator.py`/`executor.py` untouched. 26 tests (10 new).
      NOT verified: a live Sandbox boot + run — needs ~5 GB free (a VM boot
      is ~1.5-2 GB and this machine has crashed under memory pressure);
      3.75 GB free at build time. Stated open, same as the npm Docker
      round-trip.

**S4 gate met → S6 is now unblocked.** The ordering rule
(`CONTAINMENT_ARCHITECTURE.md` §7 — containment before the cognitive layer,
so capability never outruns the thing that makes its mistakes cheap) is
satisfied: the broker + snapshot give a demonstrated T2 reversal, and the
per-plan budget bounds runaway. S5 (below) was in fact built and verified
before this note was corrected — acceptable only because it does not
weaken the security boundary (it plans; `validate_steps()` still gates
every step). S6's autonomy loop is the real thing this gate protected, and
it can now proceed.

## S5 — Planner + critic split (done)
Gate: multi-step tasks succeed where single-shot fails.
Maps to `PHASE_TASK_BOARD.md`'s **P2-1** (LangGraph planner graph:
plan→act→observe→reflect, wrapping the existing pipeline). Corrected
residency per `SENTINAL_V2_RECONCILED_ARCHITECTURE.md` §3: critic resident,
planner invoked only when the router's own multi-step determination fires —
not on every request.

- [x] Goal graph replacing the current flat step list — 2026-08-30, `0f62b5f`
      (`agentic_core/goal_graph.py`: pure-Python DAG, Kahn topo sort, cycle
      detection, `{{LAST_RESULT}}`/`{{step_id.result}}` data-chaining, no heavy
      dependency).
- [x] Planner gated behind router's multi-step signal — `is_multistep_query()`
      in `agentic_core/planner.py`; single-step requests pay zero extra
      latency and no planner LLM call. `MAX_PLAN_STEPS` bound.
- [x] Critic resident, integrated with the existing postcondition observer —
      `agentic_core/critic.py` reuses `observe_postcondition` verdicts, bounds
      replans to `MAX_REPLANS`, no parallel verification mechanism.
- [x] **Wiring gap found in verification and fixed** — 2026-09-10, `42af9ff`.
      Antigravity's original commit built `execute_goal_graph_observed()` but
      never called it from `process_command()` — the planner ran, its DAG was
      flattened via `to_pipeline()` and handed to the old executor, so
      `{{LAST_RESULT}}` reached execution unresolved and the Critic's per-step
      replan never ran live. `process_command()` now routes multi-step results
      through the engine. 3 new tests exercise the real seam.

## S6 — Proactive autonomy (unblocked — S4 gate met; not yet started)
Gate: runs unattended for a week with no unwanted action.
Maps to `PHASE_TASK_BOARD.md`'s **P2-2** (semantic memory / local vector
store) and **P2-3** (procedural memory / cached task recipes), reframed
per `SENTINAL_V2_RECONCILED_ARCHITECTURE.md` §5/§7: event bus is
`watchdog` + `APScheduler` (or lighter), not MCP; local knowledge-graph
memory (bi-temporal `graph_nodes`/`graph_edges`) folds into the existing
SQLite database via `memory_hook.py`, not a new server.

**What S4 already provides for this:** the capability broker's
`autonomous=True` path (T2/T3 denied outright — `ecda782`), the tighter
autonomous `PlanBudget` (12 actions / 120s vs 24 / 300s — `4c8b654`), and
the pre-action snapshot that rolls back a failed plan (`16c7f8e`). All
built and unit-tested; they are waiting for a caller that passes
`autonomous=True`. The event bus is that caller.

- [ ] **Event bus — increment 1: time triggers, notify-only.** A resident
      poll loop (like `process_supervisor`, started from `main.py`'s
      lifecycle) that fires the `scheduled_tasks.due_at` rows SchedulerIntent
      already persists but currently never acts on (its handler openly says
      "I don't yet send active notifications"). On a due row it **notifies**
      via the existing telemetry websocket — it does NOT execute anything.
      No new heavy dependency (an `asyncio` sleep-poll, not `APScheduler`).
      This is the safe first slice: it structurally cannot take an unwanted
      action because it only sends messages.
- [ ] **Event bus — increment 2: autonomous action execution.** A trigger
      forms a background goal and runs it through the pipeline with
      `autonomous=True`, so the broker denies T2/T3 and the tighter budget
      applies. This is where the "week unattended, no unwanted action" gate
      actually bites — needs a soak test, not just unit tests. Separately
      gated from increment 1.
- [ ] **Event bus — increment 3: `watchdog` filesystem triggers** (a file
      appears in a watched folder). After increments 1–2 are solid.
- [ ] Semantic memory tier + retrieval.
- [ ] Procedural memory: learned task recipes cached and reused.
- [ ] `PHASE_TASK_BOARD.md`'s **P2-4** (MCP tool contracts) — explicitly
      scoped to capability schemas only, not the event bus.
- [ ] `PHASE_TASK_BOARD.md`'s **P2-5** (risk-tiered policy engine:
      auto/notify/confirm/forbid) — the S4 capability broker is the tier
      half of this; the enforcement half (nothing at the backend acts on
      `requires_confirmation` yet — a two-phase confirm channel) belongs
      here, alongside the event bus.

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
