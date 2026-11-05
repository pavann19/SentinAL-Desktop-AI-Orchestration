# SentinAL — Secure AI Desktop Orchestration

SentinAL is a voice- and text-controlled Windows desktop agent with a deterministic
control plane. Proposed actions pass through policy validation before execution;
where a durable postcondition exists, the system checks the resulting OS state.

The implementation combines hybrid intent routing, privacy-aware LLM selection,
bounded planning, capability controls, and postcondition verification. Optional memory
and learning features remain disabled by default.

> **Status: research prototype / early MVP.** The latest published CI run passed
> 1,333 tests with 2 skipped and 86.75% coverage. The security suite passed all 66 cases.
> A separate local, self-authored desktop benchmark reported **96.7%** task success
> (116/120; 95% CI 91.7–98.7%). That result is not a CI measurement or evidence of
> unattended reliability. [CI results](https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration/actions/runs/37445301449).

## Documentation

| Resource | Scope |
|---|---|
| [Thesis](thesis/Thesis.md) | Revised technical thesis with PDF, Word, and evidence inventory |
| [Historical record](historical-record/README.md) | Earlier thesis documents, submission, and supporting figures |
| [Goals and decisions](docs/DECISIONS.md) | Implementation decisions, feature status, and open work |
| [Containment architecture](CONTAINMENT_ARCHITECTURE.md) | Dated architectural audit and containment design |

Historical documents retain their original results and describe earlier project states.
Generated evaluation reports and model artifacts remain outside the public repository.

## Why

An agent with OS execution privileges can't rely on a language model's good behaviour for
safety. SentinAL treats the LLM as untrusted and enforces security *outside* it, then
independently checks OS state afterward rather than trusting that a call returned cleanly.
Full containment design: [`CONTAINMENT_ARCHITECTURE.md`](CONTAINMENT_ARCHITECTURE.md).

## Requirements

Windows 10/11 (the execution layer uses `win32gui`/`pyautogui`/UIA — not portable as written) ·
Python 3.11+ · [Ollama](https://ollama.com/) for local/private LLM routing · Node 18+ only for
the optional Electron/React HUD. API keys (Groq, Deepgram, Picovoice, Tavily) are all optional
— features degrade gracefully without them, and `SENTINAL_OFFLINE=1` (below) needs no cloud keys.

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

**No cloud keys, no internet API, no voice** — offline mode runs the real pipeline through
a text REPL, skips the cloud LLM entirely, probes local Ollama on `localhost:11434`, and
falls back to a deterministic stub if Ollama is unreachable. Install the Python
dependencies first, then run:

```powershell
$env:SENTINAL_OFFLINE = "1"
python scripts/offline_repl.py
```

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
confirmation no injected instruction can bypass) → **postcondition verification where
available** (for actions that leave a durable OS-state fact, a clean return that didn't
actually happen is a failure, not a success). 100% block rate, 66-test adversarial fuzz
suite. Full model, capability tiers, and the containment roadmap:
[`CONTAINMENT_ARCHITECTURE.md`](CONTAINMENT_ARCHITECTURE.md).

## Evaluation

| Metric | Result |
|---|---|
| Intent accuracy — real-world phrasing (Amazon MASSIVE) | **92.33%** |
| Intent accuracy — out-of-distribution (synthetic) | **83.68%** |
| Fast-path resolution (no LLM call) | **88.45%** |
| **End-to-end task success (real machine, OS-verified)** | **96.7%** (95% CI 91.7–98.7%, n=120) |
| Security fuzzing block rate | **100%** (66/66) |
| Test suite (published CI) | 1,333 passing, 2 skipped; 86.75% coverage |

**Reproduce with zero cloud API keys:**

```powershell
$env:SENTINAL_OFFLINE = "1"
python scripts/reproduce_router_accuracy.py
python -m eval.run_eval --run-id offline-demo --task-id conv-hello --task-id deny-format --task-id deny-format-d-drive
```

`eval.run_eval` writes generated reports under `_evidence/P1-5/`; that directory is
gitignored except for its placeholder. The three-case offline demo proves the harness path
passes in deterministic mode and fails closed on malformed offline fallback actions; it does
**not** prove natural-language disk-format command recognition.

The full end-to-end number needs a real Windows desktop and live LLM access —
`benchmarks/run_benchmark.py --repeat 3`. Methodology (independent OS-state verification,
Wilson intervals, no score-inflating retries, and newly generated eval reports include git
commit metadata) is summarized in `docs/DECISIONS.md`.

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
tests/              Automated unit, integration, stress, and security tests
docs/               Compact public docs and current decision log
thesis/             Revised thesis and downloadable documents
historical-record/  Earlier thesis documents and supporting figures
```

## License

[MIT](LICENSE) © 2026 Gannoju Pavan Kumar
