# SentinAL v9.0 → Agentic OS: Gap Analysis, Roadmap & Thesis Plan

**Date:** 2026-07-10 · **Basis:** direct code audit of the reunified v9.0 system (247/247 tests green)
**Purpose:** (1) engineering roadmap from "voice command assistant" to "agentic OS"; (2) an industry-standard thesis structure suitable for German MSc admissions.

---

# PART A — Where the system is today (honest assessment)

## A.1 What v9.0 actually is

A **reactive, single-turn command pipeline**:

```
wake word → STT (Deepgram/whisper) → NLP correction → intent classification
  (semantic router: embedding cosine over 15 intents + LLM extraction fallback)
→ validator (allowlist + sandbox path check + HITL flag) → linear executor
→ 33 registered capabilities → TTS response
```

Strengths worth keeping (these are genuinely good for a BTech project):
- **Hybrid routing** — deterministic fast-path for common commands, embedding router (`agentic_core/router.py`), LLM extraction only when needed. This is a real latency/cost architecture, not a demo.
- **Privacy router** (`system_services/privacy_router.py`) — per-prompt local-vs-cloud LLM routing based on PII/sensitive-path detection. This is a *differentiator*; most published agent systems don't have it.
- **Security-first execution** — intent allowlist (`validate_steps`), filesystem sandbox (`validate_sandbox`), command sanitizer (`_sanitize_shell_cmd`, `_is_safe_command`), CodeAct script validation (`_validate_script`), security fuzz test suite (66 tests), audit logging.
- **Engineering hygiene** — 247 unit/integration/fuzz/stress tests, CI pipeline, coverage gates, capability registry in SQLite.

## A.2 The ten gaps between v9.0 and an "Agentic OS"

An agentic OS means: *the system pursues goals, perceives the machine's state, plans, acts, observes outcomes, recovers from failure, and acts proactively under a governance policy* — instead of executing one parsed command per utterance.

| # | Gap | Evidence in code | What an agentic OS needs |
|---|-----|------------------|--------------------------|
| 1 | **No closed perception–action loop.** Executor fires and forgets. | `execute_pipeline()` in `agentic_core/executor.py` walks validated steps linearly; `capabilities/system/vision_module.py` (`verify_screen_state`) exists but is barely wired in. | ReAct/observe-act loop: after every action, observe (screenshot / UIA tree / process state), compare to expected state, replan on mismatch. |
| 2 | **No planner.** One LLM shot produces the step list. | `processor.extract_intent()` returns a flat JSON array; no decomposition, no dependencies, no retry policy. | Hierarchical planner: goal → sub-goal DAG → capability calls, with reflection ("did that work?") and bounded retries. LangGraph is already a dependency — use it as the state machine. |
| 3 | **Memory is a log, not knowledge.** | `MemoryManager` (memory_hook.py) stores URL templates, cached paths, and an interaction log. `get_context_for_prompt()` returns recent rows. | Three-tier memory: episodic (what happened), semantic (facts about the user/machine, vector-indexed), procedural (learned task recipes). Retrieval-augmented planning. |
| 4 | **Scheduler is a queue, not autonomy.** | `TaskManager` (scheduler.py) = FIFO queue, capacity 20, `start()` only. | Event-driven autonomy: file-system watchers, calendar/notification hooks, time triggers; background goals ("keep Downloads organized") executing under policy without a wake word. |
| 5 | **Capabilities are hardcoded functions.** | `capability_registry.py` seeds 33 rows but dispatch is static imports. | Tool contracts (schema, permissions, risk tier, cost) + dynamic discovery — MCP (Model Context Protocol) is the industry standard to adopt here. |
| 6 | **Flat security model.** | One `requires_confirmation` flag; allowlist is binary. | Risk-tiered policy engine: per-capability grants, per-resource scopes (which folders, which apps), taint tracking of LLM-derived arguments (prompt-injection defense), full provenance chain in audit log. Your separate `AI_Governance_Project` / `sentinal-ecosystem` work is exactly this — merge the ideas. |
| 7 | **Single-agent monolith.** | One pipeline; the LLM that plans is the LLM that executes. | Planner / Executor / Critic separation: a cheap critic model verifies outcomes and vetoes unsafe plans; enables self-correction loops. |
| 8 | **Shallow OS integration.** | GUI automation via `pyautogui` (pixel/coordinate based, `gui_resolver.py` heuristics). | Windows UI Automation (UIA) accessibility tree: semantic element targeting ("the Save button"), robust to resolution/theme; plus Windows service mode, session events, COM/WinRT APIs. |
| 9 | **Minimal observability.** | `telemetry.py` is 1.3KB; logs are prints + two files. | OpenTelemetry traces per task (plan → steps → tool calls → outcome), token/cost accounting, structured failure taxonomy. This also generates your thesis evaluation data for free. |
| 10 | **No benchmark evaluation.** | Tests verify components; nothing measures *task success rate*. | Evaluate on a published benchmark (Windows Agent Arena, OSWorld subset) + a scripted in-house task suite with success criteria. This is the single biggest upgrade for thesis credibility. |

## A.3 Roadmap: five phases to "SentinAL OS v10+"

**Phase 1 — Close the loop (4–6 weeks).**
Rework `execute_pipeline` into an observe–act cycle: every step returns an observation object; a verifier (vision_module + process/window state) confirms postconditions; failures trigger one bounded replan. Add OpenTelemetry tracing end-to-end. *Deliverable: task success rate becomes measurable.*

