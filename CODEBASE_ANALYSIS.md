# Deep Repository Analysis — SentinAL Ecosystem
**Analyst:** Claude · **Date:** 2026-07-02 · **Scope:** 3 folders, read-only analysis, no code changed.

---

## 0. The Big Picture

All three folders are **one product family: "SentinAL"**, built by Pavan (Vamshi). They are not independent projects — they are two branches of one idea plus one backup:

```
SentinAL Desktop Assistant ("Major project")      ← Voice AI desktop agent (JARVIS/MEGHA)
        │  governance ideas extracted & rebuilt
        ▼
SentinAL v3 CLI Gateway (backup_2026-02-22)       ← Ancestor snapshot (CLI-only)
        │  renamed governance/→core/, schema/→policies/, added API+UI+Docker+CI
        ▼
AI_Governance_Project (SentinAL Gateway v2.0)     ← Current, active, production-oriented
```

Evidence of lineage: `AI_Governance_Project/archive/app.py` is the backup's `app.py`; the backup's `governance/` modules match `AI_Governance_Project/core/` module-for-module (18 files, same names; contents evolved — `risk.py` differs); both share the SentinAL brand, policy JSON schemas, and adversarial datasets. The desktop assistant shares the SentinAL name, privacy-router concept, and its `archive/`/`phase_0/` folders contain the same generated reports.

---

# PROJECT 1 — `Major project` (SentinAL / MEGHA Desktop Assistant)

## 1.1 Purpose
A **voice-driven, security-hardened AI desktop assistant for Windows** ("J.A.R.V.I.S. OS SentinAL", packaged as "MEGHAv1"). Pipeline: wake-word → speech-to-text → intent extraction → validated execution of desktop capabilities (windows, media, processes, scheduling, code generation) → text-to-speech, with a **privacy router** that decides per-prompt whether to use a local LLM (Ollama) or cloud LLM (Groq). Academic final-year "Major Project 4-2" (extensive documentation PDFs included).

## 1.2 Fifteen-point detection matrix

| # | Aspect | Findings |
|---|--------|----------|
| 1 | Purpose | Secure voice AI desktop assistant (above) |
| 2 | Languages | Python 3.13 (backend), JavaScript/JSX (UI), TypeScript (phase_0 sentinal-ui components), CSS, PowerShell (generated scripts + `start_sentinal.ps1`), Batch |
| 3 | Frameworks/libs | **Python:** LangChain (`langchain_ollama`, `langchain_groq`), asyncio, python-dotenv, faster-whisper, scipy, sounddevice (per STT header), spaCy-style NLP correction. **JS:** React 19, Vite 8, Electron 35, Tailwind CSS 4, Zustand 5, framer-motion 12, three.js, electron-builder 26 |
| 4 | Build systems | Vite (frontend bundle), electron-builder → NSIS Windows installer (`MEGHAv1 Setup 1.0.0.exe`). No Python build system (no pyproject/setup.py at root) |
| 5 | Package managers | npm (package-lock.json), pip (venv/ present; **no root requirements.txt** — only `phase_0/requirements.txt`) |
| 6 | Databases | SQLite ×3: `sentinal_memory.db` (conversation/memory), `capabilities.db` (capability registry), `megha_path_cache.db` (file-path index built by `megha_indexer.py`) — duplicated in `data/` and `memory/` |
| 7 | APIs | Internal WebSocket bridge UI↔Python (`/ws/agent`, referenced by `wsService.js` and STT service); External: Groq API, Deepgram Nova-2 (STT), Picovoice Porcupine (wake word), Tavily (web search), Ollama local HTTP |
| 8 | Authentication | None (single-user desktop app). API keys via `.env`. Windows elevation helper `elevate.exe` shipped in installer |
| 9 | AI/ML components | Local LLM (Ollama llama3.2), cloud LLM (Groq llama-3.3-70b), Kokoro TTS (`kokoro-v1.0.onnx` + voices), faster-whisper base + large-v3-turbo model caches, Deepgram streaming STT, RNNoise noise suppression, adaptive VAD, vision module, CodeAct engine (LLM→PowerShell generation with security blocklist), privacy router (regex/heuristic PII & sensitive-path detection) |
| 10 | Deployment config | electron-builder config in `package.json` (NSIS, extraResources bundling Python code + `.env`), `start_sentinal.ps1`, `start_watchtower.bat` |
| 11 | Docker/K8s | **None** |
| 12 | CI/CD | **None** (no git repo at root either) |
| 13 | Testing | pytest — 21 test files in `tests/` (router, privacy_router, executor, processor, validator, memory, STT, security fuzz, stress, pipeline integration…); `htmlcov/` shows coverage was run |
| 14 | Env vars | `GROQ_API_KEY`, `GROQ_MODEL`, `DEEPGRAM_API_KEY`, `PICOVOICE_ACCESS_KEY`, `TAVILY_API_KEY`, `TAVILY_MAX_RESULTS`, `OLLAMA_MODEL`, `LLM_PROVIDER`, `STT_PROVIDER`, `SENTINAL_PORT`, `SENTINAL_UI_PORT`, `SENTINAL_HOST` |
| 15 | Config files | `config/settings.py` (BrainConfig — LLM factory/failover; note: header says "brain_config.py"), `config/constants.py`, `config/paths.py`, `config/prompts.py`, `phase_0/.env` (**contains live secrets**), `sentinal-ui/vite.config.js`, `eslint.config.js` |

