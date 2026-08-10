# SentinAL — Containment-First Autonomy Architecture

**Date:** 2026-08-04 · **Basis:** direct code audit at commit `2f631c0` (480 tests green, 76.95% coverage)
**Relationship to existing docs:** extends `AGENTIC_OS_ROADMAP_AND_THESIS_PLAN.md`; proposes **one ordering change** to it (see §6).

---

## 1. Premise

The design goal is a highly capable, increasingly autonomous desktop agent — with the
property that capability never outruns oversight.

The failure mode to design against is not intelligence, it is **capability scaling faster
than containment**: a system that can act more broadly than anything can inspect,
interrupt, or reverse. Every dangerous property follows from that structural fact.

This inverts the usual planning order. Sandboxing, budgets, provenance and kill switches
are not overhead added at the end — they are the **enabling substrate**. You cannot
responsibly grant broad autonomous action on a real machine until failure is cheap,
observable, and reversible. Once it is, you can grant far more autonomy than an
uncontained system could ever justify.

**Rule:** every increment of autonomy is gated behind the containment capability that
makes that increment recoverable.

---

## 2. The invariant

```
┌─────────────────────────────────────────────────────────────┐
│  COGNITION PLANE                              [ UNTRUSTED ] │
│  planner · executor · critic · memory · all LLM calls       │
│  Assumed compromisable: bad model output, prompt injection  │
│  in a web page, malicious content in a file it just read.   │
└─────────────────────────────────────────────────────────────┘
        │  requests capability                ⊘  cannot read, write,
        ▼  receives scoped, revocable token      disable or negotiate
┌─────────────────────────────────────────────────────────────┐   its own policy
│  CONTROL PLANE                                  [ TRUSTED ] │
│  policy engine · capability broker · audit log ·            │
│  resource budgets · kill switch                             │
│  Out-of-process. Deterministic code only, no model in loop. │
└─────────────────────────────────────────────────────────────┘
```

**Authority flows down, never up. No model output can widen its own permissions.**

The agent is a *client* of the control plane, never an administrator of it. This makes
the codebase's existing position — assume the LLM will eventually be compromised —
structural rather than a matter of careful coding in each handler.

---

## 3. Audit findings

### 3.1 The closed loop is already built ✅

`agentic_core/executor.py :: execute_pipeline_observed()` provides:
- before/after state snapshots (`capture_state_snapshot` / `diff_snapshots`)
- per-step postcondition checks, 3 tiers (`process`, `window`, `vlm`)
- failure taxonomy (`_classify_result`)
- bounded whole-pipeline replan (`MAX_REPLANS`, env `EXECUTOR_MAX_REPLANS`, default 1)

This is the hardest architectural piece of Phase 1, and it is done and tested.

### 3.2 It covers 1 of 15 intents ⚠️ — the live gap

`capabilities/system/api_wrapper.py :: _derive_expected_state()` returns a postcondition
for `ApplicationLaunchIntent` and `None` for everything else. `ALLOWLIST_INTENTS` has 15
entries. So **14 of 15 intents execute blind** — they report success whenever they fail to
raise, and the verification machinery sits idle behind them.

This is the direct explanation for why the ~60% end-to-end success rate is hard to move:
silent failure is undetectable for 93% of intents, and you cannot fix what you cannot see.

### 3.3 "Sandbox" is a path denylist ❗

