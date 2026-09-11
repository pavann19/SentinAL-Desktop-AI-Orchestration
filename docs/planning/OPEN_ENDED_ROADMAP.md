# SentinAL — Open-Ended Capability Roadmap

Extends `ROADMAP.md` (S1–S9, the foundational track) and
`CONTAINMENT_ARCHITECTURE.md` §10. Where S1–S9 are **milestones** — each
done or not-done — the axes below are **open-ended**: each is a dimension of
capability with a maturity ladder that, in principle, never terminates. The
project advances an axis one level at a time; "complete" is never the target,
"the next defensible level" is.

## Framing: JARVIS, not Ultron

The difference between JARVIS/FRIDAY/EDITH and Ultron is **not** capability —
Ultron was not more capable, it was uncontained and unaligned. So capability
(axes A1–A5, A8) may grow without bound **only while** two axes keep pace:

- **A6 (value alignment)** — the system acts in the user's interest, refuses
  on principle, and never treats its own objective as above the user's.
- **A7 (assurance)** — the containment kernel is *provably* sound, and no
  capability axis advances a level until A7 covers the new surface.

Every axis below inherits the §1 invariant of `CONTAINMENT_ARCHITECTURE.md`:
**authority flows down, never up.** The cognition plane proposes; the control
plane — the trusted, human-set plane — disposes. Nothing the system learns,
synthesizes, or infers can promote its own tier, edit its own policy, widen
its own allowlist, or rewrite its own promotion criteria.

---

## Current position (as of S8-5 / S9-4)

| Axis | Level | Where | Session hours |
|---|---|---|---|
| A1 Temporal horizon | **L1** | multi-step DAG plans (S5); S10 (standing goals) scoped, not built | 0h — scope only |
| A2 Capability genesis | **L1→L2** | learned recipes (S6); typed-slot skills, registry, replay-validation, matcher, monitor all built (S8-1..5) | **~0h45m** |
| A3 Reasoning depth | **L1** | classify → DAG plan → execute → critic replan (S5) | 0h |
| A4 Cognitive architecture | **L1** | single planner + critic split | 0h |
| A5 World model | **L1→L2** | process/window snapshot + change detection + planner context (S7 A1–A3); no project inference | **~0h25m** |
| A6 Value alignment | **L0** | literal instruction-following; risk tiers + HITL for T2/T3 | 0h |
| A7 Assurance | **L1** | unit + property/fuzz tests; drift detection (S7 Half B) + skill demotion (S8-5) + shadow-eval/fixed-criteria review (S9) now feed it; no machine-checked proofs | **~0h20m** |
| A8 Identity & rapport | **L1** | semantic memory (S6); no persistent persona or relationship model | 0h |

## Session time log

Derived from `git log` commit timestamps (the most honest source available —
not a stopwatch). This **undercounts** true effort: gaps *before* a block's
first commit (thinking, drafting, multiple tool calls) aren't visible, and
two long idle gaps (5h23m, 8h50m — clearly breaks, not work) are excluded
from the totals below.

| Block | Elapsed | Axis / track |
|---|---|---|
| S4 completion (broker, budgets, Windows Sandbox, snapshot/restore, live-verify script + result) | ~1h50m | S-track (foundational, pre-axis) |
| S6 (event bus incr. 1–2, P2-4 contracts, P2-5 confirm channel, semantic + procedural memory) | ~1h35m | S-track |
| S7 A1 + A2 (env sampler, read API) | ~11m | **A5** |
| S7 A3 (planner context wiring) | ~4m | **A5** |
| S7 Half B (drift detection) | ~7m | **A7** (monitoring signal) |
| External benchmark manifest format + `by_source` scoring | ~7m | S-track |
| S8-1 + S8-2 (typed-slot abstraction, skill registry) | ~9m | **A2** |
| `OPEN_ENDED_ROADMAP.md` authored + S9/Beyond-S9 sections added to `ROADMAP.md` | ~16m | meta / planning |
| S8-3..5 + S9-1..4 combined (replay-validation, matcher, monitor, versioned change store, proposer, shadow-eval, review) — not separable from commit timestamps alone | ~13m | **A2** (S8 share) + **A7** (S9 share, self-tuning under fixed criteria) |
| `third_party.json` real external task + `%ENV_VAR%` loader support | ~0m (same commit burst) | S-track |
| Repo hygiene (`docs/`, `scripts/` reorg) | ~12m | meta |

