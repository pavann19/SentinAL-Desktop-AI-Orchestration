# SentinAL v9.0 — System Report

## Identity
- **Project Name:** SentinAL (Sentinel + AI)
- **Internal Codename:** M.E.G.H.A. (Multi-Environment Generalized Handling Architecture)
- **Version:** v9.0 — Generalized OS Orchestration Engine
- **Platform:** Windows 10/11
- **Language:** Python 3.10+ (Backend), React + Vite (Frontend)
- **Server:** FastAPI + Uvicorn (ASGI), WebSocket full-duplex
- **Port:** Backend = 8000, Frontend = 5173

---

## Architecture — The 7 Layers

1. **INPUT** — Voice (Web Speech API wake word) or typed text from React UI
2. **GATEWAY** — `server.py`: FastAPI with WebSocket `/ws/agent`, REST `/api/command`, telemetry `/ws/telemetry`
3. **BRAIN** — `core/processor.py`: Ghost Protocol → Greeting Bypass → Privacy Router → LLM → Guardrails
4. **SANDBOX** — `core/validator.py`: Allowlist + Blocklist + Sandbox path enforcement
5. **ACTUATOR** — `services/executor.py`: Explorer Interceptor → SQLite Cache → ReAct Shell Loop → GUI Engine
6. **SERVICES** — TTS (`tts_service.py`), Search (`search_engine.py`), Vision (`vision_module.py`), Memory (`memory_manager.py`)
7. **OUTPUT** — Final response string → WebSocket → React UI + TTS audio playback

---

## All Source Files

| File | Purpose |
|------|---------|
| `server.py` | FastAPI WebSocket gateway, REST endpoints, lifecycle manager |
| `core/processor.py` | LLM intent extraction, Ghost Protocol, Privacy Router, Guardrails |
| `core/validator.py` | Security sandbox — allowlist, blocklist, path validation |
| `core/agent.py` | LangGraph ReAct tool-calling agent (alternative brain) |
| `core/memory_manager.py` | Dual SQLite DB — interaction history + URL cache |
| `core/search_engine.py` | Tavily API live web research |
| `core/vision_module.py` | Screenshot + llama3.2-vision screen verification |
| `core/logger.py` | JSON audit trail to `logs/system_logs.json` |
| `core/api_wrapper.py` | Synchronous REST pipeline wrapper (extract → validate → execute) |
| `services/executor.py` | OS command execution — shell, GUI, explorer, YouTube scraper |
| `services/tts_service.py` | Kokoro-ONNX offline text-to-speech engine |
| `tools/megha_indexer.py` | Standalone global drive path indexer → SQLite |
| `start_sentinal.ps1` | PowerShell launcher — kills processes, boots backend + frontend |
| `sentinal-ui/src/pages/UserDashboard.jsx` | Main React UI — voice engine, wake word, WebSocket, pipeline visualization |
| `sentinal-ui/src/pages/DevConsole.jsx` | SOC-style developer telemetry console |

---

## All 9 Intents Supported

| Intent | What It Does |
|--------|-------------|
| `ConversationalIntent` | General chat, greetings, knowledge Q&A — no OS action |
| `ContinuationIntent` | "Elaborate" / "continue" — re-queries LLM with stored context |
| `ApplicationLaunchIntent` | Opens apps via `os.startfile()` or `subprocess.Popen("start")` |
| `WebNavigationIntent` | Opens URLs via `webbrowser.open()` with mnemonic mapping (youtube, gmail, etc.) |
| `InformationRetrievalIntent` | Live research via Tavily API → LLM RAG synthesis |
| `GeneralizedOSIntent` | Multi-step shell + GUI action array — the universal actuator |
| `MediaStreamingIntent` | YouTube HTML scraper for direct video playback with autoplay=1 |
| `FileDeletionIntent` | Sandbox-checked file/folder deletion via shutil/os.remove |
| `UnknownIntent` | Fallback — asks user to rephrase |

