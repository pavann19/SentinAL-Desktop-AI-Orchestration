# Unified Engineering Review — SentinAL Ecosystem
**Panel:** Principal SWE, Staff Backend, Frontend Architect, AI Research, ML Eng, DevOps, Cloud Architect, DB Architect, Security, Performance, QA Lead, SRE, PM, UX, Tech Writer.
**Method:** Every claim below was verified against actual files. Where the panel initially disagreed or assumed, we re-inspected code before scoring (self-challenge notes in §3).

---

## 1. Scorecard

| # | Dimension | Ecosystem | AI_Governance | Major project | Backup |
|---|-----------|:---:|:---:|:---:|:---:|
| 1 | **Repository Score** | **54/100** | 66 | 42 | 55 |
| 2 | Security | 45 | 52 | 38 | 50 |
| 3 | Architecture | 63 | 72 | 55 | 58 |
| 4 | Scalability | 40 | 45 | 30 | 35 |
| 5 | Performance | 56 | 60 | 52 | 45 |
| 6 | AI Readiness | 66 | 74 | 60 | 55 |
| 7 | Production Readiness | 40 | 55 | 22 | n/a |
| 8 | Maintainability | 50 | 65 | 38 | 60 |
| 9 | Code Quality | 61 | 68 | 58 | 60 |
| 10 | Documentation | 55 | 78 | 35 | 45 |

**Headline:** AI_Governance_Project is a genuinely well-designed prototype gateway with production *aspirations* but prototype *hardening* (no API auth, 3 tests, flat-file state). Major project contains strong engineering (privacy routing, STT pipeline, CodeAct) but is currently **unrunnable and unversioned** — its brain (`agentic_core/`, `main.py`, `server.py`) is missing from disk. That single fact caps its scores.

---

## 2. Expert Findings (condensed, deduplicated)

### Principal SWE — Architecture / SOLID / Clean Architecture
The governance pipeline (`core/risk.py`) is the best code in the ecosystem: staged orchestration (cache→veto→signals→fusion→judge), single-responsibility functions, deterministic-first design, fail-closed defaults. Violations: `core/config.py` re-exports 15 module-level constants "for backwards compatibility" — kills testability of thresholds; module-level mutable globals (`CACHE_DATA`, `_faiss_initialized`, anchor lists) make the API process stateful and unsafe for multi-worker deployment. Major project's layering (config/capabilities/interfaces/system_services) is sound DDD-lite, but every capability late-imports `agentic_core` inside functions — a hidden god-dependency. Backup: frozen, acceptable as archive.

### Staff Backend — API / Concurrency / Error Handling
`POST /assess` is declared `def` (sync) in an async framework — fine (thread pool) but the README's "asynchronous high-throughput I/O" claim is overstated: `semantic_judge` uses blocking `requests` with 30s timeout; embeddings run on the request thread; FAISS/cache access has **no locking** — concurrent first-requests can double-initialize indexes and corrupt `semantic_cache.json` (read-modify-write whole file per request). No rate limiting, no request size cap, no `/update` auth (anyone can poison threat feeds — though ingestion only *adds* threat anchors, the endpoint is still unauthenticated remote I/O). Error handling: judge path is exemplary fail-closed; file I/O paths mostly try/except-log-continue (fail-open for cache — acceptable, deliberate for HIGH lock).

### Security Engineer
Critical: (1) **Hardcoded credentials** in `core/auth.py` (`ADM-112233-SUPER-USER`) in both governance repos; (2) **API trusts client-supplied `role`** — the entire policy-arbitration layer is bypassable by sending `"role": "INTERNAL"`; (3) **CORS `*` + allow_credentials=True** (invalid combo per spec, browsers ignore, but signals intent drift); (4) **Live secrets committed**: `Major project/phase_0/.env` has real Groq/Tavily/Deepgram keys, and the NSIS installer bundles `.env` into `resources/` — keys are distributed inside a shipped EXE. Rotate all four keys immediately. (5) `audit.jsonl` with real prompt data tracked in git. (6) CodeAct engine executes LLM-generated PowerShell gated only by a regex blocklist — blocklists are bypassable by construction; needs allowlist + sandbox. (7) Prompt-injection defense is the product itself and is decent (normalization → symbolic → semantic → judge with no-downgrade rules) — credit where due.

