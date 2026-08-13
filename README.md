# SentinAL — Secure AI Desktop Orchestration

A voice-controlled desktop agent that executes natural-language instructions on a Windows
machine, with a deterministic security and privacy layer that validates **every** action
before it runs.

The design premise: an agent with OS execution privileges cannot rely on a language model's
good behaviour for safety. SentinAL treats the LLM as an untrusted component and enforces
security outside it — through capability allowlists, filesystem sandboxing, keyword
filtering, and human-in-the-loop confirmation gates that the model cannot talk its way past.

> **Project status: research prototype / early MVP.** The security boundary and intent
> routing are well tested (850+ automated tests, 87%+ coverage, 66-test adversarial fuzz
> suite at a 100% block rate). End-to-end task success, measured with an independent,
> statistically-scored benchmark (OS-state verification, not the pipeline's own self-report;
> 95% Wilson confidence interval), is **94.2%** (95% CI 88.4–97.2%, n=120: 40 tasks × 3 runs)
> — good enough for supervised daily use, not yet unattended. See [Evaluation](#evaluation)
> for the full methodology and [Known Limitations](#known-limitations) before deploying.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
- [API](#api)
- [Security Model](#security-model)
- [Evaluation](#evaluation)
- [Reproducing the Evaluation](#reproducing-the-evaluation)
- [Testing](#testing)
- [Known Limitations](#known-limitations)
- [Project Layout](#project-layout)
- [License](#license)

---

## Features

- **Hybrid intent router** — a keyword fast-path, then a trained classifier over local
  sentence embeddings, then an LLM fallback only for genuinely ambiguous requests.
  94.2% of held-out queries resolve locally in under 50 ms with no model call at all.
- **Content-aware privacy routing** — prompts containing PII, credentials, or sensitive
  filesystem paths are forced onto a local on-device model and never reach a cloud API.
- **Deterministic validation pipeline** — allowlist → target check → filesystem sandbox →
  keyword filter → human confirmation, enforced independently of the LLM.
- **Execute-observe-replan loop** — verifies that an action actually achieved its intended
  effect (process/window/vision checks) rather than trusting that the call returned cleanly.
- **OpenTelemetry tracing** — per-stage latency and parameter state for every request.

## Architecture

```
Voice input → STT → NLP correction
     → Hybrid intent router  (keyword → classifier / cosine embeddings → LLM fallback)
     → Privacy router        (PII / credential / path detection → forces local model)
     → Validation pipeline   (allowlist → sandbox → keyword filter → HITL gate)
     → Execution             (capability dispatch)
     → Postcondition observer (did it actually work?)
     → TTS response
```

Diagrams for each stage are in [`thesis/figures/`](thesis/figures/). The full design
rationale is documented in [`thesis/THESIS_DRAFT_v1.md`](thesis/THESIS_DRAFT_v1.md).

## Requirements

- **Windows 10/11** — the execution layer uses Windows-specific APIs (`tasklist`,
  `win32gui`, `pyautogui`). Other platforms are not supported (see
  [Known Limitations](#known-limitations)).
- **Python 3.11+** (developed and tested on 3.11 and 3.13)
- **Node.js 18+** — only if you want the Electron/React HUD
- **[Ollama](https://ollama.com/)** — required for local/private LLM routing
- API keys (all optional, features degrade gracefully without them): Groq (cloud LLM),
  Deepgram (STT), Picovoice (wake word), Tavily (web search)

## Installation

```bash
git clone <your-repo-url> sentinal
cd sentinal
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Pull a local model for private routing:

```bash
ollama pull llama3.2
```

Optional — the desktop HUD:

```bash
cd sentinal-ui && npm install
```

## Configuration

```bash
copy .env.example .env
```

Then edit `.env`. Every key is documented in the template; the ones that matter most:

| Key | Default | Purpose |
|---|---|---|
| `SENTINAL_HOST` | `127.0.0.1` | **Keep on loopback.** See [Security Model](#security-model). |
| `SENTINAL_PORT` | `8000` | Backend API port |
| `SENTINAL_API_TOKEN` | *(auto-generated)* | Bearer token for the REST API |
| `LLM_PROVIDER` | `groq` | `groq` for cloud, `local` for Ollama-only |
| `SENTINAL_DEBUG` | `false` | **Leave `false`** — `true` enables diagnostic bypasses |

`.env` is gitignored. Never commit real keys.

## Running

```bash
python main.py
```

The backend starts on `http://127.0.0.1:8000`. On first run it generates a REST API token
and writes it to `.sentinal_token` (also gitignored), printing a notice to the console.

With the HUD:

```bash
cd sentinal-ui && npm run dev
```

## API

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health`, `/api/health` | none | Liveness probe |
| `POST /api/command` | **bearer token** | Execute a natural-language command |
| `GET /api/logs` | **bearer token** | Last 10 diagnostic log entries |
| `WS /ws/agent` | — | Primary UI channel (streaming pipeline state) |
| `WS /ws/telemetry` | — | Live telemetry feed |

```bash
curl -X POST http://127.0.0.1:8000/api/command \
  -H "Authorization: Bearer $(cat .sentinal_token)" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "open notepad"}'
```

## Security Model

SentinAL assumes the language model **will** eventually be compromised — by direct prompt
injection, by malicious content it reads, or simply by hallucinating — and places the
security boundary outside it:

1. **Intent allowlist** — 20 permitted intents, hardcoded. Anything else is rejected
   categorically rather than interpreted.
2. **Filesystem sandbox** — blocks `System32`, Windows core directories, `..` traversal,
   and bare drive roots (`C:\`, `D:\`).
3. **Keyword filtering** — destructive verbs matched on word boundaries, not substrings.
4. **Human-in-the-loop** — file deletion requires explicit user confirmation. An injected
   instruction cannot programmatically bypass a human.

Verified by a 66-test adversarial fuzzing suite (shell injection, path traversal, forbidden
intents, 1,000 random-noise inputs) at a 100% block rate.

**Operational security notes — read before deploying:**

- `/api/command` executes **real OS actions**. It requires a bearer token, but CORS alone
  never protected it: CORS is browser-enforced, so scripts and other local processes bypass
  it entirely. Treat the token as a real credential.
- The server binds to **loopback only** by default. Overriding `SENTINAL_HOST` to `0.0.0.0`
  publishes command execution to every network interface — only do this on a trusted
  network with a strong token set.
- `SENTINAL_DEBUG=true` enables diagnostic bypasses. Never enable it in a shared or
  production environment.

## Evaluation

All figures below are reproducible from committed artifacts (see the next section).

| Metric | Result |
|---|---|
| Intent accuracy — held-out test split | **99.33%** (448/451) |
| Intent accuracy — out-of-distribution set | **92.00%** (138/150) |
| Zero-shot baseline (pre-classifier) | 54.55% test / 70.67% OOD |
| Fast-path resolution rate (no LLM call) | **94.24%** test / **84.67%** OOD |
| Task success — 19 CI-safe benchmark tasks | **84.2%** (16/19) |
| **End-to-end task success — real-machine benchmark** | **94.2%** (95% CI 88.4–97.2%, 109/120) |
| Security fuzzing block rate | **100%** (66/66) |
| Median end-to-end latency | 101.5 ms (validation adds 0.06 ms) |
| Test suite | 856 passing (CI-gated scope), 87.08% coverage |

**On the end-to-end number.** `benchmarks/run_benchmark.py` drives the real pipeline against
a real Windows desktop across 40 tasks spanning application launch, web navigation, file
operations, process management, system utilities, multi-step requests, safety-blocking
prompts, conversation, and known-unimplemented-capability refusal — each repeated 3 times
(n=120). Verification is independent of the pipeline: pass/fail comes from querying actual
OS state (the process table, filesystem, window list), never from the pipeline's own success
report, and a 95% Wilson confidence interval is reported alongside the point estimate rather
than a bare percentage. Full methodology, the task suite, and every commit's provenance are
in `benchmarks/`; see [Reproducing the Evaluation](#reproducing-the-evaluation).

## Reproducing the Evaluation

```bash
# Intent accuracy: trained classifier vs. zero-shot baseline
python -m eval.finetune_classifier --run-id myrun

# Router-only accuracy across the full dataset
python -m eval.measure_intent_accuracy --mode router-only --run-id myrun

# Full-pipeline sampled accuracy (hits live LLM/network)
python -m eval.measure_intent_accuracy --mode full-pipeline --sample-size 40 --sample-seed 7 --run-id myrun

# Task-success harness
python -m eval.run_eval

# End-to-end benchmark: drives the real pipeline on a real desktop (Windows).
# Opens/closes real applications and browser tabs — avoid using the machine while it runs.
python benchmarks/run_benchmark.py --repeat 3
```

Results are written to `_evidence/` and `benchmarks/results/`, alongside the committed runs
backing the table above. Splits are seeded and the exact indices are committed, so accuracy
figures reproduce byte-for-byte. Every benchmark report records its git commit and a
dirty-working-tree flag, so a result is only citable alongside the exact code that produced
it.

## Testing

```bash
pytest tests/ -v --deselect tests/test_stress.py   # full suite
pytest tests/test_security_fuzz.py -v              # security only
pytest tests/test_stress.py -v --timeout=120       # stress (run separately)
```

CI (`.github/workflows/ci.yml`) runs ruff, mypy, and the test suite on every push.

## Known Limitations

Stated plainly, because they matter for anyone evaluating this:

- **6 of 19 intents have live postcondition verification**; the rest execute without an
  independent check that the action actually took effect, beyond whatever `execute_pipeline()`
  itself reports. Two of the unverified intents (dependency install, arbitrary code execution)
  launch detached, long-running processes that are inherently hard to verify synchronously —
  a real design constraint, not an oversight.
- **Windows-only.** The execution layer is not portable as written.
- **GUI automation is pixel-based** (`pyautogui`), so it breaks on resolution changes, DPI
  scaling, multi-monitor setups, and theme changes. Migration to UI Automation trees is
  planned but not done.
- **The trained classifier was pickled under scikit-learn 1.6.1.** A fresh install with a
  newer scikit-learn emits a version warning; retraining is recommended.
- **The end-to-end benchmark is self-authored** (`benchmarks/tasks.py`), not drawn from an
  external, independently-curated task set, and all measurements come from a single Windows
  machine. The methodology (independent OS-state verification, confidence intervals, no
  score-inflating retries) is designed to be defensible regardless, but a self-authored task
  suite can still under-sample failure modes an external benchmark would catch.
- **No Docker image or installable package yet** — installation is manual.

## Project Layout

```
agentic_core/       Router, processor, validator, executor, tracing
capabilities/       Pluggable actions (system, developer, web)
system_services/    Privacy router, system state
config/             All security policy constants (single auditable file)
interfaces/         Voice I/O (wake word, STT, TTS) and UI bridge
eval/               Reproducible evaluation harnesses and datasets
tests/              441 automated tests
thesis/             Full design/evaluation write-up and diagrams
_evidence/          Committed measurement artifacts
```

## License

[MIT](LICENSE) © 2026 Gannoju Pavan Kumar
