# server.py
# FastAPI Web Integration Layer for SentinAL
# Optimized for near-instant boot times and Global Project Sync (v2.4).

import sys
# Force UTF-8 console output on Windows to prevent UnicodeEncodeError crashes
# when any module prints non-ASCII characters (emojis, special symbols, etc.)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import os
import time

SERVER_START_TIME = time.time()
import json
import asyncio
import traceback
import socket
import psutil

# ── 1. GLOBAL CONFIG & SYNC (Master Lock) ───────────────────────────────────
def load_env_config():
    """Manual .env parser to keep startup time near zero without dependencies."""
    # SECURITY: default bind is loopback-only. This server exposes an endpoint
    # that executes real OS actions; binding 0.0.0.0 (the previous default)
    # published it to every interface, making it reachable from any host on the
    # same network. Override SENTINAL_HOST deliberately if remote access is
    # genuinely required — and only behind authentication and a trusted network.
    config = {"SENTINAL_PORT": "8000", "SENTINAL_HOST": "127.0.0.1"}
    env_path = ".env"
    if os.path.exists(env_path):
        try:
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, val = line.split("=", 1)
                        key, val = key.strip(), val.strip()
                        config[key] = val
                        os.environ[key] = val  # Push to global environment
            print(f"[SRE] Environment loaded: {list(config.keys())}")
        except Exception as e: 
            print(f"[SRE] Env Load Error: {e}")
    return config

SYNC_CONFIG = load_env_config()
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

SYSTEM_CONFIG = {
    "clearance": "ADMIN",
    "agent": "MEGHA",
    "active_skills": ["SYS_CONTROL", "FILE_OPS", "NET_SOCKET"]
}

import secrets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.websockets import WebSocketState
from pydantic import BaseModel
from contextlib import asynccontextmanager
from agentic_core.scheduler import task_manager

# ── NEW OS CORE SERVICES ──────────────────────────────────────────────────
from agentic_core.capability_registry import registry
from agentic_core.processor import _DEFAULT_APP_MAP_SEED
from system_services.system_state import state_manager
from interfaces.ui_bridge.conversation_manager import conversation_manager
from interfaces.voice.wake_engine import wake_engine

active_telemetry_clients = set()
active_agent_clients: dict = {}   # Fix 2.5: dict[ws → connect_time] for deterministic routing
TELEMETRY_PINGS = {}  # Track {websocket: last_ping_time}

# Fix 3.9: is_cloud reflects actual LLM provider — no longer hardcoded to True
IS_CLOUD = os.getenv("LLM_PROVIDER", "local").lower() in ("groq", "openai")

from interfaces.voice.nlp_correction import corrector