## 1.3 Architecture overview
Three-process desktop system:
1. **Electron shell** (`sentinal-ui/electron/main.cjs`) boots the React HUD and spawns the Python backend (bundled as extraResources).
2. **Python agent server** (root `server.py`/`main.py` — see §1.9) exposes a WebSocket (`/ws/agent`); orchestrates: wake engine → STT → NLP correction → `agentic_core.processor.extract_intent` → `validator.validate_steps` → `executor.execute_pipeline` → capabilities → TTS. `BrainConfig.get_routed_llm()` consults `system_services/privacy_router.py` before every LLM call: PII/sensitive-path prompts stay local (Ollama), clean prompts may go to Groq with automatic failover back to local.
3. **Capabilities layer** — `capabilities/system/*` (window manager, media, processes, scheduler, dictation, vision, GUI resolver), `capabilities/developer/*` (CodeAct PowerShell engine, scaffolding, dependency installer, data modeler, academic research), `capabilities/web/search_engine.py` (Tavily).

## 1.4 Folder structure (live code only)
```
Major project/
├── capabilities/{system,developer,web}/   # 16 skill modules
├── config/            # settings(BrainConfig), constants, paths, prompts
├── interfaces/        # voice/ (stt,tts,wake,nlp), ui_bridge/, cli/ (EMPTY)
├── system_services/   # privacy_router, system_state
├── sentinal-ui/       # Electron+React HUD (src/, electron/, dist/, release/ ~installer)
├── data/, memory/     # SQLite DBs + kokoro TTS models (duplicated)
├── tests/             # 21 pytest files
├── logs/, images/, PDFS/
├── phase_0/           # FULL older snapshot (own core/, UIs, models, docs, .env!)
├── archive/           # legacy UIs, tools, docs, whisper model cache
├── telemetry/ directory_name/   # EMPTY
└── venv/, __pycache__/, htmlcov/
```

## 1.5 Module dependency graph
```
electron/main.cjs ─spawns→ server.py(✗missing) ─ws→ ui_bridge/conversation_manager
interfaces/voice/stt_service ──→ agentic_core.scheduler(✗missing)
capabilities/system/api_wrapper ──→ agentic_core.{processor,validator,executor}(✗missing)
capabilities/* ──→ agentic_core.processor._get_routing_llm(✗missing)
config/settings(BrainConfig) ──→ system_services/privacy_router
                              ──→ langchain_ollama / langchain_groq
tests/* ──→ all of the above
```

## 1.6 Data flow
Mic → VAD/RNNoise → Deepgram/faster-whisper → transcript → wake intelligence → intent JSON (LLM) → validator → executor → capability → result → TTS (Kokoro) + WebSocket → React HUD. Memory: SQLite (`sentinal_memory.db`); audit: `logs/security_audit.log`, `privacy_audit.log`; path index: `megha_path_cache.db`.

## 1.7 External services
Groq (cloud LLM), Deepgram (STT), Picovoice (wake word), Tavily (search), Ollama (local), HuggingFace (model downloads).

## 1.8 Missing documentation
No root README, no setup/install guide for the live tree, no root requirements.txt, no architecture doc matching the *current* layout (all docs describe v9/phase_0), no API/WS protocol doc, no CONTRIBUTING/LICENSE.

## 1.9 Unknown / broken components ⚠️
- **`main.py`, `server.py`, and the whole `agentic_core/` package are MISSING from the root tree.** Compiled remnants exist (`__pycache__/main.cpython-313.pyc`, `server.cpython-313.pyc`), electron-builder `extraResources` references `../main.py` and `../agentic_core`, and at least 8 live modules import `agentic_core.*`. Copies of an older `core/` + `server.py` survive only inside `sentinal-ui/release/win-unpacked/resources/` and `phase_0/`. **The live tree cannot run as-is.**
- `directory_name/` (empty — looks like an accidental mkdir), `telemetry/` (empty), `interfaces/cli/` (empty).
- `config/settings.py` contains a class documented as `brain_config.py` — file identity unclear.
- Not a git repository — no history to recover the deleted files from.
- `phase_0/.env` contains **real API keys** (Groq, Tavily, Deepgram set); installer `resources/.env` ships secrets inside the built EXE.