---

## All Features (Complete List)

### Voice & Wake Word System (Frontend)
- **Wake word detection** — Listens for "Friday", "Jarvis", "Megha", "initiate protocol" using Web Speech API
- **2-Phase mic architecture** — Phase 1: Standby (wake word only), Phase 2: Active (captures command)
- **Inline query capture** — "Friday open my downloads" extracts "open my downloads" immediately after wake word
- **Text-based AEC (Acoustic Echo Cancellation)** — Detects when mic picks up the AI's own TTS voice and drops the echo
- **Hard interrupt** — Saying "stop", "halt", or "stand down" kills TTS audio and aborts pipeline
- **Phantom drop recovery** — Auto-restarts mic if Chrome kills it unexpectedly
- **Zero-latency greeting** — Speaks "Systems online. Good morning, Boss." immediately on wake word
- **Web Audio API visualizer** — Real-time frequency bars + dB + kHz stats on the UI

### LLM Intelligence (Backend)
- **3-Tier Privacy Router** — Regex drive patterns → sensitive folder names → action+system co-occurrence
- **Hybrid LLM routing** — Local Ollama (llama3.2) for private queries, Groq cloud (llama-3.3-70b) for general
- **Automatic fallback** — If Groq fails or key missing, falls back to local Ollama
- **SYSTEM_PROMPT** — 100+ line structured directive with OS context, JSON schema, sensory rules, examples
- **JSON cleaning** — Strips markdown code blocks, extracts outermost [ ] array from raw LLM output
- **Deterministic Guardrails** — Post-LLM: forcefully rewrites `dir`/`ls` → `explorer` for visual requests
- **Greeting bypass** — Exact-match frozen set skips LLM for "hi", "hello", etc.

### Ghost Protocol (Secret Developer Override)
- Trigger phrases: "initiate presentation protocol", "run diagnostic"
- Completely bypasses LLM — returns hardcoded 7-action GeneralizedOSIntent
- Creates MEGHA_Report.txt on Desktop, opens in Notepad, types live message via PyAutoGUI
- Guaranteed sub-50ms response — zero network dependency
- Framed as undocumented internal diagnostic, not a user feature

### Security Sandbox (validator.py)
- **ALLOWLIST_INTENTS** — Only 9 specific intent names permitted
- **SENSITIVE_TARGETS** — 19 dangerous keywords blocked: system32, rmdir, format, shutdown, taskkill, etc.
- **validate_sandbox()** — Resolves symlinks + `..` traversals via `os.path.realpath()`, blocks windows/system32 paths
- **Deep array inspection** — For GeneralizedOSIntent, iterates every action, scans each shell payload
- **Security audit log** — Violations logged to `logs/security_audit.log`
- **FileDeletionIntent confirmation flag** — Returns `requires_confirmation=True` for UI prompt
- **BLOCKED_KEYS** — Defined (win, alt, f4, del, esc, ctrl) — reserved for future enforcement

### Execution Engine (executor.py)
- **ReAct self-healing loop** — On shell failure, feeds stderr back to LLM, gets corrected command, retries up to 2x
- **Hard Halt** — After 2 failed retries, pipeline aborts entirely
- **Explorer Interceptor** — Detects `explorer` commands, uses native `os.startfile()` instead of subprocess
- **SQLite path resolution** — Queries `megha_path_cache.db` when LLM guesses wrong path
- **Cache HIT/MISS logging** — `[Memory] Cache HIT!` or `[Memory] Cache MISS`
- **GUI vs CLI routing** — Detects notepad/code/start/explorer prefixes, detaches GUI apps as separate processes
- **Stdout summarization** — Feeds terminal output to LLM for 1-2 sentence natural language summary for TTS
- **TTS bypass** — If speech_response contains "diagnostic" or no stdout, uses scripted response directly
- **YouTube scraper** — Scrapes YouTube HTML for video IDs, constructs direct playback URL with &autoplay=1
- **URL template learning** — Learns and caches platform URL templates in SQLite for future use
- **Mnemonic URL mapping** — youtube→youtube.com, gmail→mail.google.com, etc.
- **5-minute timeout** — subprocess.wait(timeout=300), kills hung processes
- **GUI automation** — click (with coordinates), type (with 2s focus wait), press/hotkey, scroll, sleep

