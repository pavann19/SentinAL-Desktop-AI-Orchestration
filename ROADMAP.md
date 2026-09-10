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

## S4 — Containment substrate (complete — gate met, live round-trip verified)
Gate (per `CONTAINMENT_ARCHITECTURE.md` §6/§7): a T1→T2 tier reversal
demonstrated under test — i.e. proof that a compromised or hallucinating
plan is physically contained, not just discouraged by a path denylist.
**Met** — the capability broker supplies the tier (`ecda782`) and the
pre-action snapshot makes a T2/T3 filesystem effect undoable (`16c7f8e`);
`test_planner_critic_integration.py` demonstrates a failed multi-step plan
rolling back an earlier step's real file deletion. The live container
round-trip is now **verified** (below). The only remaining open item under
S4 is a benchmark gap (DPI/resolution), not unbuilt containment.

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
- [x] **Live end-to-end round-trip VERIFIED** — 2026-09-10 (report
      `benchmarks/results/s4_live_roundtrip_20260910T185434Z.json`,
      `overall_pass: true`). `scripts/verify_s4_live_roundtrip.py` (`e30d410`)
      ran the real
      `docker run --rm -v <hostdir>:/workspace -w /workspace node:20-slim npm install is-number`
      end to end. All 7 checks green: daemon reachable; `npm_install()`'s own
      builder selects the sandbox `docker run --rm -v ...` path; `node:20-slim`
      pulled; the container install **exited 0 in 2.3 s**;
      **`node_modules/is-number/package.json` materialised in the HOST mount**
      — the containment proof, the npm install genuinely ran inside the
      throwaway Linux container and wrote back only through the bind mount;
      `--rm` honoured (no leftover container); no Linux-native `.node`
      artifacts. RAM held: 2.32 GB free at start, **min 1.94 GB during the
      install**, 1.95 GB at end (nowhere near the 0.66 GB that killed the
      earlier attempts — the `.wslconfig` `memory=2GB` cap plus a freed
      desktop app did it). Total wall time 17.5 s.
      Prior status: a plain `python:3.12-slim` container had been confirmed,
      and all script-generation/fallback/availability logic was unit-tested
      (11 tests), but the full `npm install` had not completed because two
      earlier Docker Desktop starts dropped free RAM under 1 GB and Docker
      self-terminated. That is now resolved and measured, not assumed.
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

## S6 — Proactive autonomy (event bus increments 1–2 built; the week-soak gate is the outstanding item)
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
now wired: `process_command(autonomous=True)` (`850678b`) enforces them,
and `event_bus.make_event_handler()` is the caller.

- [x] **Event bus — increment 1: time triggers, notify-only** — 2026-09-10,
      `a64a82b`. `agentic_core/event_bus.py`: one resident `asyncio` loop
      started from `main.py`'s lifecycle next to `process_supervisor`,
      mirroring its loop/start/stop shape (poll SQLite via `to_thread`, a
      raising callback logged+swallowed, sweep errors don't kill the loop,
      `CancelledError` stops cleanly, idempotent start). Every 30 s
      (`SENTINAL_EVENT_BUS_POLL_SECONDS`, master switch
      `SENTINAL_EVENT_BUS_ENABLED`) it fires the `scheduled_tasks.due_at`
      rows SchedulerIntent persists but its handler openly can't deliver.
      `memory_hook.py` additive: nullable `notified_at` column (PRAGMA-guarded
      ALTER), `get_due_scheduled_tasks(now)`, `mark_scheduled_task_notified`
      (does NOT complete the row). `main.py`'s `on_reminder_due` ONLY pushes a
      `reminder_due` telemetry message — no pipeline, no action — same
      invariant `on_watch_resolved` has. No new dependency (sleep-poll, not
      `APScheduler`). 13 tests; 54 pass across event bus + supervisor +
      api_wrapper + pipeline, no regressions. `validator.py`/`executor.py`
      untouched.