**Total active this session (breaks excluded): ~4h32m.** Roughly 1h30m of
that is directly attributable to an A-axis (A2 ~45m, A5 ~25m, A7 ~20m,
speculatively split further above); the remainder is S1–S9 foundational work
and planning/meta, which this doc explicitly treats as a separate,
already-milestone-tracked layer beneath the axes.

---

## A1 — Temporal horizon
*How far into the future a single intent reaches.*

| L | Capability |
|---|---|
| L0 | one command, one effect |
| L1 | a multi-step plan for one request *(now)* |
| L2 | a standing goal with a TTL and an owner ("keep Downloads sorted") |
| L3 | stewardship of a domain, re-chartered by the control plane on a cadence |
| L4 | the system proposes goals; the human ratifies or rejects |

**Invariant:** every standing goal has an owner, a TTL, and a review cadence.
The system never acts on a goal the human did not ratify, and A5 checks each
standing goal's preconditions still hold before every run.
**First increment (S10):** persistent `goals` table, control-plane
re-confirmation prompt, hard expiry; standing goals run through the same
autonomous path S6 built (T2/T3 still denied without a human).

## A2 — Capability genesis
*Where new capabilities come from.*

| L | Capability |
|---|---|
| L0 | hand-written capabilities only |
| L1 | learned recipes, registered at T1 *(S6)* |
| L2 | parameterized skills with typed slots *(S8, in progress)* |
| L3 | the system synthesizes a single-purpose tool, validates it in the S4 overlay, registers it at T1 |
| L4 | synthesized tools compose other synthesized tools |
| L5 | capability-gap self-diagnosis: "I can't do X; here is the tool I would need" |

**Invariant:** nothing self-authored runs above **T1** without human review.
Every synthesized artifact carries provenance and a kill switch. Synthesis
and validation happen only in the verified S4 container overlay, never on the
live system.
**First increment (S11):** extend S8's pipeline so a *failed* capability-gap
(no recipe, no skill, drift-retired) can trigger a bounded tool-synthesis
attempt whose output is a candidate skill — same lifecycle, same gates.

## A3 — Reasoning depth
*How much the system thinks before it acts.*

| L | Capability |
|---|---|
| L0 | classify and execute |
| L1 | decompose into a dependency-aware DAG *(S5)* |
| L2 | prune plans by predicted outcome before committing |
| L3 | compare plans counterfactually ("A leaves the file open, B doesn't") |
| L4 | form and test hypotheses about *why* a step failed, not just retry |

**Invariant:** predictions are advisory. S1 postcondition verification is
always ground truth. A calibration monitor tracks predicted-vs-actual per
capability and disables predictive planning for one whose calibration drifts.
**First increment (S13):** a lightweight outcome model over `capability_outcomes`
(S7 Half B) that annotates each candidate plan step with a success
probability; the planner prefers the higher-probability branch, nothing more.

## A4 — Cognitive architecture
*How many minds, and how they relate.*

| L | Capability |
|---|---|
| L0 | one pipeline |
| L1 | planner + critic split *(S5)* |
| L2 | ephemeral specialist sub-agents per task (researcher / coder / verifier) |
| L3 | persistent specialists with their own scoped memory |
| L4 | the society reorganizes its own structure for a task |

**Invariant:** recursive containment — a child agent's capability grant is
always a **subset** of its parent's, never a superset. One budget shared
across the whole society. Single-writer arbitration so two agents cannot race
a T2 action. The society is always auditable as a tree.
**First increment (S12):** the critic becomes a real sub-agent with its own
context window and a read-only (T0) grant; prove the subset-grant and shared-
budget mechanics on that one split before adding more roles.