**Phase 2 — Cognitive layer (6–8 weeks).**
LangGraph planner graph (plan → act → observe → reflect), three-tier memory with a local vector store (you already run Qdrant elsewhere), user-preference model. Migrate capabilities to MCP tool contracts with schemas + risk tiers.

**Phase 3 — Proactive autonomy (6–8 weeks).**
Event bus (watchdog file events, calendar, notifications, timers) feeding the planner; background goals with budgets; policy engine with risk-tiered HITL (auto / notify / confirm / forbid). Port RBAC + policy JSON schemas from your AI_Governance project.

**Phase 4 — OS-native depth (8+ weeks).**
Replace pyautogui with Windows UIA tree navigation; run the core as a Windows service with the Electron HUD as a thin client; multi-agent split (planner LLM, executor, small critic); taint-tracking of untrusted content (web pages, file contents) through the prompt chain.

**Phase 5 — Evaluation & governance (parallel, ongoing).**
Windows Agent Arena / OSWorld-subset runs; in-house 50-task benchmark with success criteria; red-team suite extending `test_security_fuzz.py` to prompt-injection scenarios; ablations (privacy router on/off, local vs cloud, fast-path vs LLM).

---

# PART B — Thesis report at industry/academic standard (German MSc admissions)

## B.1 Framing: report → thesis

What German admissions committees (TU9 and similar) look for is **scientific method**, not feature lists: a precise research question, positioning against literature, a defensible methodology, quantitative evaluation, and honest limitations. Your submitted BTech documentation is a *project report*; the thesis rewrite must be organized around **claims and evidence**.

**Suggested title:**
*"SentinAL: A Security-Governed, Privacy-Routing Voice Agent for Desktop Operating Systems — Design, Implementation, and Evaluation"*

**Research questions (pick 3, these fit the existing system):**
- **RQ1:** Can a hybrid intent architecture (deterministic fast-path + embedding router + LLM fallback) match LLM-only intent parsing in accuracy while significantly reducing latency and cloud dependency?
- **RQ2:** Can per-prompt privacy routing (local vs cloud LLM selection based on content sensitivity) preserve task success while keeping sensitive prompts on-device?
- **RQ3:** To what extent does a layered validation pipeline (allowlist → sandbox → HITL) block adversarial/injected commands without degrading benign task success? (evidence base: the 66-test security fuzz suite)

## B.2 Structure (60–80 pages, IEEE/ACM citation style)

1. **Abstract** (+ optional German *Kurzfassung* — a nice touch for German committees)
2. **Introduction** — problem, RQs, contributions list (bullet, verifiable), thesis outline
3. **Background & Related Work** — LLM tool-use agents; computer-use agents (OSWorld, Windows Agent Arena, Microsoft UFO/UFO², Anthropic computer use); voice assistants (commercial + academic); LLM agent security (prompt injection, tool misuse literature). *This chapter is what most project reports lack — invest ~12 pages.*
4. **Requirements & Threat Model** — user stories, non-functional requirements (latency, privacy, safety), explicit attacker model (malicious transcript, injected web content, LLM hallucination as a fault class)
5. **System Design** — architecture diagram, the three routing layers, privacy router decision function, validator pipeline, capability registry; *design rationale with alternatives considered*
6. **Implementation** — 24 modules, 15 intents, 33 capabilities, Electron/React HUD, WebSocket protocol; engineering practices (247 tests, CI, coverage)
7. **Evaluation** — the make-or-break chapter:
   - Intent routing accuracy on a labeled utterance set (vs LLM-only baseline)
   - End-to-end latency distributions per routing path
   - Task success rate on a scripted 30–50 task suite (define success criteria per task)
   - Security: fuzz/injection block rate, false-block rate on benign commands
   - Privacy: % prompts kept local, task-success delta with router on/off
8. **Discussion & Limitations** — single-user, Windows-only, pyautogui fragility, evaluation scale; be brutally honest — German reviewers reward it
9. **Conclusion & Future Work** — Part A of this document *is* the future-work chapter
10. **Appendices** — reproducibility (exact versions, seeds, hardware), full test matrix, ethics note (mic data, API keys, user consent)

## B.3 Concrete upgrades that raise it to "industry standard"

| Upgrade | Effort | Why it matters |
|---|---|---|
| Run even a 10-task subset of Windows Agent Arena and report numbers | Medium | Puts you on the same axis as published systems; committees recognize it |
| Labeled intent dataset (300–500 utterances) + confusion matrix | Low | Turns "it works" into measured accuracy |
| Latency CDF plots per routing path | Low | You already log timestamps; harvest them |
| Ablation table (fast-path off / privacy router off / cloud-only) | Medium | Demonstrates scientific method |
| Cite & compare against UFO², OSWorld, Anthropic computer-use | Low | Related-work credibility |
| Reproducibility appendix + public GitHub repo with CI badge | Low | The repo IS evidence — 247 green tests + CI pipeline reads as engineering maturity |
| Threat model diagram + mapping of each mitigation to a test | Medium | Security story becomes verifiable, not asserted |

## B.4 Admissions-specific notes

- Write in **English** (standard for German MSc programs); the optional German Kurzfassung signals effort.
- In your SoP/uploads, present it as: *"designed, implemented, and quantitatively evaluated a security-governed LLM agent system (X tests, CI, benchmark results)"* — metrics, not adjectives.
- Keep the PDF ~60–80 pages + appendices; over-length project dumps read poorly.
- If a program asks for a "scientific abstract" of prior work, Chapter 7's numbers are what you quote.

---

*Generated during the reunification session; see MERGE_LOG.md for the state of the codebase this analysis is based on.*