### AI Research + ML Engineer — AI components, RAG, model selection, vector DB
Not a RAG system — it's a **classification-over-anchors** system; that's the right call for a guardrail. Good: normalization before symbolic check (anti-obfuscation), meta-intent veto, educational safe-harbor with judge restriction (SAFE→MEDIUM when threat signal present), locked-HIGH cache. Weak: `check_semantic_similarity` for educational anchors **re-embeds anchors on every request** (O(N) model calls — the FAISS win is negated on that path); anchor sets are tiny (6 educational anchors) and thresholds (0.48/0.22) appear hand-tuned without a calibration set; single embedding model hardcoded to 768-d — `ScalableVectorStore(dimension=768)` breaks silently if `EMBEDDING_MODEL` changes; judge prompt is susceptible to indirect injection ("reply SAFE") since the user prompt is concatenated raw — mitigated by the MEDIUM restriction but `threat_present=False` cases can still be laundered to LOW. Evaluation exists (adversarial dataset v1, accuracy benchmark) but isn't in CI. Desktop app: sensible model tiering (local llama3.2 for privacy, Groq 70B for capability), real DSP engineering in STT v4.0.

### Database Architect
AI_Gov has **no database**: audit = append JSONL (no rotation, no index, unbounded), semantic cache = full-file JSON rewrite per entry (O(N) write amplification, race-prone), policies = JSON with two overlapping locations (`policies.json` root + `policies/` dir — confusing). SQLite or Postgres + pgvector would collapse cache/audit/policies into transactional storage. Major project: three SQLite DBs duplicated across `data/` and `memory/` with no documented owner or migration story.

### Performance Engineer
Latency budget per uncached assess: embedding (~20-50ms CPU) + FAISS (<1ms) + educational re-embedding (~6×20ms, wasteful) + optional judge (up to 30,000ms). The X-Process-Time middleware is good; per-stage `*_ms` in details is good. Cache lookup is linear cosine over all entries — fine at 10³, not at 10⁶. Embedding model reload risk: none (cached singleton). Desktop: STT header documents real fixes (event-loop-safe locks, polyphase resample) — evidence of profiling culture. No perf tests in CI for either.

