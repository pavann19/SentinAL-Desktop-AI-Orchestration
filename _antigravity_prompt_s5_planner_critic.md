You are working in the SentinAL repo at `D:\college\Major Project\SentinAL-v9-reunited`
(Python/FastAPI backend, voice-controlled desktop agent for Windows), on the `main` branch.

## Task

Implement S5 from `ROADMAP.md` (and `CONTAINMENT_ARCHITECTURE.md` §5/§7's P3 "Cognition"
plane): replace `agentic_core/processor.py`'s flat, regex-based multi-step splitter with a
real planner + critic split — a goal graph that can sequence, verify, and (bounded) replan
across steps — **without touching the security-critical validation/execution boundary**.

## Read these files first, in full, before writing anything

1. `agentic_core/processor.py` — specifically `split_multistep()` (~line 261) and
   `extract_intent()` (~line 359). This is what you're replacing/extending.
   `split_multistep()`'s own docstring documents its real limits: a deterministic
   regex splitter, capped at 3 steps, no goal graph, no reflection. Read the "KNOWN
   LIMITATION" note in its docstring carefully — it's an example of this codebase's
   own convention of stating what a mechanism does NOT do, honestly, in the code
   itself. Match that convention in whatever you write.
2. `agentic_core/executor.py`'s `execute_pipeline_observed()` (~line 1024) and
   `_run_and_observe()` (~line 964) — the existing observe/classify/bounded-replan
   loop (P1-4). Your planner's "critic" role should integrate with this, not
   duplicate it — the postcondition observer (`capabilities/system/postcondition_observer.py`)
   already answers "did this step actually work?" for 13 of 19 intents. Don't build a
   second verification mechanism where this one already applies.
3. `agentic_core/router.py`'s `SemanticRouter.route()` — per
   `SENTINAL_V2_RECONCILED_ARCHITECTURE.md` §3's corrected residency: the planner
   must be invoked only when the router's own multi-step determination fires, not on
   every request. Read how routing currently decides single-step vs multi-step (today
   that's `split_multistep()` being called at all) and preserve that gate — critic
   logic can be resident, but the planner itself must stay on-demand.
4. `ROADMAP.md`'s S5 section and `CONTAINMENT_ARCHITECTURE.md` §5's P3 row — your
   scope boundary. A goal graph replacing the flat step list; planner gated behind
   the router's multi-step signal; critic resident and reusing the existing
   postcondition observer.

## The one rule that matters more than anything else in this task

**Do not modify `agentic_core/validator.py` or any of `execute_pipeline_observed()`'s
existing postcondition/replan/failure-taxonomy logic.** Your planner sits *upstream* of
validation — it decides what steps to attempt, in what order, and whether to replan
after a step's own postcondition check fails. It does not get to skip, weaken, or
bypass `validate_steps()`'s allowlist/sandbox/keyword-filter/human-confirmation gate for
any step it produces. Every step your planner emits still goes through the exact same
validation and execution path that a single-step request does today. If you find
yourself wanting to touch `validator.py` to make something work, stop and flag it in
your final report instead of making the change — that decision belongs to a human
review, not to this task.

## Scope, concretely

- A goal graph (plan → act → observe → reflect) that can represent more than a flat
  3-step cap — real dependencies between steps, not just an ordered list.
- Planner invoked only behind the router's existing multi-step signal — a single-step
  request must cost nothing extra; no added latency, no added LLM call.
- Critic role integrates with the existing postcondition observer rather than
  inventing a parallel verification mechanism.
- Bounded replan: reuse or extend `MAX_REPLANS` semantics from `executor.py` rather
  than inventing an unbounded reflection loop — an agent that can retry forever on a
  genuinely failing step is a new failure mode, not a feature.
- **Dependency budget**: this is a resource-constrained dev machine (12GB RAM). Before
  adding any new library (LangGraph or otherwise), check its actual install footprint
  and justify it in your final report. Prefer a lighter, dependency-free goal-graph
  implementation if the task doesn't genuinely need a full framework — a hand-rolled
  DAG over a dict of step dependencies may be entirely sufficient here and is worth
  strongly preferring over a heavy new dependency.

## Testing — and a hardware-driven constraint on how you verify locally

Write real tests (no hollow mocks) for the new planner/critic logic, following this
repo's existing test conventions (see `tests/test_executor_replan.py`,
`tests/test_postcondition_coverage.py` for the house style — real fixtures, explicit
regression-guard comments explaining *why* a test exists, not just what it asserts).

**Do not run the full test suite (`pytest -q` with no path filter) on this machine.**
It's ~1000 tests and takes 5-9 minutes under real memory pressure — safe in principle,
but not what this task needs mid-development. Instead:
- Run only the new test file(s) you're adding, plus the specific existing files you
  touch (e.g. `pytest tests/test_processor.py tests/test_executor_replan.py -q --no-cov`).
- Do not start Docker, do not run `benchmarks/run_benchmark.py`, do not do anything
  that spawns real GUI windows or long-running processes as part of routine
  iteration — those are reserved for a separate, deliberate validation pass on other
  infrastructure, not this task.

## Commit discipline

- Commit locally on `main` only. **Do not push to `origin` or touch `public-release`
  in any way** — that branch is frozen for now per explicit instruction, regardless of
  what state your local `main` ends up in.
- Do not edit `README.md` with any numbers from your local test runs — this machine's
  local measurements are explicitly not being used to update public-facing docs right
  now.
- Real, atomic commits with clear messages, matching this repo's existing commit style
  (see recent `git log` on `main` for tone/format — explain the *why*, not just the
  *what*, and state honestly what you did NOT verify, the same way the rest of this
  session's work has).

## When you're done

Leave your work as clean local commits on `main`. In your final message, report:
1. What you built (goal graph representation, planner gating mechanism, critic wiring).
2. Which existing files you touched and why, and confirm `validator.py` and
   `execute_pipeline_observed()`'s core logic are untouched.
3. What tests you added and ran, and their result.
4. Anything you deliberately left out of scope or flagged rather than implemented
   (per "the one rule" above, or the dependency-budget note).

I'll verify against this repo's 5-gate acceptance ladder (`VERIFICATION_PROTOCOL.md`) —
diff-is-real, independent tests, coverage delta, a real runtime artifact showing a
multi-step goal actually executing and being verified, and a regression check — before
this is considered done.