---

# PROJECT 2 — `AI_Governance_Project` (SentinAL Neuro-Symbolic Governance Gateway)

## 2.1 Purpose
A **fail-closed AI security middleware / guardrail gateway**: FastAPI service that intercepts prompts before they reach an LLM, running a 6-stage pipeline — semantic cache → symbolic veto (regex/keywords) → parallel semantic signals (FAISS threat scan, meta-intent, domain alignment, threat centroid) → deterministic fusion → LLM judge arbitration (Ollama Mistral) → policy arbitration by role tier → JSONL audit. Includes Streamlit admin/demo UI.

## 2.2 Fifteen-point detection matrix

| # | Aspect | Findings |
|---|--------|----------|
| 1 | Purpose | AI governance gateway / prompt firewall (above) |
| 2 | Languages | Python only (plus JSON policy files) |
| 3 | Frameworks/libs | FastAPI, uvicorn, Streamlit, sentence-transformers (`all-mpnet-base-v2`), FAISS-CPU, spaCy (`en_core_web_sm` NER), pydantic-settings, requests/httpx, python-json-logger, numpy<2 |
| 4 | Build systems | Docker (two images); no Python packaging |
| 5 | Package managers | pip (`requirements.txt`, `requirements-ci.txt`) |
| 6 | Databases | **None.** State = JSON files: `policies.json`, `policy_rules.json`, `policies/*.json` (anchors, corpus, symbolic rules), `semantic_cache.json` (flat-file vector cache), `audit.jsonl` (append-only audit) |
| 7 | APIs | REST: `POST /api/v1/assess`, `POST /api/v1/update` (threat-feed pull), `POST /api/v1/cache/flush`, `GET /health`; consumes Ollama HTTP API |
| 8 | Authentication | **None on the API.** `core/auth.py` has **hardcoded capability tokens** (`ADM-112233-SUPER-USER`, `RES-998877-SECRET-ACCESS`) but is only used by CLI/env — the API trusts the `role` field in the request body. CORS `allow_origins=["*"]` with credentials |
| 9 | AI/ML | Sentence-transformer embeddings (768-d), FAISS IndexFlatIP similarity, semantic cache w/ cosine threshold 0.95, LLM-as-judge (Mistral via Ollama, fail-closed), spaCy NER PII redaction, threat centroid, live threat-feed ingestion (GitHub DAN jailbreak repo) |
| 10 | Deployment | `docker-compose.yml`: `sentinal-api` (:8000) + `sentinal-ui` (:8501) + `ollama` (:11434), bridge network, volume-mounted policies/audit |
| 11 | Docker/K8s | Docker + Compose yes; **Kubernetes no** |
| 12 | CI/CD | GitHub Actions (`.github/workflows/ci.yml`): pytest on push/PR to main, Python 3.10, lightweight CI requirements (heavy ML mocked). No build/publish/deploy stages |
| 13 | Testing | pytest — only **2 files, 3 tests** (`test_api.py`, `test_privacy.py`) + `tests/test_prompts.json`; separate `benchmarks/` (accuracy eval, load test) and archived adversarial eval suite |
| 14 | Env vars | `SEMANTIC_THRESHOLD_HIGH/MEDIUM`, `EDUCATIONAL_THRESHOLD`, `DOMAIN_THRESHOLD`, `CACHE_SIMILARITY_THRESHOLD`, `META_INTENT_THRESHOLD`, `OLLAMA_API_URL`, `OLLAMA_MODEL`, `EMBEDDING_MODEL`, `POLICY_FILE`, `POLICY_RULES_FILE`, `API_URL` (UI), `CAPABILITY_TOKEN` |
| 15 | Config files | `.env.example`, `core/config.py` (pydantic BaseSettings + legacy re-exports), policy JSONs, Dockerfiles, docker-compose.yml, ci.yml, `.gitignore` |

## 2.3 Architecture & request flow
```
Client/Streamlit → POST /api/v1/assess (FastAPI, X-Process-Time middleware)
  1. redact_pii()        spaCy NER + regex (email/phone/IP/Aadhaar)
  2. assess_risk()       Stage 0 cache → Stage 1 symbolic veto → Stage 2 signals
                         (FAISS threat, meta-intent, domain, centroid, dynamic feeds)
                         → Stage 3 fusion → Stage 4 Mistral judge (fail-closed)
  3. policy_decision()   role tier × risk → ALLOW / RESTRICT / BLOCK
  4. log_event()         audit.jsonl (JSONL)
  → AssessResponse {decision, risk_level, details, clean_prompt, redacted_items, ms}
```
**Data flow:** policy JSONs + educational anchors → embedded lazily into FAISS at first request; threat feeds pulled from GitHub → dynamic anchors; every decision cached in `semantic_cache.json` (HIGH decisions locked, never downgraded).

