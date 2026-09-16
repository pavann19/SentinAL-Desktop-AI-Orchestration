# SentinAL — Secure AI Desktop Orchestration

A voice-controlled desktop agent that executes natural-language instructions on a Windows
machine, with a deterministic security layer that validates **every** action before it runs
and verifies the action actually happened afterward.

**Positioning:** Gatekeeper decides whether a prompt may reach a model; SentinAL decides
whether an agent's proposed OS action may execute, and verifies that it worked.

> **Status: research prototype / early MVP.** The security boundary and intent routing are
> well tested (990+ automated tests, 87%+ coverage, a 66-test adversarial fuzz suite at 100%
> block rate). End-to-end task success on a real machine, independently OS-state-verified, is
> **96.7%** (95% CI 91.7–98.7%, n=120) — good for supervised daily use, not yet unattended.
> Full write-up: [`docs/reports/`](docs/reports/) and [`thesis/`](thesis/).

## Why

An agent with OS execution privileges can't rely on a language model's good behaviour for
safety. SentinAL treats the LLM as untrusted and enforces security *outside* it, then
independently checks OS state afterward rather than trusting that a call returned cleanly.
Full containment design: [`CONTAINMENT_ARCHITECTURE.md`](CONTAINMENT_ARCHITECTURE.md).

## Requirements

Windows 10/11 (the execution layer uses `win32gui`/`pyautogui`/UIA — not portable as written) ·
Python 3.11+ · [Ollama](https://ollama.com/) for local/private LLM routing · Node 18+ only for
the optional Electron/React HUD. API keys (Groq, Deepgram, Picovoice, Tavily) are all optional
— features degrade gracefully without them, and `SENTINAL_OFFLINE=1` (below) needs none at all.

## Install & run

```bash
git clone <your-repo-url> sentinal && cd sentinal
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
ollama pull llama3.2                 # local/private model
copy .env.example .env               # then edit — every key is documented in the template
python main.py                       # backend on http://127.0.0.1:8000
```

First run generates a bearer token into `.sentinal_token` (gitignored). Key `.env` settings:
`SENTINAL_HOST` (keep on `127.0.0.1`), `LLM_PROVIDER` (`groq` cloud / `local` Ollama-only),
`SENTINAL_DEBUG` (leave `false`).

**No keys, no network, no voice** — `SENTINAL_OFFLINE=1 python scripts/offline_repl.py` runs
the real pipeline through a text REPL: skips the cloud LLM entirely, uses local Ollama if
reachable, else a deterministic stub — nothing to install to try it.

## API

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health`, `/api/health` | none | Liveness probe |
| `POST /api/command` | bearer | Execute a natural-language command |
| `GET /api/tasks[/{id}]` | bearer | Poll a background task's status |
| `GET /api/logs` | bearer | Last 10 diagnostic log entries |
| `WS /ws/agent`, `/ws/telemetry` | — | Streaming pipeline state / live telemetry |

```bash
curl -X POST http://127.0.0.1:8000/api/command \
  -H "Authorization: Bearer $(cat .sentinal_token)" -H "Content-Type: application/json" \
  -d '{"prompt": "open notepad"}'
```

`/api/command` executes real OS actions — the token is a real credential, and CORS does not
protect it (CORS is browser-enforced; scripts bypass it entirely). Keep `SENTINAL_HOST` on
loopback unless you know you want it published to the network.

## Security model

**Intent allowlist** (fixed set, else rejected outright) → **filesystem sandbox**
(`System32`, Windows core dirs, `..` traversal, bare drives blocked) → **keyword filtering**
(destructive verbs, word-boundary matched) → **human-in-the-loop** (deletion needs explicit
confirmation no injected instruction can bypass) → **postcondition verification** (real OS
state checked after execution — a clean return that didn't actually happen is a failure, not
a success). 100% block rate, 66-test adversarial fuzz suite. Full model, capability tiers, and
the containment roadmap: [`CONTAINMENT_ARCHITECTURE.md`](CONTAINMENT_ARCHITECTURE.md).

## Evaluation

| Metric | Result |
|---|---|
| Intent accuracy — real-world phrasing (Amazon MASSIVE) | **92.33%** |
| Intent accuracy — out-of-distribution (synthetic) | **83.68%** |
| Fast-path resolution (no LLM call) | **88.45%** |
| **End-to-end task success (real machine, OS-verified)** | **96.7%** (95% CI 91.7–98.7%, n=120) |
| Security fuzzing block rate | **100%** (66/66) |
| Test suite | 990 passing, 87.50% coverage |

**Reproduce with zero API keys / network:**

```bash
python scripts/reproduce_router_accuracy.py           # router-only, full dataset, exhaustive
python -m eval.run_eval                                # task-success harness
```

The full end-to-end number needs a real Windows desktop and live LLM access —
`benchmarks/run_benchmark.py --repeat 3`. Methodology (independent OS-state verification,
Wilson intervals, no score-inflating retries, every report pinned to its git commit) is in
[`docs/reports/`](docs/reports/).

## Testing

`pytest tests/ -v --deselect tests/test_stress.py` (CI runs ruff, mypy, and this on every push).

## Known limitations

- **6 of 19 intents have no independent postcondition check** (read-only/conversational, or
  leave no durable OS-state fact — e.g. `ConversationalIntent`, `DictationIntent`).
- **Windows-only.**
- **GUI resolution** falls back to pixel-matching (fragile to DPI/multi-monitor changes) only
  when UI Automation can't resolve a label — not the default path, but not eliminated.
- **The end-to-end benchmark is self-authored**; `benchmarks/external/` adds a pluggable
  manifest format for third-party tasks, still thin.
- **No installer/package** — install is manual.

## Project layout

```
agentic_core/       Router, planner, validator, executor, memory, world model
capabilities/       Pluggable actions (system, developer, web)
config/             Security policy + tiers (single auditable source)
interfaces/         Voice I/O (wake word, STT, TTS) and UI bridge
eval/, benchmarks/  Reproducible accuracy + task-success evaluation
scripts/            Standalone verification/reproduction/offline-mode entry points
tests/              990+ automated tests
docs/                Planning docs, point-in-time reports, dev history
thesis/             Full design/evaluation write-up and diagrams
```

## License

[MIT](LICENSE) © 2026 Gannoju Pavan Kumar