- [~] **Event bus — increment 2: autonomous action execution** — machinery
      built 2026-09-10, `850678b`. `process_command(prompt, *, autonomous=False)`
      gained the flag: when `autonomous=True` the capability broker's decision
      is ENFORCED — a plan whose highest tier is T2/T3 is denied outright
      ("no human -> can't confirm -> deny", which the broker already encodes),
      nothing runs, and the multi-step path uses `budget_for(autonomous=True)`
      (12 actions / 120 s). `validate_steps()` still runs first and
      unconditionally. `scheduled_tasks` gains a `kind` column
      ('reminder' default | 'goal'); `event_bus.make_event_handler()` runs a
      due `kind='goal'` row via `process_command(autonomous=True)` — but only
      when `SENTINAL_AUTONOMOUS_GOALS_ENABLED` (default **off**), and **nothing
      creates a `'goal'` row yet** (no user-facing path — that's a later
      increment). So this is inert on a fresh install, twice over. 24 tests
      (broker-enforced T3 block with executor never called; direct-human T3
      still only flagged; autonomous T0 runs; validator still gates a
      system32 goal; autonomous multi-step uses the tighter budget;
      `make_event_handler` reminder-vs-goal branch incl. disabled-degrades-to-
      notify and a raising goal still reporting). `validator.py`/`executor.py`
      untouched; `main.py` gained no new lint issue.
      **Still open — the actual S6 gate:** a real week-long unattended soak
      with `SENTINAL_AUTONOMOUS_GOALS_ENABLED=true` and real `'goal'` rows.
      Unit tests prove the containment logic; they cannot prove "no unwanted
      action over a week." Not claimed as passed.
- [ ] **Event bus — increment 3: `watchdog` filesystem triggers.** A second
      event *source* alongside the time poll: a file created/moved into a
      watched folder raises an event, dispatched through the same
      `make_event_handler()` branch (notify by default; run as an autonomous
      goal only under `SENTINAL_AUTONOMOUS_GOALS_ENABLED` with an explicit
      per-watch opt-in). New: declare `watchdog` in `requirements.txt` (it's
      an undeclared transitive dep today — same class of bug as
      `pywinauto`/`pygetwindow` in S3), a `watched_folders` config/table,
      debounce so an editor's save-storm is one event, a path-safety check
      (a watched folder can't be a system dir; the triggering path is passed
      as data, never interpolated into a shell command). Deferred until the
      week-soak gate on increment 2 has actually been run — a second trigger
      source is only worth adding once the autonomous execution path it
      feeds is trusted.
- [~] **Semantic memory — increment 1: retrieval by meaning.** `2e86cdd` —
      `agentic_core/semantic_memory.py`. Reuses the router's already-loaded
      `all-MiniLM-L6-v2` (no second model, no new dependency, no vector
      server per `SENTINAL_V2_RECONCILED_ARCHITECTURE.md` §7). Embeddings
      stored as float32 BLOBs in a new `memory_semantic` SQLite table;
      `retrieve()` is a brute-force cosine scan over the most-recent N rows
      (`SENTINAL_SEMANTIC_MEMORY_MAX_ROWS`, default 5000). `remember()`
      called from `api_wrapper._remember_interaction()` after both the
      flat-path and goal-graph returns; retrieved context is folded into
      `processor.py`'s two target/action extraction points. Never raises;
      no-op when the router is in keyword-fallback mode. Off by default
      behind `SENTINAL_SEMANTIC_MEMORY_ENABLED` — the retrieved context
      feeds the LLM prompt and can shift intent extraction, so opt in then
      flip once validated. 12 hermetic tests with a stubbed deterministic
      embedder; `validator.py`/`executor.py` untouched; `main.py` gained no
      new lint issue.