### DevOps / Cloud / SRE
AI_Gov: Docker Compose is correct for dev (3 services, named volumes, bridge net) but images are Python 3.9 while CI is 3.10 (drift); `COPY . .` in Dockerfile.api ships tests/docs/archive into the image; no healthchecks in compose (API has `/health` but compose doesn't use it); no resource limits; single uvicorn worker implied (module globals make >1 worker unsafe anyway); no metrics endpoint, no structured log shipping, no alerting. CI runs tests only — no lint, no image build, no security scan (pip-audit/trivy), no deploy. K8s: not present; the app is one config pass away from 12-factor except file-state. Major project: no git, no CI, installer bundles secrets — deployment story is manual and hazardous. **SRE verdict: nothing here is on-call-able yet.**

### QA Automation Lead
AI_Gov: 3 tests for a security product whose selling point is deterministic guarantees. The risk-fusion matrix (meta-intent × domain × threat × educational × judge) is pure-function testable (`fuse_signals`) and has **zero tests**. Test/prod parity risk: CI mocks all ML, so a broken FAISS integration ships green. Major project: 21 test files incl. security fuzz and stress — the best test intent in the ecosystem — but they can't pass today (imports of deleted `agentic_core`), and there's no CI to catch that. That's how the repo rotted silently.

### Frontend Architect + UX
sentinal-ui: modern stack (React 19, Vite 8, Tailwind 4, Zustand), clean component split (hud/core/ui), ws service + message adapter separation — good. Concerns: three.js + framer-motion HUD is heavy for an always-on assistant (GPU/battery); `dist/` and full `release/` (≈200MB installer + win-unpacked with DLLs) committed inside source tree; duplicate UI trees (`sentinal-ui`, `phase_0/jarvis-ui-new`, `phase_0/sentinal-ui`, `archive/ui_legacy`) — four copies. Streamlit UI: fine as demo; fake status indicators ("✅ System Online" hardcoded) mislead operators; role selector in sidebar makes the auth bypass a UI feature.

### PM + Tech Writer
AI_Gov README is 28KB and genuinely strong (architecture, mermaid, quickstart, API docs, roadmap) but oversells ("production-grade", "enterprise-ready", "O(log N)" — IndexFlatIP is exact O(N) search, not log) and §1 is titled "1. Section". Version confusion across artifacts: README v1.0.0 release commit, API `version="2.0.0"`, backup calls itself v3, desktop docs say v9 — no coherent versioning scheme. Major project has rich *academic* docs but zero *operational* docs. No LICENSE file in any repo despite README badge claiming MIT. No CHANGELOG anywhere.

### Dead code / duplication census
Dead: `core/llm.py` (subprocess path, unused by API), `core/auth.py` (unwired), `evaluate_final.py` (root, superseded), `policies.json` vs `policies/` overlap, Major project empty dirs (`directory_name/`, `telemetry/`, `interfaces/cli/`), `.vite/` stray cache, `__pycache__` at repo roots, backup's committed `.pyc`. Duplication: backup `governance/` ≈ AI_Gov `core/` (intentional, archive); Major project `phase_0/` duplicates ~everything incl. 2 whisper model caches (~GBs), 2 kokoro models, 3 DB copies, 2 installers. Estimated recoverable disk: several GB.

---

## 3. Self-challenge (what the panel got wrong on first pass)
1. *"The API is async and non-blocking"* — README claim; inspection showed sync handler + blocking `requests`. Score adjusted down.
2. *"auth.py protects the API"* — false; grep showed it's never imported by `api/`. Reclassified from "weak auth" to "**no** auth".
3. *"FAISS gives O(log N)"* — `IndexFlatIP` is brute-force exact; the win is vectorized C, not complexity. Docs finding, not perf bug at current scale.
4. *"Major project is merely messy"* — worse: missing `agentic_core`/`main.py`/`server.py` verified three ways (find, pycache, electron extraResources). Production readiness cut to 22.
5. *"Educational anchors are FAISS-indexed"* — only partially: `educational_store` exists, but `check_educational_context` calls the non-FAISS `check_semantic_similarity` re-embedding path. Confirmed by reading both functions.
6. Panel debated whether client-supplied `role` is a real vuln given it's a demo — consensus: the README claims production middleware, so it's scored as production. Fail-closed design earns back points elsewhere.

---

## 4. Top 100 Improvements (ranked by impact)
Leg: **T**ime (h=hours d=days w=weeks) · **D**ifficulty (L/M/H) · **R**isk of change (L/M/H) · Proj: G=AI_Governance, M=Major project, B=Backup, A=All.

| # | Improvement | Proj | T | D | R | Files | Benefit |
|---|-------------|:---:|:--:|:-:|:-:|-------|---------|
| 1 | Rotate the 4 leaked API keys (Groq, Tavily, Deepgram, Picovoice), then purge `.env` copies | M | 1h | L | L | phase_0/.env, releases | Stops live credential exposure |
| 2 | Recover/rewrite `agentic_core/`, `main.py`, `server.py` (sources exist in `sentinal-ui/release/win-unpacked/resources/` + phase_0) | M | 2-3d | M | M | ~18 new | Makes the flagship project runnable again |
| 3 | Put Major project under git immediately (before any other change) | M | 1h | L | L | repo root | Prevents recurrence of #2; enables everything else |
| 4 | Server-side role resolution: derive role from a verified credential, never from request body | G | 1d | M | M | api/main.py, core/auth.py, schemas.py | Closes total policy-bypass hole |
| 5 | Replace hardcoded tokens with env-provided hashed tokens or JWT | G,B | 4h | L | L | core/auth.py | Removes committed credentials |
| 6 | Add API authentication (API-key header middleware) to all endpoints incl. `/update`, `/cache/flush` | G | 1d | M | M | api/main.py | Prevents unauthenticated cache flush / feed poisoning |
| 7 | Test the fusion matrix: unit tests for `fuse_signals`, `judge_arbitration`, cache-lock, symbolic veto (~30 cases) | G | 2d | M | L | tests/ +3 | Deterministic guarantees actually guaranteed |
| 8 | Fix CORS: explicit origin list, drop credentials with `*` | G | 1h | L | L | api/main.py | Standards-correct browser security |
| 9 | Exclude `.env` from electron-builder `extraResources`; inject secrets at runtime (keytar/OS keychain) | M | 4h | M | L | sentinal-ui/package.json | Stops shipping secrets in installers |
| 10 | Add thread lock around FAISS init + cache read/write | G | 3h | M | L | core/risk.py, cache.py | Eliminates race corruption under load |
| 11 | Untrack `audit.jsonl` (`git rm --cached`) and rotate file at runtime | G | 1h | L | L | audit.jsonl | Stops leaking user prompts via git |
| 12 | FAISS-index the educational anchors path (use existing `educational_store`) | G | 3h | L | L | core/risk.py | Removes per-request re-embedding (~100ms saved) |
| 13 | Root `requirements.txt` / `pyproject.toml` for Major project (freeze from venv) | M | 2h | L | L | +1 | Reproducible environment |
| 14 | Root README for Major project: what runs, how, current broken state | M | 4h | L | L | +1 | Onboarding; documents #2 |
| 15 | CI for Major project (GitHub Actions: pytest + ruff) | M | 4h | L | L | +1 | Catches rot like #2 automatically |
| 16 | Async judge: `httpx.AsyncClient` + async endpoint, or run judge in executor with cap | G | 1d | M | M | core/semantic_judge.py, api/main.py | Frees workers during 30s judge calls |
| 17 | Replace `semantic_cache.json` with SQLite (or Redis) w/ vector column | G | 1-2d | M | M | core/cache.py | Transactional cache; kills O(N) rewrite |
| 18 | Rate limiting + max prompt length on `/assess` | G | 3h | L | L | api/main.py, schemas.py | DoS resistance; embedding cost cap |
| 19 | Integration test job in CI with real (small) embedding model, nightly | G | 1d | M | L | ci.yml | Closes mock-only blind spot |
| 20 | Delete or archive `release/`, `dist/`, `win-unpacked/` from source tree (git-ignore build outputs) | M | 2h | L | L | ~600 files | Repo shrinks GBs; clarity |
| 21 | Deduplicate `phase_0/` (keep as compressed archive outside repo or in git history) | M | 3h | L | M | ~400 files | Removes whole-project duplicate incl. secrets |
| 22 | Wire adversarial-accuracy benchmark into CI with threshold gate (e.g. ≥95% of baseline) | G | 1d | M | L | ci.yml, benchmarks/ | Regression-proof detection quality |
| 23 | Prompt-injection hardening for judge: structured delimiters + instruction to ignore embedded directives + output token limit | G | 3h | M | L | core/semantic_judge.py | Blocks "reply SAFE" laundering |
| 24 | CodeAct: switch blocklist→allowlist of PS cmdlets + `-ConstrainedLanguage` mode + dry-run preview | M | 2-3d | H | M | codeact_engine.py | LLM-generated script safety |
| 25 | Healthchecks in docker-compose (`/health`, ollama tags endpoint) + `depends_on: condition` | G | 2h | L | L | docker-compose.yml | Orderly startup; self-healing |
| 26 | Align Docker (3.9) and CI (3.10) Python; pin one version everywhere | G | 1h | L | L | Dockerfile.api/.ui, ci.yml | Kills env drift class of bugs |
| 27 | `.dockerignore` + multi-stage Dockerfile (exclude tests/docs/archive; pre-download models in build stage) | G | 3h | L | L | +1, Dockerfile.api | Smaller, faster, cleaner images |
| 28 | Structured audit rotation (size/day-based) + retention policy | G | 3h | L | L | core/audit.py, logger.py | Unbounded-disk fix; compliance-real |
| 29 | Prometheus metrics endpoint (decision counts by risk/source, stage latencies, cache hit rate) | G | 1d | M | L | api/main.py +1 | Observability beyond one header |
| 30 | Delete empty dirs (`directory_name/`, `telemetry/` or implement it, `interfaces/cli/`) | M | 15m | L | L | 3 dirs | Hygiene; removes confusion |
| 31 | Resolve merge-conflict marker in backup README | B | 15m | L | L | README.md | Restores document integrity |
| 32 | Fix README §1 title ("Section") + correct O(log N)→exact-search claim | G | 1h | L | L | README.md | Credibility of flagship doc |
| 33 | Add LICENSE files (MIT badge is claimed but no license exists) | A | 30m | L | L | +3 | Legal clarity |
| 34 | Single source of policy truth: merge root `policies.json`/`policy_rules.json` into `policies/` dir | G | 3h | L | M | 4 JSON + loaders | Ends dual-location confusion |
| 35 | Pydantic validation on all policy JSON at load (schema models, fail fast with line info) | G | 4h | M | L | core/policy_loader.py, +schemas | Malformed policy = boot error, not runtime surprise |
| 36 | Remove config re-export shim; import `settings` object directly everywhere | G | 3h | L | M | core/config.py + ~10 importers | Testable, override-able config |
| 37 | Embedding-dimension from model, not hardcoded 768 | G | 1h | L | L | core/vector_store.py | Model swap won't silently break |
| 38 | Version scheme: single VERSION file; sync API version, README, tags | A | 2h | L | L | 3-4 files | Ends v1/v2/v3/v9 confusion |
| 39 | Delete dead code: `core/llm.py` (API path), root `evaluate_final.py`, stray `.vite/` | G,M | 1h | L | L | 3 files | Less to maintain/misread |
| 40 | `git rm` committed `__pycache__`/`.pyc` in backup; add to .gitignore | B | 30m | L | L | ~12 files | Repo hygiene |
| 41 | Batch-embed anchors at startup (single `model.encode(list)`) instead of per-text loop | G | 2h | L | L | vector_store.py, risk.py | 5-10× faster index build |
| 42 | Cache eviction policy (LRU/TTL, max entries) for semantic cache | G | 4h | M | L | core/cache.py | Bounded memory; fresher decisions |
| 43 | Startup warmup: embed a dummy prompt + init FAISS before serving (readiness probe) | G | 2h | L | L | api/main.py | No 10s first-request stall |
| 44 | Type hints + mypy in CI for `core/` | G | 1-2d | M | L | ~20 files, ci.yml | Catches signature drift |
| 45 | Ruff/black + pre-commit hooks both active repos | G,M | 3h | L | L | +2 cfg | Consistent style, free bug class |
| 46 | pip-audit / safety scan in CI | G | 2h | L | L | ci.yml | Dependency CVE alerts |
| 47 | Secret scanning (gitleaks) in CI + pre-commit | A | 2h | L | L | ci.yml | Prevents key-leak recurrence |
| 48 | `/update` feed ingestion: pin source commit SHA, validate content size/shape, log diff | G | 4h | M | L | core/updates.py | Supply-chain guard on threat feeds |
| 49 | Judge response: enforce single-token output (`num_predict`), strict verdict parse (exact match, not substring) | G | 2h | L | L | semantic_judge.py | "NOT SAFE"→currently parses as SAFE ("SAFE" in verdict). Real bug |
| 50 | Restore/verify Major project test suite runs post-#2; fix imports | M | 1-2d | M | L | tests/ (21) | Regains regression net |
| 51 | Streamlit: real health from `/health` instead of hardcoded "System Online" | G | 2h | L | L | ui/web_app.py | Honest operator signal |
| 52 | Consolidate Major project DBs: one `data/` location, delete `memory/` dupes, document schema | M | 4h | M | M | 6 db files | Single source of truth |
| 53 | WebSocket protocol doc (message types in `messageAdapter.js` ↔ server) | M | 4h | L | L | +1 doc | UI/backend contract explicit |
| 54 | Add k6/locust load test as CI-optional job with latency budget assertions | G | 1d | M | L | benchmarks/, ci.yml | Perf regressions visible |
| 55 | Gunicorn/uvicorn multi-worker safety: after #10/#17, document worker count; or state single-worker requirement | G | 2h | M | L | Dockerfile.api, README | Correct horizontal scaling story |
| 56 | Response headers: request-id middleware + correlation id in audit events | G | 3h | L | L | api/main.py, audit.py | Traceability across log/audit |
| 57 | Threshold calibration harness: sweep thresholds against labeled dataset, emit ROC; commit chosen operating point | G | 2d | M | L | benchmarks/ +1 | Evidence-based 0.48/0.22 instead of hand-tuned |
| 58 | Expand adversarial dataset (multilingual, base64/leet obfuscation, indirect injection) to ≥500 cases | G | 2-3d | M | L | data/ | Detection robustness measured |
| 59 | Normalize→embed consistency: ensure embeddings use the same normalized text as symbolic stage | G | 2h | L | M | core/risk.py | Obfuscated prompts hit the right vectors |
| 60 | Negative-anchor set (benign lookalikes) to reduce false positives; track FP rate in benchmark | G | 1-2d | M | L | policies/, benchmarks/ | Fewer wrong blocks = usable product |
| 61 | OpenAPI: export spec artifact in CI; add response examples + error schemas | G | 3h | L | L | api/, ci.yml | Client integration ease |
| 62 | 422/400 handling: explicit validation errors for empty/oversized prompt, unknown role enum | G | 2h | L | L | schemas.py | Clean API contract (role should be enum, not str) |
| 63 | `AssessRequest.role` → Literal/Enum type | G | 1h | L | L | api/schemas.py | Prevents typo'd tiers silently defaulting |
| 64 | Backup repo: mark clearly READ-ONLY (README banner) or convert to git tag in main repo | B | 1h | L | L | README.md | Prevents accidental divergent edits |
| 65 | Consolidate the two governance repos' history: import backup as historical branch/tag of AI_Gov | B,G | 3h | M | L | git only | One timeline, no drift risk |
| 66 | Major project: name the product (SentinAL vs MEGHA vs JARVIS) once; rename folders/app ids consistently | M | 4h | L | M | package.json, docs | Brand/identity coherence |
| 67 | `config/settings.py` header/name mismatch: rename to `brain_config.py` or fix header + module docstring | M | 30m | L | L | 1 file | Removes identity confusion |
| 68 | Electron: `contextIsolation`/`nodeIntegration` audit of preload; pin CSP in index.html | M | 1d | M | M | electron/*.cjs | Desktop attack-surface reduction |
| 69 | Electron auto-update strategy (electron-updater) or documented manual update path | M | 1-2d | M | M | package.json, main.cjs | Shipped-app patchability |
| 70 | STT: make provider fully pluggable via `STT_PROVIDER` (Deepgram/whisper) with graceful offline fallback documented | M | 1d | M | L | interfaces/voice/stt_service.py | Works without cloud/network |
| 71 | Privacy router: unit-test corpus of FP/FN cases (the "desktop" false-positive fix suggests no regression suite) | M | 1d | M | L | tests/test_privacy_router.py | Locks in v2.0 fixes |
| 72 | Central exception taxonomy for capabilities (typed errors → user-facing messages) | M | 1-2d | M | M | capabilities/* | Consistent failure UX |
| 73 | Scheduler/process manager: idempotency + audit log for system-mutating actions | M | 1-2d | M | M | capabilities/system/ | Safe re-runs; forensics |
| 74 | Vision module + GUI resolver: document capability + add smoke tests | M | 1d | M | L | vision_module.py, gui_resolver.py | Un-black-box two modules |
| 75 | Kokoro/whisper model files → download-on-first-run with checksum, not committed binaries | M | 1d | M | M | data/models/, phase_0/models | Repo size −GBs; clean licensing |
| 76 | requirements: split prod vs dev; pin with hashes (pip-tools) both repos | G,M | 3h | L | L | requirements*.txt | Reproducible, supply-chain-safer |
| 77 | numpy<2 pin: verify need, document why, or lift | G | 2h | L | L | requirements.txt | Avoids future resolver pain |
| 78 | Python 3.9→3.12 upgrade for Docker images (3.9 EOL Oct 2025) | G | 3h | M | M | Dockerfiles | Security patches; perf |
| 79 | Compose: resource limits + restart policies on all services | G | 1h | L | L | docker-compose.yml | Runaway-container protection |
| 80 | K8s manifests or Helm chart (deployment, HPA-ready after #17/#10) | G | 2-3d | M | M | +new dir | Cloud portability |
| 81 | Object storage / volume strategy for audit + cache in containerized deploys (currently container-local writes) | G | 4h | M | M | compose, config | No data loss on container recreate |
| 82 | Graceful shutdown: flush cache/audit on SIGTERM (lifespan hooks) | G | 3h | L | L | api/main.py | No truncated JSONL lines |
| 83 | Log levels via env; JSON logs to stdout in containers (12-factor) | G | 2h | L | L | core/logger.py | Aggregator-friendly |
| 84 | SLO doc: target p50/p99 for cached/uncached/judge paths + error budget | G | 3h | L | L | docs/ | SRE contract for the gateway |
| 85 | Alert rules (judge failure rate, fail-closed spike, cache corruption) once #29 lands | G | 4h | M | L | +rules file | Detects silent degradation |
| 86 | Streamlit admin: authentication gate before exposing flush/update buttons | G | 3h | L | L | ui/web_app.py | Admin surface protected |
| 87 | UX: block/restrict responses should return safe alternative message templates from policy, not hardcoded strings | G | 3h | L | L | policy.py, web_app.py | Product-quality refusals |
| 88 | HUD performance budget: lazy-load three.js scene, pause animations when idle | M | 1d | M | L | sentinal-ui/src/components/core | Battery/GPU friendliness |
| 89 | Accessibility pass on HUD (keyboard nav, reduced-motion, contrast) | M | 1-2d | M | L | sentinal-ui/src | Inclusive + judged demos better |
| 90 | Delete `archive/ui_legacy/node_modules` from disk; npm-install on demand | M | 30m | L | L | ~10⁴ files | Disk + indexer speed |
| 91 | CHANGELOG.md + conventional commits (both active repos) | G,M | 2h | L | L | +2 | Traceable evolution |
| 92 | CONTRIBUTING.md + PR template with security checklist | G | 2h | L | L | +2 | Review discipline |
| 93 | Architecture Decision Records (start with: file-state vs DB, fail-closed policy, role model) | G | 4h | L | L | docs/adr/ | Rationale survives author |
| 94 | Policy-authoring guide (JSON schema, threshold meanings, examples) | G | 4h | L | L | docs/ | Ops can tune without reading code |
| 95 | Threat-model doc (STRIDE on the gateway itself) | G | 1d | M | L | docs/ | Security roadmap grounded |
| 96 | Multimodal rails (`normalize_image/audio`) are stubs — implement real captioning/ASR or remove from README claims | G | 3-5d | H | M | core/multimodal.py | Claim/reality alignment |
| 97 | Embedding model upgrade eval (e.g. bge-m3 / gte) behind config flag, measured by #57 harness | G | 2d | M | M | core/embeddings.py | Detection quality headroom |
| 98 | Vector DB migration path (pgvector/Qdrant) documented + abstracted behind `ScalableVectorStore` interface | G | 2-3d | M | M | core/vector_store.py | True scalability beyond RAM |
| 99 | Merge desktop assistant's privacy_router with gateway's PII layer into one shared library package | A | 3-5d | H | M | new pkg + 2 repos | DRY across ecosystem; one tested privacy engine |
| 100 | Monorepo or org-level repo strategy decision (2 active repos + archive policy) | A | 1d | M | L | git only | Ends copy-paste evolution pattern |

**Sequencing note:** #1–#3 today; #4–#11 this week (security wave); #12–#30 next (correctness/CI wave); the rest by theme. Items #2/#50 unblock everything in Major project — do nothing else there first except #1/#3.

---

## 5. What is genuinely good (keep, don't refactor away)
Fail-closed judge arbitration and locked-HIGH cache; staged deterministic-first pipeline; lazy ML init for CI; privacy-aware local/cloud LLM routing; STT engineering rigor; Electron/React separation via ws adapter; the README's ambition (§20 structure, mermaid, benchmarks) — it just needs to match reality.