### Zero-Latency Memory Cache (megha_indexer.py)
- **Global drive detection** — Scans A-Z drive letters via `os.path.exists()`
- **os.walk with in-place pruning** — Skips: Windows, Program Files, AppData, node_modules, .git, .venv, $Recycle.Bin, System Volume Information, __pycache__
- **Batched SQLite writes** — INSERT OR REPLACE every 500 records for 500x I/O reduction
- **Schema** — `folder_paths(folder_name TEXT, absolute_path TEXT PRIMARY KEY)`
- **Case-insensitive** — folder_name stored as lowercase

### Dual Database System
- **sentinal_memory.db** — interaction_history (audit trail) + url_cache (learned URL templates)
- **megha_path_cache.db** — folder_paths (pre-indexed drive map)
- **URL sanitization** — Only https://, must contain {query}, rejects http/javascript/data/file schemes
- **Thread-safe** — threading.Lock() on all read/write operations

### Text-to-Speech (tts_service.py)
- **Kokoro-ONNX engine** — Fully offline, no internet needed
- **Voice**: af_heart (American Female), 24000 Hz sample rate
- **Text sanitization** — Strips JSON, code blocks, shell commands, OS paths before speaking
- **Singleton pattern** — Model loaded once, reused on all subsequent calls
- **sounddevice playback** — Native audio output, waits for completion

### Vision Module (vision_module.py)
- **Screenshot capture** — pyautogui.screenshot() → base64 PNG
- **llama3.2-vision** — Local VLM queries via Ollama
- **Yes/No screen verification** — "Is Chrome open?" → TRUE/FALSE
- **Graceful degradation** — If vision model not downloaded, assumes TRUE and continues

### Live Research (search_engine.py)
- **Tavily API** — "basic" search depth, max 3 results
- **Hard timeout** — 15s enforced by asyncio.wait_for in server.py
- **Standardized return** — {context, results} on success, {error, code} on failure

### WebSocket Pipeline (server.py)
- **Full-duplex /ws/agent** — Real-time bidirectional command processing
- **Telemetry /ws/telemetry** — Streams last 10 log entries every 1s
- **Interrupt signal** — Frontend sends {"type":"interrupt"} to halt processing
- **ContinuationIntent branch** — Stores last_research_context for "elaborate" requests
- **LLM Verbosity Patch** — Forces 2-sentence summaries with "Shall I elaborate, Boss?"
- **Brain Dead Guard** — If LLM returns only UnknownIntents, responds gracefully
- **Hard timeouts** — Tavily=15s, LLM synthesis=30s
- **Lifespan manager** — Closes MemoryManager DB connection on shutdown

### Frontend UI (React + Vite)
- **UserDashboard.jsx** — Main interface with command input, pipeline stages, voice engine
- **DevConsole.jsx** — SOC-style telemetry console with live WebSocket log feed
- **4-stage pipeline visualization** — Perception → Cognition → Governance → Actuation
- **Color-coded states** — Amber (processing), Magenta (researching), Emerald (success), Red (failure), Cyan (idle)
- **Debounce lock** — isProcessingRef prevents double-submission
- **Exponential backoff** — WS reconnect: 1s → 2s → 4s → ... → 30s max
- **Framer Motion animations** — Smooth UI transitions
- **Lucide icons** — Mic, Shield, Globe, Check
- **REST heartbeat** — Polls /api/health every 3s for server status indicator

### Startup System (start_sentinal.ps1)
- Nuclear sweep — kills all python + node processes
- Manual .env parsing — injects variables into PowerShell session
- Launches Python backend in new window
- 3s sync delay before launching frontend
- Frontend: `npm run dev` (Vite dev server)