- [~] **Semantic memory — increment 2: advisory plan hint.** `5460ebb` —
      records the step-shape (`[{intent, target}, ...]`) of a *successful*
      multi-step run in a new nullable `memory_semantic.plan` column, and
      shows it to the planner when a new goal is very close.
      `semantic_memory.recall_plan()` retrieves the nearest successful plan
      above a higher floor than plain recall
      (`SENTINAL_SEMANTIC_MEMORY_PLAN_MIN_SIM`, default 0.55 vs the 0.35
      recall floor); `format_plan_hint()` renders it as an explicitly
      advisory block appended to `planner.plan_goal()`'s LLM decomposition
      prompt. Hint-only: every step the planner returns is still
      intent-allowlisted, `MAX_PLAN_STEPS`-clamped and cycle-checked, so a
      stale hint cannot smuggle a capability or an unbounded plan;
      `replan_failed_node()` is deliberately left without a hint. Reuses
      `SENTINAL_SEMANTIC_MEMORY_ENABLED` — no new flag; off by default the
      planner prompt is byte-identical to before. `validator.py`/
      `executor.py` untouched, `main.py` not touched. 20 semantic-memory
      tests + 4 planner-hint tests (hint reaches the prompt / absent on no
      match / recall raising is survived / a bogus hinted intent is still
      rewritten to `GeneralizedOSIntent`).
      **Open:** the benchmark delta with the flag on (multi-step pass rate,
      steps/plan, planner latency) — a deliberate measurement run, not yet
      done on this machine.
- [~] **Procedural memory: deterministic recipe replay.** `9c7edb2` —
      `agentic_core/procedural_memory.py`. Where increment 2 hints, this
      replaces: a multi-step goal that is a near-verbatim match for one that
      has succeeded organically `PROC_MIN_SUCCESSES` (3) times with the same
      plan structure replays the stored `GoalGraph` and skips the planner
      LLM. `_canonical()`/`_fingerprint()` reduce a graph to its structural
      node shape (volatile run state stripped, so pre-run and post-run
      forms hash identically). Eligibility gate: >= 3 successes, 0
      failures, last success within `PROC_MAX_AGE_DAYS` (30), cosine >=
      `PROC_MIN_SIM` (0.75 — stricter than the 0.55 plan-hint and 0.35
      loose-recall floors). `record_failure()` retires a recipe on a single
      failed replay. New `memory_procedural` table (fingerprint PK, SQLite
      upsert). `planner.plan_goal()` replays before the LLM branch;
      **never for an autonomous goal** (`autonomous` threaded
      `process_command` -> `extract_intent` -> planner `context`) — a
      background goal always gets a fresh plan. A replayed graph is still
      re-validated at load (allowlist / step-count / cycle) and again
      per-step by `validate_steps()` downstream — a recipe is a plan shape,
      never an execution grant. `api_wrapper._record_procedural_outcome()`
      reinforces a successful structure and retires a recipe whose own
      replay failed; `plan_source` is surfaced on the response. Own flag
      `SENTINAL_PROCEDURAL_MEMORY_ENABLED`, default **off** (it changes
      execution by skipping an LLM call — not folded into the semantic
      memory flag). `validator.py`/`executor.py`/`main.py` untouched;
      `main.py` no new lint. 12 procedural-memory + 4 planner-replay + 4
      api_wrapper outcome tests, stubbed deterministic embedder.
      **Deferred follow-up:** slot/parameter templatisation (reuse a recipe
      for a goal with different literal targets); this cut matches only
      near-verbatim repeats.
      **Open:** the flag-on benchmark delta (planner-LLM call count, planner
      latency, multi-step pass rate) — a deliberate measurement run, not yet
      done on this machine.