## 2.4 Module dependency graph
```
api/main.py → api/schemas, core/{privacy,risk,policy,logger,updates,cache}
core/risk.py (orchestrator) → semantic_judge, embeddings, cache, updates,
        domain_classifier, config, normalizer, threat_centroid,
        vector_store, policy_loader, logger
core/vector_store → embeddings → sentence_transformers (lazy)
core/semantic_judge → Ollama HTTP     core/llm → `ollama run` subprocess (CLI path)
ui/web_app.py → REST only (clean decoupling)
core/auth.py → config   (⚠ not wired into api/)
```

## 2.5 External services
Ollama (judge + downstream LLM), HuggingFace (embedding model download at build/first run), GitHub raw (threat feed), Docker Hub.

## 2.6 Missing documentation / unknowns
README is extensive (25 sections) but: §1 is literally titled "1. Section" (placeholder); no OpenAPI export; no threshold-tuning guide; no policy-authoring schema doc; benchmarks referenced but methodology not reproducible from README alone. `audit.jsonl` is committed despite being gitignored (tracked before ignore rule). `core/llm.py` (subprocess CLI streaming) appears to be dead code on the API path — used only by archived CLI.

---

# PROJECT 3 — `AI_Governance_Project_backup_2026-02-22` (SentinAL v3 snapshot)

## 3.1 Purpose
A **frozen backup of the governance project's ancestor**: CLI-only "SentinAL v3 — Deterministic-First AI Governance Architecture". `app.py` REPL accepts text / `image:` / `audio:` inputs, runs the same assess→policy→log→LLM pipeline.

## 3.2 Fifteen-point matrix (differences from Project 2 only)
Languages: Python. Frameworks: same core ML stack, **no FastAPI/Streamlit/Docker/CI**. Package layout: `governance/` (≙ `core/`), `schema/` (≙ `policies/`), `evaluation/` (adversarial eval harness + results). Build/deploy/Docker/CI/testing frameworks: **none** (evaluation scripts only). Databases: none (JSON). APIs: none (CLI). Auth: same hardcoded-token `auth.py`. Env vars/config: same threshold set, `config/.gitkeep` only. Git: yes, 3 commits.

## 3.3 Unknowns / defects
- `README.md` contains an **unresolved merge-conflict marker (`<<<<<<< HEAD`)** — committed conflicted file.
- `governance/__pycache__/*.pyc` committed to git.
- Purely historical: superseded by Project 2 (which preserves its `app.py` and eval suite under `archive/`). Safe to treat as read-only archive.

---

# Cross-Project Relationship Map

| From | To | Relationship |
|------|----|--------------|
| backup_2026-02-22 | AI_Governance_Project | Direct ancestor. `governance/*` → `core/*` (renamed, evolved), `schema/*` → `policies/*`, `app.py` → `archive/app.py`. No runtime dependency |
| Major project | AI_Governance_Project | Conceptual sibling: shares SentinAL brand, privacy/guardrail philosophy, threshold-based routing. **No code dependency at runtime** — desktop app's `privacy_router` is an independent regex implementation |
| Major project ↔ phase_0/archive | itself | `phase_0/` and `archive/` are embedded older snapshots of the same desktop app (v9 era), including duplicate UIs, models, docs |

**No project imports another at runtime.** The only hard dependency risk is internal: Major project's live code depends on the deleted `agentic_core/` package.

---

# Consolidated Tech Stack

| Layer | Major project | AI_Governance_Project | Backup |
|-------|---------------|----------------------|--------|
| Language | Python 3.13, JS/JSX/TS | Python 3.9–3.10 | Python 3.13 |
| API | WebSocket (custom) | FastAPI REST | — (CLI) |
| UI | Electron 35 + React 19 + Vite 8 + Tailwind 4 + Zustand + three.js | Streamlit | terminal |
| LLM | Ollama llama3.2 + Groq llama-3.3-70b (LangChain) | Ollama Mistral | Ollama Mistral |
| Speech | Deepgram, faster-whisper, Porcupine, Kokoro TTS, RNNoise | — | audio rail stub |
| Vectors | — | sentence-transformers + FAISS | sentence-transformers (list scan) |
| Storage | SQLite ×3 | JSON/JSONL flat files | JSON |
| Packaging | electron-builder NSIS | Docker Compose | — |
| CI | none | GitHub Actions | none |
| Tests | pytest (21 files) | pytest (2 files) | eval scripts |
