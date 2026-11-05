# SentinAL — Secure AI Desktop Orchestration

[![SentinAL CI](https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration/actions/workflows/ci.yml/badge.svg)](https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration/actions/workflows/ci.yml)

SentinAL is a supervised Windows desktop voice and text agent. It separates model-assisted interpretation from deterministic action validation and checks supported postconditions against operating-system state.

**Status: B.Tech final-year project and research prototype.** The published results below describe identified evaluations, not unattended reliability or production deployment.

## Architecture

```text
Voice / text → intent router → bounded planner → validator / capability controls
                                                         ↓
                                observed OS state ← executor
```

The router tries deterministic rules and local semantic classification before language-model fallback. A trained classifier is used when its local artifact is present. The privacy router selects local or cloud LLM processing; voice transcription has its own provider configuration. Optional learning features are disabled by default.

## Results and evidence

| Evaluation | Reported result | Scope |
|---|---:|---|
| MASSIVE-derived intent evaluation | 92.33% accuracy | Real-world phrasing mapped to supported intents |
| Separately authored synthetic OOD evaluation | 83.68% accuracy | Harder phrasing; not an external benchmark |
| Router resolution without fallback LLM invocation | 88.45% | Reported classifier-era evaluation |
| Real-machine task benchmark | 116/120 (96.7%) | Independent OS-state checks; reported 95% CI 91.7–98.7% |
| Adversarial security regression | 66/66 blocked | Finite test suite, not a universal security guarantee |
| October 6, 2026 CI checkpoint | 1,333 passed, 2 skipped; 86.75% coverage | [Historical run](https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration/actions/runs/37445301449) |

Earlier evaluations and the current measurements use different datasets and configurations. See [evaluation notes](docs/EVALUATION.md) for the older numbers, reproduction prerequisites and limitations. The badge above links to current CI; the dated checkpoint is retained as historical evidence.

## Documentation

| Resource | Contents |
|---|---|
| [Thesis](thesis/Thesis.md) | Full thesis, PDF, Word document and evidence inventory |
| [Historical record](historical-record/README.md) | Earlier thesis documents and figures |
| [Evaluation](docs/EVALUATION.md) | Measurement scope and reproduction commands |
| [Contributing](CONTRIBUTING.md) | Development checks and CI selection |
| [Security](SECURITY.md) | Trust boundaries, limitations and reporting |
| [Design checkpoint](docs/DECISIONS.md) | Dated architectural decisions |
| [Containment audit](CONTAINMENT_ARCHITECTURE.md) | Historical architecture audit and proposed controls |
| [Desktop interface](sentinal-ui/README.md) | Frontend development and packaging boundaries |

## Requirements

- Windows 10/11 and Python 3.11–3.13 for the desktop execution layer.
- Ollama for local LLM processing; configured cloud providers are optional.
- Node.js 22.12+ for the React/Electron interface.
- Model weights and voice assets may require separate downloads. A clean clone does not include the trained classifier or all evaluation artifacts.

## Setup

Run from PowerShell:

```powershell
git clone https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration.git
Set-Location SentinAL-Desktop-AI-Orchestration
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Review `.env` before starting. The template selects a cloud LLM provider; set `LLM_PROVIDER=local` for local Ollama processing and configure the model separately. Keep `SENTINAL_HOST=127.0.0.1`. Configure speech providers independently if using voice.

```powershell
ollama pull llama3.2
python main.py
```

Starting the backend enables real desktop actions. Use a disposable test directory for file operations. The REST bearer token is generated in `.sentinal_token`; keep it private.

For the text-only offline entry point, after installing dependencies:

```powershell
$env:SENTINAL_OFFLINE = "1"
python scripts/offline_repl.py
```

This path uses local Ollama when reachable and a deterministic fallback otherwise. It is not an OS sandbox. Initial embedding-model loading may still require a download if weights are absent.

## API boundaries

| Endpoint | Access | Purpose |
|---|---|---|
| `GET /health`, `/api/health` | Unauthenticated | Liveness |
| `POST /api/command` | Bearer token | Submit a command capable of real OS effects |
| `GET /api/tasks`, `/api/tasks/{id}` | Bearer token | Task status |
| `GET /api/logs` | Bearer token | Recent diagnostics |
| `WS /ws/agent`, `/ws/telemetry` | Separate WebSocket handling | Agent events and telemetry |

The WebSocket routes do not provide the same REST bearer-token boundary. CORS and origin restrictions are not general client authentication. Keep the service on loopback; network exposure requires additional authentication and deployment controls.

## Security and limitations

Intent allowlists, path validation, capability controls, confirmation support and postcondition checks constrain supported actions. Application path checks are not OS-enforced isolation. The REST confirmation helper defaults to disabled unless `SENTINAL_REQUIRE_CONFIRMATION=true`; review the actual channel and configuration before relying on approval. These controls and their remaining gaps are described in [SECURITY.md](SECURITY.md).

Not every intent has an independent postcondition. GUI automation depends on an interactive Windows session and may fall back to pixel matching. The 120-task benchmark is self-authored, and generated reports/model artifacts are not bundled. Source packaging exists, but a self-contained installer and unattended operation are not established by CI.

## Repository layout

```text
agentic_core/       Routing, planning, validation, execution and observation
capabilities/       System, developer and web actions
config/             Paths, policy and capability configuration
interfaces/         Voice and UI adapters
sentinal-ui/        React interface and Electron shell
eval/, benchmarks/  Evaluation instruments and task definitions
tests/, scripts/    Regression suites and maintenance tools
docs/               Development and evaluation documentation
thesis/             Revised thesis and downloadable documents
historical-record/  Preserved earlier thesis material
```

## License

[MIT](LICENSE) © 2026 Gannoju Pavan Kumar