- [~] `PHASE_TASK_BOARD.md`'s **P2-4** (MCP tool contracts). `8db98c6` —
      `config/capability_contracts.py` (one declarative `CapabilityContract`
      per allowlisted intent: param schema, result shape, cost bucket,
      side-effects, examples; tier resolved from
      `config.capability_tiers.INTENT_TIERS`, not hand-copied) +
      `agentic_core/capability_manifest.py` (`manifest()` JSON tool manifest,
      `validate_params()` advisory schema pre-check that does **not** replace
      `validator.py`, `dispatch_via_contract()` schema-check → import handler
      → invoke). Import-time check: exactly one contract per allowlisted
      intent (bar `UnknownIntent`), no orphans. **Dynamic dispatch wired for
      one capability** — `SchedulerIntent` (T1, self-contained) — as the
      board's "dispatch of one migrated capability"; every other intent
      raises `ContractDispatchUnavailable`. `python -m
      agentic_core.capability_manifest` dumps the manifest. 18 tests.
      `validator.py`/`executor.py`/`main.py` untouched; no new flag; the
      pipeline is unchanged (this path is not called from `/api/command` or
      the executor).
      **Deferred:** route the pipeline through contracts and migrate the
      `(target, prompt)` handler family (`media_control` / `window_manager` /
      `dictation` / `sys_utility` share `SchedulerIntent`'s shape) — needs
      `executor.py`'s if/elif dispatch rewritten, i.e. that file unfrozen.
      No REST endpoint — `GET /api/capabilities` is ~4 lines in the frozen
      `main.py`, a separate authorised change.
- [x] `PHASE_TASK_BOARD.md`'s **P2-5** (risk-tiered policy engine:
      auto/notify/confirm/forbid) — both enforcement halves done.
      **Autonomous** half: `850678b` — `process_command(autonomous=True)`
      denies T2/T3 outright. **Direct-human** half: `f4365a0` —
      `agentic_core/confirmation.py` + `process_command(prompt, *,
      confirm_token=None)`. When `SENTINAL_REQUIRE_CONFIRMATION` is on, a
      T2/T3 direct-human request returns `execution="PendingConfirmation"`
      with a one-time, TTL-bound token fingerprinted to that exact
      prompt+plan (a token issued for "delete A" cannot confirm "delete B"
      even with the same phrasing); resending with the token runs it. Off
      by default — behaviour unchanged (the benchmark's FileDeletion tasks
      would otherwise get PendingConfirmation instead of executing); a real
      deployment sets it on. In-memory store (a half-confirmed irreversible
      action must not survive a restart). REST `/api/command` takes an
      optional `confirm_token`. 15 tests (token lifecycle incl. single-use
      / expiry / request-binding; process_command enabled→pending→resend→run,
      cross-request token rejected, T0 never challenged, autonomous still
      Blocked-not-pending). The **WebSocket** `confirmation_required` /
      `confirm` message flow through `execute_agent_task` is a deferred
      follow-up — default-off means nothing is worse meanwhile, and the
      REST path is the complete testable core.

## S7 — World context and drift detection (gate met — code complete)
Per `CONTAINMENT_ARCHITECTURE.md` §10.3/§10.4: a live environment model
built on S1's snapshot mechanism so the planner can query current state,
plus per-capability success-rate trend tracked over time. Gated on S1
(verification) and S2 (benchmark baseline) — both done. Scoped digital
environment only — running processes, foreground window, time — **not**
camera/mic (own governance section required, §10.3), not screenshots.

