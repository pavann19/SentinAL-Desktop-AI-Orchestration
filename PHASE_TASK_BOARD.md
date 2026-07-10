# Phase 1 & 2 Task Board — Agent Assignments

**Agents:** `CLAUDE` (integrator/verifier/security) · `ANTIGRAVITY` (vision/UIA/large-context/UI) · `CODEX` (self-contained modules, tests, scaffolding)
**Every task gets its own git branch, its own commit, and must clear all 5 gates in VERIFICATION_PROTOCOL.md.**
**Status legend:** `TODO` / `WIP` / `IN-REVIEW` / `DONE` (5 gates green) / `BLOCKED`

---

## Role definitions

### CLAUDE (me) — Integrator, Verifier, Security-critical owner
- **I do NOT parallelize well as a bulk code-writer with the others — my value is being the single source of truth.** I own: the git repo, the task board, MERGE_LOG, running all 5 gates, and merging every branch.
- **Modules I personally write** (because they touch safety and I already know them cold):
  - `agentic_core/validator.py` risk-tier upgrade
  - `agentic_core/executor.py` observe-act loop rework
  - `system_services/privacy_router.py` policy-engine extension
  - the policy/RBAC layer ported from your AI_Governance project
- **Verification duty:** I am the one who runs Gates 1–5 on *every* task, including my own (for my own code, a second agent writes the independent tests — Gate 2 stays honest).
- **Why me for integration:** I have the full repo context, git access, and I already caught the stub fraud once. I keep the STATE file so any token-exhausted agent can resume.

### ANTIGRAVITY — Perception, OS-native, Front-end
- Best at: large context, multimodal (screenshots), IDE-scale refactors, the Electron/React HUD.
- Modules: `capabilities/system/vision_module.py`, Windows UIA integration, `capabilities/system/gui_resolver.py`, `sentinal-ui/` HUD changes.

### CODEX — Self-contained, well-specified, high-volume
- Best at: fast codegen on tight specs, test writing, boilerplate, data generation.
- Modules: OpenTelemetry tracing layer, MCP tool-contract scaffolding, the labeled intent dataset, the task-success benchmark harness, independent test suites (Gate 2 author).

---

## PHASE 1 — Close the loop (target ~2 weeks)

| ID | Task | Owner | Independent tests by | Evidence artifact (Gate 4) |
|----|------|-------|---------------------|----------------------------|
| P1-1 | Observe-act loop: `execute_pipeline` returns observation objects; postcondition verifier | CLAUDE | CODEX | before/after state snapshot pair per step |
| P1-2 | Wire `vision_module.verify_screen_state` into the loop as a verifier | ANTIGRAVITY | CODEX | screenshot diff proving detection of a failed action |
| P1-3 | OpenTelemetry tracing: span per task→step→tool call, export to file | CODEX | CLAUDE | exported span tree JSON for a 3-step task |
| P1-4 | Failure taxonomy + one bounded replan on postcondition mismatch | CLAUDE | CODEX | trace showing a failure→replan→success |
| P1-5 | Task-success harness: scripted N-task suite with pass/fail criteria | CODEX | CLAUDE | success-rate report over ≥10 tasks |

**Phase 1 exit demo:** run a task that fails on first attempt (e.g. target window not focused), watch the loop detect it via vision, replan, succeed — with the full trace and screenshots saved to `_evidence/phase-1/`.

## PHASE 2 — Cognitive layer (target ~2.5 weeks)

| ID | Task | Owner | Independent tests by | Evidence artifact (Gate 4) |
|----|------|-------|---------------------|----------------------------|
| P2-1 | LangGraph planner graph (plan→act→observe→reflect) wrapping the pipeline | CLAUDE | CODEX | saved plan DAG + trace for a multi-step goal |
| P2-2 | Semantic memory tier (vector store, local Qdrant) + retrieval | CODEX | ANTIGRAVITY | cross-session recall proof (fact written run A, recalled run B) |
| P2-3 | Procedural memory: learned task recipes cached & reused | CODEX | CLAUDE | 2nd run of same task uses cached recipe (trace shows skip-replan) |
| P2-4 | Migrate capabilities to MCP tool contracts (schema+risk tier+cost) | ANTIGRAVITY | CODEX | tool manifest + dynamic dispatch of one migrated capability |
| P2-5 | Risk-tiered policy engine (auto/notify/confirm/forbid) in validator | CLAUDE | CODEX | policy decision log across all 4 tiers |

**Phase 2 exit demo:** give a compound goal ("research topic X, summarize to a file, and schedule a reminder"); planner decomposes it, executes via MCP tools, memory records it, policy engine gates the file-write — full trace + policy log saved to `_evidence/phase-2/`.

---

## Token-limit discipline (all agents)

1. **One task = one agent session.** Never assign a task that can't finish inside a single context window. If a task feels big, it's two tasks.
2. **Context packs, not repo dumps.** Each agent gets ONLY the files its task needs (listed in the task) + this board + the protocol. They must not explore the whole repo — that burns tokens and invites divergence.
3. **Commit-per-task = resumable checkpoint.** A token-exhausted agent leaves a committed branch; the next session (or another agent) resumes from git, not from scratch.
4. **Verification is scripted (Gates 3, 5).** Claude does not re-read the codebase to verify — it runs `pytest`. Cheap.
5. **STATE.md is the memory.** Current task, current branch, what's blocked — one short file so no agent re-derives context after a reset. Updated at the end of every session.
6. **Claude reviews diffs, not whole files.** Gate 1 reads `git diff`, not the entire module.

---

## STATE (update every session)

- **Current phase:** Phase 1 — not started
- **Active tasks:** none assigned yet
- **Last green tag:** none (baseline `4c7af25`, 247 tests)
- **Blocked:** none
- **Next action:** assign P1-3 (tracing, CODEX) and P1-5 (harness, CODEX) first — they're independent, unblock evaluation, and don't touch core code.