@asynccontextmanager
async def lifespan(app: FastAPI):
    """// System Lifecycle Manager"""
    task_manager.start()
    from interfaces.voice.stt_service import start_listening, stop_listening
    loop = asyncio.get_running_loop()

    # ── DB & STATE BOOTSTRAP ──
    try:
        registry.seed_defaults(_DEFAULT_APP_MAP_SEED)
        print("[SRE] Capability Registry seeded.")
    except Exception as e:
        print(f"[RELIABILITY ERROR] Registry seed fault: {e}")

    # ── REACTIVE TELEMETRY HOOK ──
    def on_state_broadcast(state):
        msg = {"type": "system_state", "state": state, "timestamp": time.time()}
        async def _broadcast():
            if loop.is_closed(): return
            for client in list(active_telemetry_clients):
                if client.client_state == WebSocketState.CONNECTED:
                    try: await safe_send_json(client, msg)
                    except Exception: active_telemetry_clients.discard(client)
        if not loop.is_closed():
            asyncio.run_coroutine_threadsafe(_broadcast(), loop)

    state_manager.on_state_change(on_state_broadcast)

    # ── PROCESS SUPERVISOR ──
    # Reconciles detached, long-running work (CodeAct scripts, installs) whose
    # completion the request/response cycle cannot observe — the request returns
    # long before the work finishes. One supervisor for the whole process, started
    # here alongside the other bootstrap steps, NOT one watcher per request.
    #
    # on_watch_resolved only NOTIFIES. It deliberately does not re-submit a
    # corrective command: anything that executes must re-enter through the front
    # of the pipeline (validation -> risk -> authorization -> policy -> HITL ->
    # sandbox) like any other request. A background component with its own
    # execution path would bypass every one of those gates.
    async def on_watch_resolved(resolution: dict):
        msg = {
            "type": "process_watch",
            "watch_id": resolution.get("watch_id"),
            "label": resolution.get("label"),
            "status": resolution.get("status"),
            "detail": resolution.get("detail", ""),
            "timestamp": time.time(),
        }
        for client in list(active_telemetry_clients):
            if client.client_state == WebSocketState.CONNECTED:
                try:
                    await safe_send_json(client, msg)
                except Exception:
                    active_telemetry_clients.discard(client)

    try:
        from agentic_core.process_supervisor import start_supervisor, stop_supervisor
        start_supervisor(on_resolved=on_watch_resolved)
        print("[SRE] Process supervisor started.")
    except Exception as e:
        print(f"[RELIABILITY ERROR] Process supervisor failed to start: {e}")
        stop_supervisor = None

    def on_stt_wake():
        conversation_manager.start_session()
        wake_text = wake_engine.get_wake_response(state_manager.get_snapshot())
        msg = {"type": "wake_ack", "message": wake_text, "timestamp": time.time()}
        async def _broadcast():
            if loop.is_closed(): return
            for client in list(active_telemetry_clients):
                if client.client_state == WebSocketState.CONNECTED:
                    try:
                        await safe_send_json(client, msg)
                    except Exception:
                        active_telemetry_clients.discard(client)
        if not loop.is_closed():
            asyncio.run_coroutine_threadsafe(_broadcast(), loop)
            async def _speak_ack():
                from interfaces.voice.tts_service import speak
                await asyncio.to_thread(speak, wake_text, 1.15, None, "FAST")
            asyncio.run_coroutine_threadsafe(_speak_ack(), loop)

    def on_stt_interrupt(text):
        async def _interrupt():
            print(f"[AUDIT] Voice interrupt received: {text}")
            await task_manager.interrupt_current()
            conversation_manager.end_session()
            for client in list(active_agent_clients):
                if client.client_state == WebSocketState.CONNECTED:
                    await safe_send_json(client, {"type": "interrupted", "message": "Stopped."})
        if not loop.is_closed():
            asyncio.run_coroutine_threadsafe(_interrupt(), loop)

    def on_stt_transcript(text):
        if not text: return
        import re
        if len(re.sub(r'[^a-zA-Z0-9]', '', text)) < 2:
            return
        print(f"[STT] Forwarding raw transcript: {text}")
        
        # Fix 2.5: Route to the most-recently connected agent client (deterministic)
        ws = max(active_agent_clients, key=active_agent_clients.get, default=None)
        
        async def _submit():
            if ws and ws.client_state == WebSocketState.CONNECTED:
                try:
                    await safe_send_json(ws, {"type": "execution_step", "message": f"Microphone (Raw): {text}", "stage": "perception"})
                    await asyncio.sleep(0.1) # Small delay for UI
                except Exception:
                    active_agent_clients.discard(ws)
                
            clean_text = await asyncio.to_thread(corrector.correct_text, text)
            
            if clean_text != text:
                print(f"[STT] Corrected transcript: {clean_text}")
                if ws and ws.client_state == WebSocketState.CONNECTED:
                    try:
                        await safe_send_json(ws, {"type": "execution_step", "message": f"Microphone (Polished): {clean_text}", "stage": "perception"})
                    except Exception:
                        active_agent_clients.pop(ws, None)  # Fix 2.5: dict removal
            
            conversation_manager.update_interaction()
            # Use the global execute_agent_task already defined in this file
            await task_manager.submit_task(clean_text, ws, execute_agent_task)

        if not loop.is_closed():
            asyncio.run_coroutine_threadsafe(_submit(), loop)

    async def _watchdog():
        """Culls dead telemetry clients that haven't responded to the event loop."""
        while not loop.is_closed():
            now = time.time()
            dead = [ws for ws, lp in TELEMETRY_PINGS.items() if (now - lp) > 10.0]
            for ws in dead:
                print(f"[RELIABILITY] Heartbeat LOST for telemetry client. Culling.")
                TELEMETRY_PINGS.pop(ws, None)
                active_telemetry_clients.discard(ws)
            await asyncio.sleep(5)

    # Run STT listener in daemon thread
    start_listening(on_transcript=on_stt_transcript, on_wake=on_stt_wake, on_interrupt=on_stt_interrupt)
    loop.create_task(_watchdog())
    loop.create_task(conversation_manager.heartbeat())

    yield
    try:
        if stop_supervisor is not None:
            await stop_supervisor()
            print("[SRE] Process supervisor stopped.")
    except Exception as e:
        print(f"[RELIABILITY ERROR] Supervisor shutdown fault: {e}")
    try:
        stop_listening()
        from agentic_core.executor import memory
        if memory: memory.close()
        print("[SRE] Memory Manager closed.")
    except Exception as e:
        print(f"[RELIABILITY ERROR] Shutdown fault: {e}")