### LangGraph Agent (agent.py) — Alternative Brain
- **control_operating_system** tool — action/category/target dispatch
- **interact_with_screen** tool — PyAutoGUI with coordinate resolution
- **check_screen** tool — VLM screenshot verification
- **browser_control** tool — 3-phase autonomous browser automation (Planner → Validator → Controller + DOM Analyzer)
- **create_react_agent** — LangGraph with MemorySaver checkpointer

### Logging (logger.py)
- JSON append log — timestamp, input, intent, validation, execution
- Non-blocking — failures log to console, never crash pipeline
- Used by /api/logs and /ws/telemetry endpoints

---

## All Algorithms

| Algorithm | Location | How It Works |
|-----------|----------|-------------|
| Privacy 3-Tier Detection | processor.py | Regex → keyword set → co-occurrence check |
| Ghost Protocol Match | processor.py | Strip punctuation → substring match → return hardcoded payload |
| LLM JSON Cleaning | processor.py | Try code-block extraction → try greedy [ ] regex → json.loads |
| Deterministic Guardrail | processor.py | If visual request + dir/ls payload → rewrite to explorer |
| Intent Allowlist Scan | validator.py | Set membership check on intent name |
| Sensitive Keyword Scan | validator.py | Substring match on target + all shell payloads |
| Path Sandbox Resolution | validator.py | expandvars → realpath → normpath → check for windows/system32 |
| Explorer SQLite Lookup | executor.py | os.path.exists() check → SQLite SELECT by folder_name |
| ReAct Shell Healing | executor.py | Capture stderr → feed to LLM → get corrected command → retry |
| YouTube HTML Scrape | executor.py | urllib GET → regex findall watch?v= → construct direct URL |
| URL Template Learning | executor.py | Cache MISS → save LLM template → upsert to SQLite |
| Stdout Summarization | executor.py | Aggregate stdout → LLM summarize → return to TTS |
| Drive Detection | megha_indexer.py | Loop chr(65)-chr(90) + os.path.exists |
| In-Place Dir Pruning | megha_indexer.py | dirs[:] = [d for d if not in IGNORE_LIST] |
| Batched SQLite Write | megha_indexer.py | Accumulate 500 rows → executemany() → commit |
| URL Sanitization | memory_manager.py | Regex: must be https://, must contain {query} |
| TTS Text Sanitization | tts_service.py | Strip markdown → strip JSON → filter CLI lines → collapse newlines |
| Wake Word Fuzzy Match | UserDashboard.jsx | wakeWords.some(word => transcript.includes(word)) |
| Text-Based AEC | UserDashboard.jsx | Compare transcript vs AI output → drop if substring match |
| WS Exponential Backoff | UserDashboard.jsx | delay = min(delay * 2, 30000) |

---

## Environment Configuration (.env)

| Variable | Value | Purpose |
|----------|-------|---------|
| SENTINAL_PORT | 8000 | Backend server port |
| SENTINAL_UI_PORT | 5173 | Frontend dev server port |
| SENTINAL_HOST | 127.0.0.1 | Backend bind address |
| LLM_PROVIDER | groq | Primary LLM engine (groq or local) |
| GROQ_API_KEY | gsk_... | Groq cloud API key |
| TAVILY_API_KEY | tvly-... | Tavily search API key |
| OLLAMA_MODEL | llama3.2:latest | Local Ollama model name |
| GROQ_MODEL | llama-3.3-70b-versatile | Cloud Groq model name |

---

## Dependencies (requirements.txt)

faster-whisper, pyaudio, numpy, SpeechRecognition, langchain, langchain_ollama, langgraph, fastapi, uvicorn, pydantic, streamlit, textual, pyautogui, python-dotenv, kokoro-onnx, onnxruntime, sounddevice, soundfile, transformers, torch, accelerate, librosa, langchain-groq