`agentic_core/validator.py :: validate_sandbox()` does careful path/string matching
(drive roots, `windows\`, `system32`, `SENSITIVE_TARGETS`, `SOFT_SENSITIVE_TARGETS`).
That is a useful pre-execution filter, but **nothing contains the process** — actions
execute with the user's full privileges. Defensible for today's supervised single-user
operation; it is the binding constraint on any real autonomy.

---

## 4. Postcondition coverage gap

| Intent | Verifiable via | Tier | Status |
|---|---|---|---|
| `ApplicationLaunchIntent` | process appears | process | ✅ wired |
| `WebNavigationIntent` | browser window title contains host | window | ❌ blind |
| `MediaStreamingIntent` | player window + audio session | window | ❌ blind |
| `ProcessManagementIntent` | process absent/present after action | process | ❌ blind |
| `FileDeletionIntent` | path no longer exists | **filesystem (new)** | ❌ blind |
| `ProjectScaffoldIntent` | target dir + manifest exist | **filesystem (new)** | ❌ blind |
| `DependencyInstallIntent` | package resolves in target env | **filesystem (new)** | ❌ blind |
| `SysUtilityIntent` | setting reads back changed | **system query (new)** | ❌ blind |
| `GeneralizedOSIntent` | declared per-action expectation | mixed | ❌ blind |
| `CodeActIntent` | exit code + declared artifact | **filesystem (new)** | ❌ blind |
| `InformationRetrievalIntent` | response non-empty, on-topic | **semantic (new)** | ❌ blind |
| `ConversationalIntent` | response non-empty | **semantic (new)** | ❌ blind |
| `ContinuationIntent` | response non-empty | **semantic (new)** | ❌ blind |
| `AcademicResearchIntent` | output artifact exists | **filesystem (new)** | ❌ blind |
| `DataModelingIntent` | output artifact exists | **filesystem (new)** | ❌ blind |

**Two new observer tiers (filesystem, system query) cover most of the gap.** Four intents
are already covered by existing tiers and need only the `expected_state` derivation.

---

## 5. Target architecture — six planes

Read bottom-up; each plane is load-bearing for the one above it.

| # | Plane | Today | Target |
|---|---|---|---|
| P6 | **Governance & oversight** | `validator.py`, `privacy_router.py`, `security_audit.log` | ⚠️ partial → + policy engine, capability broker, taint labels on LLM-derived args |
| P5 | **Containment substrate** | *(none — `validate_sandbox()` is a denylist)* | ❌ missing → overlay writes, snapshots, egress policy, resource budgets |
| P4 | **Autonomy & triggers** | `scheduler.py` (FIFO queue, cap 20) | ❌ missing → event bus (fs watchers, timers, calendar), background goals w/ budgets |
| P3 | **Cognition** | `processor.py` single-shot flat step list; bounded replan | ⚠️ partial → planner/executor/critic split, goal DAG, reflection |
| P2 | **Memory & world model** | `memory_hook.py` SQLite log; `capability_registry.py` | ⚠️ partial → episodic + semantic (vector) + procedural recipes |
| P1 | **Perception & verification** | `postcondition_observer.py` 3 tiers ✅ | ⚠️ partial → +2 tiers, +14 intents |

**P5 is the gate on P4.**

---

## 6. Containment tiers

Autonomy is granted per capability, per tier. A capability moves up a tier only when the
containment for it exists.

| Tier | Containment | Autonomy unlocked | Reversal |
|---|---|---|---|
| **T0** | Read-only; no mutation possible | Fully autonomous, no confirmation, no budget | nothing to reverse |
| **T1** | Scoped write to overlay; commit explicit | Autonomous within declared working directory | discard overlay |
| **T2** | Real writes + pre-action snapshot + provenance | Autonomous with notification; user can undo after | restore snapshot |
| **T3** | Irreversible (delete, send, purchase, credentials) | **Never autonomous** — per-action human confirmation | none; hence the gate |

Today every capability effectively runs at **T2 without the snapshot** — which is exactly
why the substrate is the gate on everything else.

*Thesis note:* risk-tiered capability grants with per-tier reversal guarantees is a
defensible contribution, and instrumenting it produces evaluation data for free.

---

## 7. Sequenced plan

Ordered by dependency, not ambition. Each stage produces the evidence the next one needs.

| Stage | Work | Gate to clear | Why here |
|---|---|---|---|
| **S1** | Complete the observe loop: add filesystem + system-query tiers to `observe_postcondition()`; derive `expected_state` for all 15 intents | silent-failure rate measurable per intent | cheapest, highest leverage; machinery already built and idle |
| **S2** | Task benchmark: 50 scripted real tasks with pass criteria, run per commit | success rate is a tracked number, not an estimate | needs S1 — can only score what you can verify |
| **S3** | Fix what the benchmark exposes; likely GUI grounding first (UIA tree over pixel coords) | success rate materially above ~60% | needs S2 to target real failure modes, not guesses |
| **S4** | Containment substrate: overlay writes, snapshots, budgets, capability broker | T1/T2 reversal demonstrated under test | **the gate on all autonomy** |
| **S5** | Planner + critic split; goal graph replaces flat step list | multi-step tasks succeed where single-shot fails | safe to let plans get ambitious once S4 makes mistakes cheap |
| **S6** | Proactive autonomy: event bus, background goals under budget + tier policy | runs unattended a week with no unwanted action | everything above is prerequisite |

### Proposed change to the existing roadmap

`AGENTIC_OS_ROADMAP_AND_THESIS_PLAN.md` reaches the cognitive layer in Phase 2 and
proactive autonomy in Phase 3, with deeper isolation arriving later (Phase 4).

**That ordering builds capability ahead of containment** — precisely the shape of the
failure mode this design exists to avoid. S4 should move ahead of S5/S6. It costs little
now and gets much more expensive to retrofit once a planner is issuing multi-step actions
autonomously.

---

## 8. Honest limits

1. **This does not approach JARVIS/FRIDAY.** Those assume solved general intelligence —
   open-ended reasoning, full sensory awareness, correct inference of unstated intent.
   Nobody is there. What is achievable is a reliable, contained, increasingly proactive
   desktop agent.

2. **Success rate is the hard part.** ~60% → ~90% on real desktop tasks is not one fix.
   It is a long tail of grounding failures, timing races, and ambiguous instructions.
   S1–S3 make that tail *visible*; nothing makes it short.

3. **Containment on Windows is genuinely hard.** Filesystem overlays and rollback for GUI
   automation are not solved problems. Expect S4 to be partial — strong for file/process
   operations, weaker for arbitrary GUI actions. Scope the tier table to what can actually
   be reversed.

---

## 9. Immediate next task (S1, first commit)

1. Add a **filesystem tier** to `capabilities/system/postcondition_observer.py`:
   `expected` key `path_exists: str` / `path_absent: str` → `os.path.exists()` check,
   returning an `Observation` with `tier_used="filesystem"`, confidence 1.0.
2. Extend `_derive_expected_state()` in `capabilities/system/api_wrapper.py` beyond
   `ApplicationLaunchIntent` — start with the four intents needing no new tier
   (`WebNavigationIntent`, `MediaStreamingIntent`, `ProcessManagementIntent`) plus
   `FileDeletionIntent` on the new filesystem tier.
3. Regression tests per intent, asserting the postcondition is actually derived and the
   mismatch path classifies as `postcondition_mismatch`.

This activates verification for the majority of intents, turns the dormant bounded-replan
path load-bearing, and starts producing per-intent failure data that S2 onward depends on.
Small, well-isolated, and testable against the existing suite.

---

## 10. Open-ended capability: self-improvement, skill learning, world context, dynamic environments

These four are the pieces that turn a fixed capability set into an open-ended system. They
are also, structurally, the **highest-risk category in this whole design** — a system that
rewrites its own prompts, learns new action sequences, or changes its own behavior based on
what it observes is a system modifying itself. That is the literal mechanism the §1/§2
invariant exists to contain. So these four get the *strictest* gating in the architecture,
not the loosest, and none of them are exempt from "authority flows down, never up."

Concretely: self-improvement never means the cognition plane edits its own policy, its own
containment tier, or its own promotion criteria. It means the cognition plane *proposes*
changes, the control plane *evaluates* them against fixed, human-set criteria, and only the
control plane promotes or rejects. The loop is closed, but the plane that closes it is the
trusted one.

### 10.1 Self-improvement loop (extends P3, gated by P5/P6)

What can legitimately self-improve without becoming unsafe: prompt templates, planning
heuristics (which capability to try first for a given intent), retry/replan parameters,
capability-selection weights. What must never self-improve unsupervised: the policy engine,
the containment tier of any capability, the allowlist, the promotion criteria themselves.

```
outcome data (P1 observations)
        │
        ▼
candidate change  ── e.g. "prefer capability B over A for WebNavigationIntent
        │              when target contains 'docs.'" — proposed by cognition plane
        ▼
shadow evaluation  ── replayed offline against the S2 task benchmark, never against
        │              the live system; produces a before/after score, not a belief
        ▼
control-plane review  ── fixed, human-set acceptance criteria (e.g. "≥5% success-rate
        │                 gain, zero new regressions across the benchmark")
        ▼
  ┌─────────────┐        ┌──────────────┐
  │  PROMOTED   │        │   REJECTED    │
  │  versioned, │        │   discarded,  │
  │  logged,    │        │   logged with │
  │  rollback-  │        │   reason      │
  │  able       │        │               │
  └─────────────┘        └──────────────┘
```

Every promotion is versioned (so any change can be reverted to the prior version in one
step) and every promotion and rejection is written to the audit log with the evidence that
produced the decision. No change is ever promoted from a single live run — only from
replay against the fixed benchmark, which is why S2 (the task benchmark) is a hard
prerequisite for this stage, not an optional nice-to-have.

### 10.2 Skill learning → procedural memory (fills the gap in P2)

A **skill** is a validated capability recipe: a parameterized sequence of steps, its
preconditions, and the postcondition that proves it worked — structurally identical to
what already exists for hand-written capabilities in `capability_registry.py`, just
originated differently.

Acquisition pipeline:
1. **Observe** a task the pipeline completed successfully (per P1 postcondition
   verification — this is why S1 is upstream of skill learning, not parallel to it).
2. **Abstract** the concrete step sequence into a parameterized recipe (replace literal
   values like a specific filename with a typed slot).
3. **Validate by replay**, in the P5 containment overlay, on 2–3 held-out variants of the
   same task class — never on the live filesystem.
4. **Register** at containment **tier T1** by default, `origin="learned"`, with a
   confidence score, regardless of what tier a hand-written equivalent might carry — a
   learned skill starts more restricted than a human-authored one, and earns tier
   promotion only after a track record (§6 tiers already model exactly this kind of
   earned trust).
5. **Monitor.** A learned skill whose live success rate drops below its validated
   confidence over a rolling window is automatically demoted, not silently kept — this
   is the same mechanism as §10.3's drift detection, applied to the skill's own recipe.

### 10.3 World context and dynamic environments (extends P1 + P2)

"Real-world context" for a desktop agent should be scoped honestly: it means the user's
digital environment — open applications, active window, filesystem state, calendar,
notifications, time — not physical sensors. Camera/ambient-microphone context is a
materially different, much higher privacy-risk category and would need its own explicit
opt-in and governance section if it's ever wanted; it is deliberately **not** assumed here.

Two additions:

- **A live environment model**, queryable by the planner, built from the same
  `capture_state_snapshot()` mechanism that already exists in
  `postcondition_observer.py` — extended from a one-shot before/after diff into a
  continuously-updated table the planner can query ("what's currently open," "what
  changed in the last 10 minutes"). This is what turns memory from a log (P2 today) into
  a *world model*.
- **Environment drift detection.** Every capability's live success rate (from P1
  observations) is tracked over a rolling window. A sustained drop for one capability —
  independent of everything else — is the signal that the environment changed under it
  (an app updated its UI, a website redesigned its layout), not that the agent got worse
  generally. That signal is what triggers re-learning of the specific affected skill
  (§10.2) rather than a blanket retrain, and it's also the mechanism that makes GUI
  automation survivable long-term against UI drift, which pixel/coordinate targeting
  (current `gui_resolver.py` approach) is otherwise permanently fragile against.

### 10.4 Sequencing addition

These four extend the plan in §7, not replace it. Ordering, added as new stages:

| Stage | Work | Gate to clear | Why here |
|---|---|---|---|
| **S7** | Live environment model + drift detection, built on P1's snapshot mechanism | planner can query current state; per-capability success-rate trend is tracked | needs S1 (verification) and S2 (benchmark baseline) to have a trend to detect drift against |
| **S8** | Skill learning pipeline: observe → abstract → replay-validate → register at T1 | first learned skill promoted, monitored, demotable | needs **S4 containment** — replay validation happens in the overlay, nowhere else |
| **S9** | Self-improvement loop for prompts/heuristics, per §10.1 | first promoted change is versioned, rollback-able, and logged with its shadow-eval evidence | needs S2 (benchmark, for shadow eval) and S4 (containment, same reason as S8) |

Note the shared dependency: **S8 and S9 both require S4 first.** This is the concrete
reason self-improvement and skill learning were placed after the containment substrate in
this design rather than earlier — they are, by definition, the system changing its own
behavior, so they are exactly the category §1 says must never be granted before the
substrate that makes it reversible exists.
