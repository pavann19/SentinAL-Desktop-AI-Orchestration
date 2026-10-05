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
import asyncio
import json

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
    "clearance": "LOCAL USER",
    "agent": "MEGHA",
    "active_skills": ["SYS_CONTROL", "FILE_OPS", "NET_SOCKET"]
}

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.websockets import WebSocketState

# ── NEW OS CORE SERVICES ──────────────────────────────────────────────────
from agentic_core.capability_registry import registry
from agentic_core.processor import _DEFAULT_APP_MAP_SEED
from agentic_core.scheduler import task_manager
from interfaces.ui_bridge.conversation_manager import conversation_manager
from interfaces.voice.wake_engine import wake_engine
from system_services.system_state import state_manager

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

    # ── EVENT BUS (S6 — time triggers) ──
    # Fires the scheduled_tasks.due_at rows SchedulerIntent persists but its
    # handler openly says it can't yet deliver.
    #   kind == 'reminder' (default, increment 1): ONLY notify — like
    #     on_watch_resolved above, no pipeline, no action.
    #   kind == 'goal' (increment 2): run it through the pipeline with
    #     autonomous=True (broker denies T2/T3, tighter budget), but ONLY when
    #     SENTINAL_AUTONOMOUS_GOALS_ENABLED. Off by default; nothing currently
    #     creates a 'goal' row, so this path is inert on a fresh install.
    _autonomous_goals_on = os.getenv(
        "SENTINAL_AUTONOMOUS_GOALS_ENABLED", "false"
    ).strip().lower() not in ("0", "false", "no", "")

    async def _broadcast_telemetry(msg: dict):
        for client in list(active_telemetry_clients):
            if client.client_state == WebSocketState.CONNECTED:
                try:
                    await safe_send_json(client, msg)
                except Exception:
                    active_telemetry_clients.discard(client)

    async def _run_autonomous_goal(description: str):
        from capabilities.system.api_wrapper import process_command
        return await process_command(description, autonomous=True)

    try:
        from agentic_core.event_bus import (
            make_event_handler,
            start_event_bus,
            stop_event_bus,
        )
        start_event_bus(on_event=make_event_handler(
            broadcast=_broadcast_telemetry,
            run_goal=_run_autonomous_goal,
            autonomous_goals_on=_autonomous_goals_on,
        ))
        print(f"[SRE] Event bus started (autonomous goals: {'ON' if _autonomous_goals_on else 'off'}).")
    except Exception as e:
        print(f"[RELIABILITY ERROR] Event bus failed to start: {e}")
        stop_event_bus = None

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
                    active_agent_clients.pop(ws, None)
                
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
                print("[RELIABILITY] Heartbeat LOST for telemetry client. Culling.")
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
        if stop_event_bus is not None:
            await stop_event_bus()
            print("[SRE] Event bus stopped.")
    except Exception as e:
        print(f"[RELIABILITY ERROR] Event bus shutdown fault: {e}")
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
    if not secrets.compare_digest(presented.strip().encode("utf-8"), API_TOKEN.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid bearer token.")


_WS_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


async def authenticate_websocket(websocket: WebSocket) -> bool:
    """Reject foreign browser origins and require a bounded first-frame handshake."""
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in _WS_ORIGINS:
        await websocket.close(code=1008)
        return False
    await websocket.accept()
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        token = message.get("token") if isinstance(message, dict) else None
        valid = (
            isinstance(message, dict) and message.get("type") == "authenticate"
            and isinstance(token, str) and len(token) <= 4096
            and secrets.compare_digest(token.encode("utf-8"), API_TOKEN.encode("utf-8"))
        )
    except (TimeoutError, ValueError, WebSocketDisconnect):
        valid = False
    if not valid:
        await websocket.close(code=1008)
        return False
    await websocket.send_json({"type": "authenticated"})
    return True


@app.get("/")
@app.get("/health")
@app.get("/api/health")
async def health_check():
    """// REST API Health Monitor (intentionally unauthenticated)"""
    return {"status": "online", "version": "2.4.2"}

class CommandRequest(BaseModel):
    prompt: str
    # P2-5 direct-human confirm channel. When SENTINAL_REQUIRE_CONFIRMATION is
    # on, a T2/T3 request first returns execution="PendingConfirmation" with a
    # confirm_token; resend the same prompt with that token to proceed.
    confirm_token: str | None = None

# ─────────────────────────────────────────────────────────────────────────────
# 3. REST Endpoint: Command Processing
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/command", dependencies=[Depends(require_api_token)])
@limiter.limit("30/minute")
async def handle_command(req: CommandRequest, request: Request):
    """// REST Execution Endpoint (Legacy Interface) — requires bearer token, rate-limited"""
    try:
        from capabilities.system.api_wrapper import process_command
        result = await process_command(req.prompt, confirm_token=req.confirm_token)
        return result
    except Exception as e:
        return {"input": req.prompt, "steps": [], "validation": "Error", "execution": "Error", "response": str(e)}

@app.get("/api/logs", dependencies=[Depends(require_api_token)])
@limiter.limit("60/minute")
async def get_logs(request: Request):
    """// Diagnostic Log Retrieval — requires bearer token, rate-limited"""
    return _read_last_10_logs()

@app.get("/api/tasks", dependencies=[Depends(require_api_token)])
@limiter.limit("60/minute")
async def list_tasks_endpoint(request: Request):
    """// Background Task Status (list) — requires bearer token, rate-limited.
    Pure read over process_supervisor's existing watch table; pending tasks
    first, then the most recently resolved."""
    from agentic_core.process_supervisor import list_tasks
    return await asyncio.to_thread(list_tasks)

@app.get("/api/tasks/{watch_id}", dependencies=[Depends(require_api_token)])
@limiter.limit("60/minute")
async def get_task_endpoint(watch_id: str, request: Request):
    """// Background Task Status (single) — requires bearer token, rate-limited."""
    from agentic_core.process_supervisor import get_task_status
    task = await asyncio.to_thread(get_task_status, watch_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task

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
    if not await authenticate_websocket(websocket):
        return
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
                    if sensor.SensorType=='Temperature' and 'cpu' in sensor.Identifier.lower():
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
            
            system_stats = build_system_telemetry(hardware)
            dynamic_config = SYSTEM_CONFIG.copy()

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
def build_system_telemetry(hardware: dict) -> dict:
    """Measured process uptime and resource load; no availability or threat claim."""
    cpu = hardware["cpu_percent"]
    ram = hardware["ram_percent"]
    load = "CRITICAL" if cpu > 95 or ram > 98 else "HIGH" if cpu > 90 or ram > 90 else "ELEVATED" if cpu > 70 else "NORMAL"
    core = "EXECUTING" if task_manager.current_task_id else "STRAINED" if cpu > 85 else "IDLE"
    return {
        "uptime_seconds": max(0.0, time.time() - SERVER_START_TIME),
        "ai_core_status": core,
        "resource_load": load,
        "build_version": "9.0.0-prototype",
    }


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
        final_text = data.get("response", data.get("final_response", ""))
        speech_text = data.get("speech_response", final_text)

    # 2. Emit Standardized WebSocket Response
    await safe_send_json(websocket, {
        "type": "final_response",
        "message": final_text,
        "final_response": final_text,
        "speech_response": speech_text,
        "execution": data.get("execution", "Success") if isinstance(data, dict) else "Success",
        "failure_category": data.get("failure_category") if isinstance(data, dict) else None,
        "is_cloud": IS_CLOUD  # Fix 3.9: reflects actual LLM provider
    })

    # 3. Enforce Speech Sequence
    if speech_text and not cancel_event.is_set():
        from interfaces.voice.tts_service import speak
        state_manager.update_state(is_listening=True)
        await safe_send_json(websocket, {"type": "speech_start"})
        await asyncio.to_thread(speak, speech_text, 1.0, cancel_event, "HQ")
        await safe_send_json(websocket, {"type": "speech_end"})

async def execute_agent_task(prompt: str, websocket: WebSocket, cancel_event: asyncio.Event,
                             confirm_token: str | None = None):
    """Use the same policy, confirmation and observation pipeline as the REST API."""
    if cancel_event.is_set():
        return
    from capabilities.system.api_wrapper import process_command
    await safe_send_json(websocket, {"type": "execution_step", "message": "Validating request", "stage": "governance"})
    result = await process_command(prompt, confirm_token=confirm_token, cancel_event=cancel_event)
    if cancel_event.is_set():
        return
    if result.get("execution") == "PendingConfirmation":
        await safe_send_json(websocket, {
            "type": "confirmation_required", "message": result.get("response", ""),
            "prompt": prompt, "confirm_token": result["confirm_token"],
        })
        return
    success = result.get("execution") == "Success"
    state_manager.update_state(last_execution_status=result.get("execution", "Error"))
    if success:
        await finalize_mission(result, websocket, cancel_event)
    else:
        await safe_send_json(websocket, {
            "type": "error", "message": result.get("response", ""),
            "execution": result.get("execution"), "failure_category": result.get("failure_category"),
        })


@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    """// Full-Duplex Agent Brain Pipeline (v9.0 Hybrid)"""
    if not await authenticate_websocket(websocket):
        return
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
            
            confirm_token = msg.get("confirm_token")
            if confirm_token is not None and not isinstance(confirm_token, str):
                await safe_send_json(websocket, {"type": "error", "message": "Invalid confirmation token."})
                continue

            async def run_command(task_prompt, task_socket, cancel_event, token=confirm_token):
                await execute_agent_task(task_prompt, task_socket, cancel_event, confirm_token=token)

            await task_manager.submit_task(prompt, websocket, run_command)

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