## A5 — World model
*How much of the user's situation the system holds.*

| L | Capability |
|---|---|
| L0 | nothing |
| L1 | process + foreground-window snapshot *(S7 A1)* |
| L2 | change detection over a window *(S7 A2)*; project / task inference |
| L3 | predictive ("this build will fail because dependency X is stale") |
| L4 | cross-device model of the machines the user owns |
| L5 | a model of the user's intent landscape — projects, deadlines, people |

**Invariant:** digital context only — no camera or ambient microphone without
its own explicit governance section. Per-device capability tiers (a T2 on the
laptop may be T3 on a server). The model is inspectable and correctable by
the user at any time.
**First increment:** S7 A2 already ships `changes_since()`; next is grouping
recent activity into inferred "projects" the planner can name.

## A6 — Value alignment  *(pace-setter — must keep up with A1–A5)*
*Acting in the user's interest, not just on their words.*

| L | Capability |
|---|---|
| L0 | do exactly what was said *(now)* |
| L1 | rank the *permitted* options by inferred preference |
| L2 | "I think you want X — confirm?" before acting on an inference |
| L3 | act proactively, but only within a value model the user has ratified |
| L4 | principled refusal with explanation ("I won't do that because…") |

**Invariant:** the learned preference model can only **rank within** the set
the policy already permits — never expand it. It is versioned and
rollback-able like S9's heuristics. Every proactive action is explainable and
logged. Irreversible (T3) actions always keep the human in the loop,
regardless of how confident the value model is.
**First increment (S15):** a preference store that reorders candidate plans
(e.g. "prefers UIA over pixel matching", "prefers dark mode") with zero
authority to add a plan the validator would not already allow.

## A7 — Assurance  *(gate — no other axis advances a level until this covers it)*
*From "we tested it" to "we proved it."*

| L | Capability |
|---|---|
| L0 | unit tests |
| L1 | property + fuzz tests over the trusted base *(partly now)* |
| L2 | machine-checked proof: no cognition-plane output can promote its own tier, and no plan bypasses `validate_steps()` |
| L3 | runtime attestation that the containment kernel is the unmodified, proven version |
| L4 | proof obligations auto-generated for each new capability before it can register |

**Invariant:** this axis has no capability risk of its own — it is pure risk
reduction, and it is what makes every other axis defensible rather than
reckless.
**First increment (S16):** extract the trusted base (`validator.py`,
`capability_broker.py`, the policy engine) into a small kernel with an
explicit spec, and machine-check the two core properties above.

## A8 — Identity & rapport
*Continuity of self across a long relationship — the JARVIS quality.*

| L | Capability |
|---|---|
| L0 | stateless responder |
| L1 | semantic memory of past interactions *(S6)* |
| L2 | persistent preferences and history the user can inspect / export / delete |
| L3 | a consistent voice and persona |
| L4 | a relationship model — knows the user's patterns, projects, and people |

**Invariant:** all of it is the user's data — local, inspectable, exportable,
deletable. The persona never manipulates. Memory is never used against the
user's interest, and the user can see exactly what is remembered and why.

---

## Recommended next levels (in order)

1. **A7 → L2** — the machine-checked containment kernel. Highest value: it
   converts the thesis claim from "tested" to "proven", and it is the gate
   every other axis waits on.
2. **A1 → L2** — persistent standing goals (S10). The most visible capability
   jump; reuses the S6 autonomous path unchanged.
3. **A6 → L1** — preference ranking (S15 first increment). Small, and it is
   the axis that keeps A1–A5 honest.
4. **A2 → L2** — finish S8 (skill learning). Already in progress.

A3/A4/A5-L3+ and anything at L4+ on any axis are research-scale — name them
as future work, build them only after A7 has caught up.