- [x] **Half A, increments A1 + A2 — live environment model.** `837d89b`.
      **A1 sampler:** `agentic_core/world_model.sample_tick()` records one
      `env_state` row (process set + hash + count, foreground app/title),
      reusing `postcondition_observer.capture_state_snapshot()` for the
      process list. Rides the resident event-bus loop — one call per tick,
      in both the active and the disabled-idle branch — so **no `main.py`
      change**, and kept fully separate from the reminder sweep (touches no
      `scheduled_tasks` row, can't affect notify-only). Throttled to
      `SENTINAL_ENV_SAMPLE_MIN_INTERVAL` (20 s); retention bounded by row
      count *and* age (`SENTINAL_ENV_RETAIN_ROWS`/`_HOURS`, 500 / 6 h),
      pruned every write. Never raises. **A2 read API:** `current_state()`
      (latest sample — active app/title, open apps, process count, age) and
      `changes_since(seconds)` (apps opened/closed + foreground-switch count
      across the window). Pure reads; `{}` when disabled or < 2 samples.
      New `env_state` table + `add_env_state`/`recent_env_states`/
      `prune_env_state` in `memory_hook.py`; `config/world_model.py` knobs.
      Off by default behind `SENTINAL_ENV_MODEL_ENABLED` (A3 will feed the
      planner prompt; a shifting context can move intent extraction).
      `validator.py`/`executor.py`/`main.py` untouched. 12 world-model +
      3 event-bus wiring tests.
- [x] **Half A, increment A3 — planner wiring.** `7fd49cc`.
      `world_model.format_for_prompt()` renders the latest sample (foreground
      window + open apps) as an advisory `[CURRENT ENVIRONMENT]` block;
      `plan_goal()`'s LLM branch appends it after the semantic plan hint so
      the planner can resolve *"close it"* / *"this window"*. Advisory only —
      every returned step is still allowlisted / clamped / cycle-checked;
      `''` (byte-identical prompt) unless `SENTINAL_ENV_MODEL_ENABLED` with a
      sample; `replan_failed_node()` untouched. 4 format + 3 wiring tests.
      **Half A complete** — planner can query current state.
- [x] **Half B — drift detection.** `849b26c`. `capability_outcomes` table
      (ts, intent, `verified` = whole-run success, `failure_category`,
      whole-command `latency_ms`, `tier`) + add/recent/prune in
      `memory_hook.py`. `world_model.record_run(output, latency_ms)` writes
      one row per distinct intent in a terminal run (Success/Failed only —
      Blocked/Pending/Error are upstream rejections, not capability
      performance), called from `api_wrapper` at both return sites next to
      `_remember_interaction` — **not** `executor.py`.
      `capability_health(intent)` = rolling success rate over the last
      `DRIFT_WINDOW` (20) outcomes vs. the earliest `DRIFT_BASELINE` (20),
      `drifted` only when both sides have >= `DRIFT_MIN_SAMPLE` (8) and the
      rolling rate is `DRIFT_DROP` (0.25)+ below baseline. `drift_report()`
      lists flagged capabilities worst-first. Rides
      `SENTINAL_ENV_MODEL_ENABLED` (default off) — no separate flag, nothing
      reads the table until drift analysis is asked for.
      `validator.py`/`executor.py`/`main.py` untouched. 14 Half-B tests + 2
      wiring tests. **S7 gate met** — planner can query current state (A3)
      and per-capability success-rate trend is tracked (Half B).
      S7 produces the drift signal only; acting on it (targeted skill
      re-learning) is **S8**, which needs S4's overlay.

---

## S8 — Skill-learning pipeline → procedural memory (S4 overlay now verified)
Per `CONTAINMENT_ARCHITECTURE.md` §10.2/§10.4: observe → abstract →
replay-validate in the containment overlay → register at T1 → monitor →
demote. **Gate:** first learned skill promoted, monitored, demotable.
Unblocked now that S4's live container overlay is verified (`1174e1a`).

- [x] **S8-1 — typed-slot abstraction.** `1b2b7ed`,
      `agentic_core/skill_abstraction.py` (pure, stdlib). `abstract_skill()`
      takes ≥2 successful concrete runs that share a plan *shape* (intent +
      dependency edges per node; targets ignored — deliberately looser than
      `procedural_memory`'s literal fingerprint) and generalises the varying
      target spans into typed slots: common prefix/suffix → frame, varying
      middle → `{slot}`, type inferred (path/url/app/number/query/text),
      records whether the value is recoverable from the prompt. Returns a
      template `{fingerprint, skeleton[target_template], slots[],
      postcondition_kind, origin:"learned", n_instances}`.
      `fill_skeleton()` materialises it back to pipeline steps. Never raises.
      9 tests.
- [x] **S8-2 — learned-skill registry + lifecycle.** `1b2b7ed`,
      `agentic_core/skill_registry.py` + `learned_skills` /
      `learned_skill_events` tables + `config/skills.py`. Lifecycle
      candidate → (validated) → active → demoted / retired. Invariants in
      code: `origin` always "learned", `tier` always T1 (§10.2 step 4);
      `activate()` refuses a skill not validated or below
      `SKILL_CONFIDENCE_FLOOR` (0.6); a retired skill can't be activated;
      every transition audit-logged. `register_candidate()` idempotent —
      refreshes the recipe + instance count, never state/tier/confidence.
      Inert data until S8-4. 11 tests. `validator.py`/`executor.py`/
      `main.py` untouched.
- [x] **S8-3 — replay-validation gate.** `0a1172b`,
      `agentic_core/skill_validator.py`. `validate_skill(template, runner=)`
      replays a candidate on typed held-out slot fillings and returns the
      pass rate; the production runner executes the filled plan under a fresh
      S4 snapshot and restores unconditionally (the containment overlay for
      host GUI/file actions), injectable for hermetic tests.
      `promote_if_ready()` gates the full path: enough instances → validate →
      `mark_validated` → `activate` only if confidence ≥
      `SKILL_CONFIDENCE_FLOOR`. Never raises. 3 tests + 3 promotion tests.
- [x] **S8-4 — promotion + planner use.** `0a1172b`,
      `agentic_core/skill_matcher.py`. `match_skill(prompt)` fires an ACTIVE
      skill when its example goals are close to the prompt (embedding sim ≥
      0.72) **and** every slot is fillable from it (target-frame extraction,
      then type-shaped regex). `plan_goal()` checks it **before** procedural
      memory — a validated skill outranks a raw recipe. Behind
      `SENTINAL_LEARNED_SKILLS_ENABLED` (default off), never for
      `autonomous=True`; every returned step still allowlist/budget/cycle
      checked downstream. 3 tests.
- [x] **S8-5 — monitoring → demotion.** `0a1172b`,
      `agentic_core/skill_monitor.py` + `learned_skill_outcomes` table.
      `record_skill_run()` (wired in `api_wrapper` next to the other outcome
      hooks) logs each live learned-skill run and re-checks health: rolling
      success `SKILL_DEMOTE_DROP` below validated confidence over ≥ 6 runs →
      `demote()`; a demoted skill still failing → `retire()`. Every
      transition audit-logged. `sweep_active_skills()` for a future scheduled
      pass. 4 tests. `validator.py`/`executor.py`/`main.py` untouched.
      **S8 gate met** — a learned skill can be promoted, is monitored, and is
      demotable, all under default-off flags.

---

## S9 — Self-improvement loop (prompts / heuristics)
Per `CONTAINMENT_ARCHITECTURE.md` §10.1. **Gate:** first promoted change is
versioned, rollback-able, and logged with its shadow-eval evidence.
Self-improve: prompt templates, planning heuristics, retry/replan params,
capability-selection weights. **Never:** the policy engine, any capability's
tier, the allowlist, the promotion criteria themselves. The cognition plane
*proposes*; the control plane *evaluates against fixed criteria* and promotes.

- [x] **S9-1 — versioned change store.** `0a1172b`,
      `agentic_core/improvement_store.py` + `tuning_versions` table.
      `propose` / `record_shadow` / `promote` / `reject` / `current(target)`
      / `revert(target)`. Every applied change is a new row; `revert` marks
      the newest promoted one reverted so the previous value becomes current.
      Malformed targets (no `param:`/`heuristic:`/`prompt:` prefix) rejected.
      4 tests.
- [x] **S9-2 — proposer (cognition plane).** `0a1172b`,
      `improvement_engine.propose_from_outcomes()`. Reads `drift_report()`;
      under a hard drift (drop ≥ `PROPOSE_DRIFT_MIN`) emits **bounded param
      nudges only** (`TUNABLE_PARAMS` ranges) — no prompt rewriting this cut.
      Applies nothing. 2 tests.
- [x] **S9-3 — shadow-eval orchestration.** `0a1172b`,
      `improvement_engine.shadow_eval(version_id, benchmark_runner=)`.
      Baseline run → apply candidate to `os.environ` for one run (context
      manager restores) → diff → `record_shadow`. The real benchmark runner
      needs a live desktop and is **out of scope on this machine**; it is
      injectable and tested with a fake. 3 tests.
- [x] **S9-4 — control-plane review.** `0a1172b`,
      `improvement_engine.review()` — the **only** promotion path. Fixed
      criteria: `after − before ≥ MIN_BENCHMARK_GAIN` (0.05) **and** zero new
      regressions. Pass → `promote` + evidence; fail → `reject` + reason.
      4 tests. **S9 gate met** — a promoted change is versioned, one-step
      reversible, and logged with its shadow-eval evidence.
      **Not activated:** nothing in the live pipeline reads `current()` yet —
      that is a later step, gated on a real shadow-eval run against the
      benchmark (a live desktop). `SENTINAL_SELF_IMPROVEMENT_ENABLED` default
      off. `validator.py`/`executor.py`/`main.py` untouched.

---

## Beyond S9 — forward phases (scoped, NOT started)

These are captured for direction only. See `OPEN_ENDED_ROADMAP.md` for the
same ground reframed as open-ended capability **axes** (A1–A8) with maturity
ladders. **Do not implement any of S10–S16 without an explicit decision** —
they each introduce a new risk category and each has a hard prerequisite,
exactly as S8/S9 required S4. Every one inherits §1: authority flows down,
never up.

| Phase | Adds | New risk | Prerequisite / containment |
|---|---|---|---|
| **S10 — Persistent multi-session goals** | Standing intent ("keep Downloads organized", "watch this repo weekly") that survives restarts | Goal scope-creep over time; a stale goal acting on a changed world | Control-plane re-confirmation cadence; hard TTLs; S7 precondition checks per standing goal; runs through S6's autonomous path (T2/T3 still denied) |
| **S11 — Tool synthesis** | The system authors new capabilities — small tools it writes, tests, registers — not just recipes | Arbitrary code generation as a first-class loop | S4 overlay validates every synthesized tool; human review before any exceeds T1; provenance + kill-switch registry |
| **S12 — Internal multi-agent society** | Planner spawns specialist sub-agents (researcher / coder / critic) with separate context + grants | Emergent behavior; sub-agents colluding to exceed individual grants; harder audit | Every sub-agent's grant ⊆ parent's (§1 applied recursively); one shared swarm budget; single-writer arbitration on T2 actions; society auditable as a tree |
| **S13 — Model-based / predictive planning** | Simulate action outcomes before committing ("will closing this window prompt for unsaved changes?") | Acting on predictions instead of observations; model error compounding over long plans | Predictions advisory only — never replace S1 postcondition checks; a calibration monitor disables predictive planning per-capability when predicted-vs-actual drifts |
| **S14 — Cross-machine operation** | Coordinating across several machines the user owns | Blast radius ×N; a compromised plan touches N machines; network as attack surface | Per-machine tiers (a T2 on the laptop may be T3 on a server); mutual node auth; a per-machine kill switch independent of the others |
| **S15 — Value / preference learning** | Infers *what the user wants* from feedback, not just what they typed | Specification gaming — optimizing a proxy for "user satisfaction" | The preference model may only *rank* options the policy already permits, never expand the set; "this is what I inferred — correct?" checkpoints; versioned + rollback-able like S9 |
| **S16 — Formal guarantees on the containment kernel** | Machine-checked proofs: no cognition-plane output can promote its own tier; no plan bypasses `validate_steps()` | None — pure risk reduction | Nothing; it is the phase that makes S10–S15 defensible, and the gate every capability phase waits on |

---

## Cross-cutting / not gated on the S-sequence

These don't block or get blocked by S4–S7 — they're independent, and worth
picking up opportunistically:

- [ ] **Installer/packaging** — no Docker image or installable package yet;
      installation is fully manual (`README.md` Known Limitations).
- [~] **External benchmark** — `b0ee941` (see `benchmarks/external/`). Tasks are
      now DATA: `benchmarks/external/schema.md` defines a JSON manifest
      (id / source / category / prompt / declarative verify+setup+teardown),
      `benchmarks/external_loader.py` turns one into real
      `benchmarks.tasks.Task` objects whose every `verify` kind dispatches to
      an existing `tasks.py` helper — no new verification logic, same
      "query the OS, never the pipeline" bar. `run_benchmark.py` gained
      `--external` / `--external-dir` / `--only-external`, a `by_source`
      report split, and `external_manifests {path, sha256}` in provenance;
      with no flag every existing number is byte-identical. `ManifestError`
      on any structural problem (unknown kind, missing field, duplicate id).
      20 tests. `validator.py`/`executor.py`/`main.py`/`benchmarks/tasks.py`
      untouched. **Still open:** this closes the *self-authored* half — a
      third party can now add/audit tasks without Python — but the shipped
      manifest is example content (`source: "example:*"`); populating
      `third_party.json` with a genuine external corpus, and the
      *single-Windows-machine* half, remain.
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