app = FastAPI(title="SentinAL API Server v2.4", lifespan=lifespan)

# ── Rate Limiting ──────────────────────────────────────────────────────────
# In-memory, per-client-IP limiter (no Redis needed — this is a single-machine
# deployment; the whole point of a distributed backend would be moot here).
# Rationale: the bearer-token auth on /api/command stops *unauthenticated*
# abuse, but a valid token doesn't protect against a runaway client loop, a
# buggy retry, or a script hammering the endpoint — each call can trigger a
# real OS action and/or an LLM request, both with real cost/side effects.
# 429 Too Many Requests is returned once the limit is exceeded, handled by
# slowapi's default handler.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Fix 1.3: CORS locked to localhost only (was open to all origins)
_UI_PORT = int(os.getenv("SENTINAL_UI_PORT", "5173"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{_UI_PORT}",
        f"http://127.0.0.1:{_UI_PORT}",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Local API Authentication ─────────────────────────────────────────────────
# SECURITY: /api/command executes real OS actions. CORS alone does NOT protect
# it — CORS is a browser-enforced policy, so any non-browser caller (curl, a
# script, another local process) bypasses it entirely. Combined with the
# previous default bind of 0.0.0.0 (all interfaces, now 127.0.0.1 — see the
# __main__ block), this endpoint was reachable and executable without
# credentials from any host on the same network.
#
# Mitigation: a bearer token required on every state-changing or
# information-disclosing REST endpoint. The token is read from
# SENTINAL_API_TOKEN; if unset, one is generated at startup and written to
# .sentinal_token (gitignored) so a local UI/CLI can read it, and printed once
# to the console. Health checks stay unauthenticated so process supervisors and
# container health probes keep working.
_TOKEN_FILE = ".sentinal_token"


def _resolve_api_token() -> str:
    """Returns the API token, generating and persisting one if not configured."""
    token = os.getenv("SENTINAL_API_TOKEN", "").strip()
    if token:
        return token
    try:
        if os.path.exists(_TOKEN_FILE):
            with open(_TOKEN_FILE, "r", encoding="utf-8") as fh:
                existing = fh.read().strip()
            if existing:
                return existing
    except Exception as exc:
        print(f"[SECURITY] Could not read {_TOKEN_FILE}: {exc}")

    generated = secrets.token_urlsafe(32)
    try:
        with open(_TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(generated)
        print(f"[SECURITY] Generated a new local API token -> {_TOKEN_FILE}")
    except Exception as exc:
        # Non-fatal: the token still works for this process, it just is not
        # persisted. Failing closed here would make the server unstartable on a
        # read-only filesystem, which is a worse outcome than an ephemeral token.
        print(f"[SECURITY] Could not persist API token ({exc}); using an in-memory token.")
    return generated


API_TOKEN = _resolve_api_token()


async def require_api_token(authorization: str = Header(default="")) -> None:
    """FastAPI dependency: enforces `Authorization: Bearer <token>`.

    Uses secrets.compare_digest to avoid leaking the token through response
    timing. Raises 401 rather than 403 so a missing credential is distinguishable
    from a rejected one in logs.
    """
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    if not secrets.compare_digest(presented.strip(), API_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bearer token.")


@app.get("/")
@app.get("/health")
@app.get("/api/health")
async def health_check():
    """// REST API Health Monitor (intentionally unauthenticated)"""
    return {"status": "online", "version": "2.4.2"}

class CommandRequest(BaseModel):
    prompt: str

# ─────────────────────────────────────────────────────────────────────────────
# 3. REST Endpoint: Command Processing
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/command", dependencies=[Depends(require_api_token)])
@limiter.limit("30/minute")
async def handle_command(req: CommandRequest, request: Request):
    """// REST Execution Endpoint (Legacy Interface) — requires bearer token, rate-limited"""
    try:
        from capabilities.system.api_wrapper import process_command
        result = await process_command(req.prompt)  # process_command is now async (Fix 3.12)
        return result
    except Exception as e:
        return {"input": req.prompt, "steps": [], "validation": "Error", "execution": "Error", "response": str(e)}

@app.get("/api/logs", dependencies=[Depends(require_api_token)])
@limiter.limit("60/minute")
async def get_logs(request: Request):
    """// Diagnostic Log Retrieval — requires bearer token, rate-limited"""
    return _read_last_10_logs()

def _read_last_10_logs():
    """// Log File Reader Utility"""
    log_path = os.path.join("logs", "system_logs.json")
    if not os.path.exists(log_path): return []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data[-10:] if data else []
    except Exception: return []

# ─────────────────────────────────────────────────────────────────────────────
# 4. WebSocket Endpoints (Telemetry, Agent, Voice)
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """// Real-time System Telemetry Stream"""
    await websocket.accept()
    active_telemetry_clients.add(websocket)
    try:
        while True:
            logs = await asyncio.to_thread(_read_last_10_logs)
            last_status = logs[-1].get("execution_status", "Idle") if (isinstance(logs, list) and len(logs) > 0) else "Idle"
            
            # ── Dynamic GPU & Thermals Telemetry ──
            gpu_load = None
            cpu_temp = None
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu_load = gpus[0].load * 100
            except Exception:
                pass
                
            try:
                import wmi
                w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                temperature_infos = w.Sensor()
                for sensor in temperature_infos:
                    if sensor.SensorType==u'Temperature' and 'cpu' in sensor.Identifier.lower():
                        cpu_temp = float(sensor.Value)
                        break
            except Exception:
                pass

            hardware = {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "ram_percent": psutil.virtual_memory().percent,
                "gpu_percent": gpu_load,
                "temperature": cpu_temp
            }
            
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
            logs_dir = os.path.join(root_dir, "logs")
            core_dir = os.path.join(root_dir, "core")
            
            def count_files(p):
                return len([f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))]) if os.path.exists(p) else 0

            total_files = count_files(root_dir) + count_files(logs_dir) + count_files(core_dir)

            environment = {
                "directories": [root_dir, logs_dir, core_dir],
                "file_count": total_files
            }
            
            uptime_seconds = time.time() - SERVER_START_TIME
            uptime_pct = min(99.99, 99.0 + (uptime_seconds / 86400)) 

            # ── Dynamic System Assessment ──
            cpu_val = hardware["cpu_percent"]
            ram_val = hardware["ram_percent"]
            
            # 1. Threat Level Assessment
            if cpu_val > 95 or ram_val > 98:
                threat = "CRITICAL"
            elif cpu_val > 90 or ram_val > 90:
                threat = "HIGH"
            elif cpu_val > 70:
                threat = "ELEVATED"
            else:
                threat = "ZERO"

            # 2. AI Core Status (based on TaskManager load & memory)
            if task_manager.current_task_id:
                core_status = "EXECUTING"
            elif cpu_val > 85:
                core_status = "STRAINED"
            else:
                core_status = "OPTIMAL"

            # 3. Dynamic Clearance (derived from mode/state)
            clearance = "ADMIN" if uptime_seconds > 60 else "GUEST"

            system_stats = {
                "uptime_percent": round(uptime_pct, 4),
                "ai_core_status": core_status,
                "threat_level": threat,
                "build_version": "v10.1.5-STABLE"
            }
            
            # Sync Config with Dynamic Clearance
            dynamic_config = SYSTEM_CONFIG.copy()
            dynamic_config["clearance"] = clearance
            
            if websocket.client_state == WebSocketState.CONNECTED:
                TELEMETRY_PINGS[websocket] = time.time()
                await safe_send_json(websocket, {
                    "latest_logs": logs,
                    "last_execution_status": last_status,
                    "hardware": hardware,
                    "environment": environment,
                    "governance": dynamic_config,
                    "system": system_stats
                })
            else:
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[RELIABILITY ERROR] Telemetry Loop Fault: {e}")
    finally:
        TELEMETRY_PINGS.pop(websocket, None)
        active_telemetry_clients.discard(websocket)

# ── Global Session Memory (Shared across tasks) ──
SESSION_MEMORY = {
    "last_research_context": "",
    "last_search_query": ""
}

async def safe_send_json(websocket: WebSocket, payload: dict):
    if websocket is None:
        return
    if websocket.client_state == WebSocketState.CONNECTED:
        try:
            await websocket.send_json(payload)
        except RuntimeError:
            pass # ASGI Connection dropped mid-send
        except Exception as e:
            print(f"[RELIABILITY ERROR] [WS SEND ERROR] {type(e).__name__}: {e}")

 
async def finalize_mission(data: dict | str, websocket: WebSocket, cancel_event: asyncio.Event):
    """
    CENTRALIZED RESPONSE GUARANTEE LAYER
    Standardizes payload structure and enforces the TTS lifecycle.
    """
    if cancel_event.is_set(): return

    # 1. Normalize Response
    if isinstance(data, str):
        final_text = data
        speech_text = data
    else:
        final_text = data.get("final_response", "")
        speech_text = data.get("speech_response", final_text)

    # 2. Emit Standardized WebSocket Response
    await safe_send_json(websocket, {
        "type": "final_response",
        "message": final_text,
        "final_response": final_text,
        "speech_response": speech_text,
        "is_cloud": IS_CLOUD  # Fix 3.9: reflects actual LLM provider
    })

    # 3. Enforce Speech Sequence
    if speech_text and not cancel_event.is_set():
        from interfaces.voice.tts_service import speak
        state_manager.update_state(is_listening=True)
        await safe_send_json(websocket, {"type": "speech_start"})
        await asyncio.to_thread(speak, speech_text, 1.0, cancel_event, "HQ")
        await safe_send_json(websocket, {"type": "speech_end"})

async def execute_agent_task(prompt: str, websocket: WebSocket, cancel_event: asyncio.Event):
    """
    Decoupled execution payload. Run safely via TaskManager.
    """
    if cancel_event.is_set(): return
    try:
        # -1. Input Normalization
        prompt_lower = prompt.lower().strip()
        normalization_map = {
            "search for": "search",
            "look up": "search",
            "find": "search"
        }
        for old, new in normalization_map.items():
            if prompt_lower.startswith(old):
                prompt_lower = prompt_lower.replace(old, new, 1)
                break
                
        # 0. Fast-Path OS Command Router (Deterministic Bypass)
        import re

        from datetime import datetime
        
        fast_path_result = None
        # Use bulletproof substring matching for deterministic bypasses
        if any(x in prompt_lower for x in ["what time is it", "what is the time", "current time", "tell me the time"]) or prompt_lower == "time":
            fast_path_result = f"The time is {datetime.now().strftime('%I:%M %p')}."
        elif any(x in prompt_lower for x in ["what is the date", "what's the date", "whats the date", "current date", "tell me the date"]) or prompt_lower == "date":
            fast_path_result = f"Today's date is {datetime.now().strftime('%B %d, %Y')}."
        elif any(x in prompt_lower for x in ["what day is it", "what is the day", "what day of the week is it", "today"]) or prompt_lower == "day":
            fast_path_result = f"Today is {datetime.now().strftime('%A')}."
        
        if fast_path_result:
            await safe_send_json(websocket, {"type": "execution_step", "message": "Fast-Path: Retrieving direct OS system result...", "status": "pending", "stage": "actuation"})
            await finalize_mission(fast_path_result, websocket, cancel_event)
            return

        # 1. Start processing immediately
        await safe_send_json(websocket, {"type": "execution_step", "message": "Neural Link: Establishing mission parameters...", "status": "pending", "stage": "perception",
            "step_index": 1, "step_total": 4, "step_label": "Perception", "step_icon": "👁"})
        if cancel_event.is_set(): return
        
        # 2. Extract Intent (Using normalized prompt)
        from agentic_core.processor import extract_intent
        steps = await asyncio.to_thread(extract_intent, prompt_lower)
        if cancel_event.is_set(): return
        
        # 3. Aegis Governance
        from agentic_core.validator import validate_steps
        await safe_send_json(websocket, {"type": "execution_step", "message": "Aegis: Verifying governance policy...", "status": "pending", "stage": "governance",
            "step_index": 2, "step_total": 4, "step_label": "Governance", "step_icon": "🛡"})
        is_valid, validation_msg, _ = await asyncio.to_thread(validate_steps, steps)
        if cancel_event.is_set(): return
        
        if not is_valid:
            await finalize_mission(f"Security Block: {validation_msg}", websocket, cancel_event)
            return

        # 4. Neural Memory Branch
        is_continuation = any(s.get("intent") == "ContinuationIntent" for s in steps)
        if is_continuation:
            if not SESSION_MEMORY["last_research_context"]:
                await finalize_mission("I have no previous context to elaborate on, Boss.", websocket, cancel_event)
                return

            await safe_send_json(websocket, {"type": "execution_step", "message": "Neural Memory: Accessing previous fact layer context...", "status": "pending", "stage": "researching"})
            
            from agentic_core.processor import _get_routing_llm
            today = datetime.now().strftime("%A, %B %d, %Y")
            rag_prompt = f"Date: {today}. Query: {SESSION_MEMORY['last_search_query']}. Context: {SESSION_MEMORY['last_research_context']}. You are a tactical AI parsing previous Intel. Provide the FULL details and exhaustive elaboration that you previously summarized."
            
            llm = _get_routing_llm(SESSION_MEMORY['last_search_query'])
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(llm.invoke, [("human", rag_prompt)]),
                    timeout=30.0
                )
                final_answer = response.content.strip()
                if not final_answer:
                    final_answer = "The neural memory returned an empty response."
            except asyncio.TimeoutError:
                await safe_send_json(websocket, {"type": "error", "message": "Neural Memory Timeout: Synthesis exceeded 30s."})
                return

            if cancel_event.is_set(): return
            await finalize_mission(final_answer, websocket, cancel_event)
            return

        # 5. Neural Research Branch
        is_research = any(s.get("intent") == "InformationRetrievalIntent" for s in steps)
        all_unknown = all(s.get("intent") == "UnknownIntent" for s in steps) if steps else True
        if all_unknown:
            await safe_send_json(websocket, {"type": "execution_step", "message": "Aegis: Confidence too low. Requesting clarification...", "status": "pending", "stage": "governance"})
            from agentic_core.processor import _get_routing_llm
            llm = _get_routing_llm("Clarification pass")
            clarify_prompt = f"The user said: '{prompt}'. The system is unsure of their intent because the semantic confidence was too low. Generate a very short, polite, conversational clarification question asking what they want to do or if they meant to run a specific command. Do not execute anything or answer any questions. Keep it to one exact sentence."
            try:
                resp = await asyncio.to_thread(llm.invoke, [("system", clarify_prompt)])
                clarification = resp.content.strip()
            except Exception:
                clarification = "I didn't quite catch your intent. Could you rephrase that for me?"
            
            await finalize_mission(clarification, websocket, cancel_event)
            return
            
        final_answer = ""
        if is_research:
            search_query = next((s.get("target") for s in steps if s.get("intent") == "InformationRetrievalIntent"), prompt)
            
            # --- CLOUD LEAK PATCH: Security Governance ---
            from system_services.privacy_router import privacy_guard
            if privacy_guard.analyze(search_query)["route"] == "local":
                await safe_send_json(websocket, {"type": "execution_step", "message": "Aegis: Blocked. Cannot pass local entities to Cloud Search.", "status": "failed", "stage": "governance"})
                await finalize_mission("Security Block: I cannot perform web searches containing private system paths or sensitive data.", websocket, cancel_event)
                return
            
            await safe_send_json(websocket, {"type": "execution_step", "message": f"Neural Research: Querying fact layer for '{search_query}'...", "status": "pending", "stage": "researching"})
            await asyncio.sleep(1.0)
            if cancel_event.is_set(): return

            from capabilities.web.search_engine import get_live_research
            start_time = time.perf_counter()
            try:
                search_data = await asyncio.wait_for(
                    asyncio.to_thread(get_live_research, search_query),
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                await safe_send_json(websocket, {"type": "error", "message": "Neural Link Timeout: Tavily search exceeded 15s. Please retry."})
                return
                
            if "error" in search_data:
                # GRACEFUL DEGRADATION: If search fails, notify user and fallback to LLM knowledge
                await safe_send_json(websocket, {"type": "execution_step", "message": f"Neural Link Offline: {search_data['error']}. Falling back to internal knowledge...", "status": "pending", "stage": "researching"})
                context = "System: Live research failed. Provide a briefing based only on your current internal neural parameters."
            else:
                context = search_data.get("context", "")
                SESSION_MEMORY["last_research_context"] = context
                SESSION_MEMORY["last_search_query"] = search_query

            from agentic_core.processor import _get_routing_llm
            from datetime import datetime
            today = datetime.now().strftime("%A, %B %d, %Y")
            
            strict_rule = " CRITICAL RULE: You are a tactical AI. Your initial response MUST be a 2-sentence high-level summary. End your summary with the exact phrase: 'Shall I elaborate, Boss?'. Do NOT output the full details unless the user's prompt explicitly contains the word 'continue', 'elaborate', or 'yes'."
            rag_prompt = f"Date: {today}. Query: {search_query}. Context: {context}. Brief the user concisely.{strict_rule}"
            
            await safe_send_json(websocket, {"type": "execution_step", "message": "Neural Synthesis: Compiling briefing...", "status": "pending", "stage": "researching"})
            if cancel_event.is_set(): return

            llm = _get_routing_llm(search_query)
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(llm.invoke, [("human", rag_prompt)]),
                    timeout=30.0
                )
                final_answer = response.content.strip()
                if not final_answer:
                    final_answer = "The neural synthesis returned an empty response. Please retry your query."
            except asyncio.TimeoutError:
                await safe_send_json(websocket, {"type": "error", "message": "Neural Synthesis Timeout: LLM generation exceeded 30s."})
                return
        
        else:
            from agentic_core.executor import execute_pipeline
            total_steps = len(steps) + 3  # perception + governance + each plan step
            await safe_send_json(websocket, {"type": "execution_step", "message": f"Actuation: Dispatching {len(steps)} command(s)...", "status": "pending", "stage": "actuation",
                "step_index": 3, "step_total": total_steps, "step_label": "Actuation", "step_icon": "⚡"})
            # Emit per-step actuation progress messages
            for i, step_plan in enumerate(steps):
                if cancel_event.is_set(): return
                intent_name = step_plan.get('intent', 'Task')
                target_name = step_plan.get('target', step_plan.get('packages', ''))
                label = f"{intent_name.replace('Intent', '')}: {target_name}" if target_name else intent_name.replace('Intent', '')
                icon_map = {
                    'ApplicationLaunchIntent': '🚀',
                    'GeneralizedOSIntent': '💻',
                    'InformationRetrievalIntent': '🔍',
                    'WebNavigationIntent': '🌐',
                    'FileDeletionIntent': '🗑',
                    'ProcessManagementIntent': '⚙',
                    'ProjectScaffoldIntent': '🏗',
                    'DependencyInstallIntent': '📦',
                    'ConversationalIntent': '💬',
                    'CodeActIntent': '👨‍💻',
                    'AcademicResearchIntent': '📚',
                    'DataModelingIntent': '📊',
                    'SysUtilityIntent': '🎛',
                    'SchedulerIntent': '📅',
                    'MediaControlIntent': '🎵',
                    'WindowManagementIntent': '🪟',
                    'DictationIntent': '🗣️',
                }
                icon = icon_map.get(intent_name, '▶')
                await safe_send_json(websocket, {"type": "execution_step",
                    "message": f"Executing: {label}",
                    "status": "pending", "stage": "actuation",
                    "step_index": 3 + i + 1, "step_total": total_steps,
                    "step_label": label, "step_icon": icon})
            if cancel_event.is_set(): return
            final_answer = await asyncio.to_thread(execute_pipeline, steps, cancel_event)


        if cancel_event.is_set(): return
        
        # ── TRACKING FINAL STATE ──
        state_manager.update_state(
            last_intent=steps[0].get("intent") if steps else "ConversationalIntent",
            last_target=steps[0].get("target") if steps else "N/A",
            last_execution_status="Success"
        )

        await finalize_mission(final_answer, websocket, cancel_event)

    except Exception as inner_e:
        # GLOBAL ERROR BOUNDARY: Always log and return a safe, operational response to the UI
        print(f"[SRE] CRITICAL SYSTEM FAULT: {str(inner_e)}")
        import traceback
        traceback.print_exc()
        try:
            await finalize_mission("I encountered an issue, but I'm still operational.", websocket, cancel_event)
        except Exception:
            pass  # Intentional fallback boundary


@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    """// Full-Duplex Agent Brain Pipeline (v9.0 Hybrid)"""
    await websocket.accept()
    active_agent_clients[websocket] = time.time()  # Fix 2.5: track connect time for routing
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                
                if msg.get("type") == "interrupt":
                    await task_manager.interrupt_current()
                    conversation_manager.end_session()
                    await safe_send_json(websocket, {"type": "interrupted", "message": "Stopped."})
                    continue
                    
            except json.JSONDecodeError: continue
            
            prompt = msg.get("text", msg.get("prompt", "")).strip()
            if not prompt:
                await safe_send_json(websocket, {"type": "error", "message": "Command cannot be empty."})
                continue
                
            print(f"[AUDIT] Mission Received: '{prompt}'")
            
            # Submit securely to the task manager instead of spawning an untethered thread
            await task_manager.submit_task(prompt, websocket, execute_agent_task)

    except WebSocketDisconnect:
        pass  # Standard disconnect
    except Exception as e:
        print(f"[RELIABILITY ERROR] Agent Loop Fault: {e}")
    finally:
        await task_manager.cancel_tasks_for_websocket(websocket)
        active_agent_clients.pop(websocket, None)  # Fix 2.5: dict-based removal
        try:
            await websocket.close()
        except Exception:
            pass  # Client already gone

# ─────────────────────────────────────────────────────────────────────────────
# 8. Optimized Direct Launch
# ─────────────────────────────────────────────────────────────────────────────
def __main_entry__():
    """Console-script entry point (`sentinal` command, see pyproject.toml)."""
    import uvicorn
    port = int(SYNC_CONFIG.get("SENTINAL_PORT", 8000))
    # SECURITY: loopback-only default — see load_env_config() for rationale.
    host = SYNC_CONFIG.get("SENTINAL_HOST", "127.0.0.1")
    print(f"[SRE] SentinAL Core v9.0 online at http://{host}:{port}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"[SECURITY] WARNING: bound to {host}, not loopback. /api/command executes "
            f"real OS actions — ensure this network is trusted and SENTINAL_API_TOKEN is set."
        )
    print(f"[SECURITY] REST API token required for /api/command and /api/logs (see {_TOKEN_FILE}).")
    uvicorn.run("main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    __main_entry__()
