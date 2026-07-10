import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import uvicorn
import threading
import time

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global flag to signal the Playwright script to proceed
client_connected = asyncio.Event()
active_agent_ws = None
active_telemetry_ws = None

@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    global active_telemetry_ws
    await websocket.accept()
    active_telemetry_ws = websocket
    try:
        while True:
            # Send idle telemetry
            payload = {
                "hardware": {"cpu_percent": 12.4, "ram_percent": 45.2, "temperature": 42.1},
                "system": {"uptime_percent": 99.9, "ai_core_status": "ONLINE", "threat_level": "LOW"},
                "governance": {"clearance": "ALPHA"}
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        active_telemetry_ws = None

@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    global active_agent_ws
    await websocket.accept()
    active_agent_ws = websocket
    client_connected.set()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_agent_ws = None

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

async def capture_screenshots():
    import subprocess
    import os
    
    # Start Vite UI server
    print("[Capture] Starting Vite UI server...")
    vite_process = subprocess.Popen(
        ["cmd", "/c", "npm run dev"], 
        cwd=os.path.join(os.getcwd(), "sentinal-ui"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Start the backend server in a background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Give the servers a moment to boot
    print("[Capture] Waiting for servers to boot...")
    await asyncio.sleep(5)

    async with async_playwright() as p:
        # Launch visible Google Chrome
        browser = await p.chromium.launch(
            headless=False, 
            channel="chrome",
            args=['--start-maximized']
        )
        # Use no_viewport to let it fill the maximized window
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()

        print("[Capture] Navigating to SentinAL UI in Chrome...")
        await page.goto("http://localhost:5173/")
        
        # Wait for the UI to connect to our mock backend
        print("[Capture] Waiting for UI to connect to websocket...")
        await client_connected.wait()
        await asyncio.sleep(3) # Let UI settle and animations finish

        import pyautogui

        # 1. Idle Dashboard
        print("[Capture] Taking 01_dashboard_idle.png...")
        pyautogui.screenshot("images/01_dashboard_idle.png")

        # Helper to send agent messages
        async def send_agent(type_val, msg, stage=None, status=None, **kwargs):
            if active_agent_ws:
                payload = {"type": type_val, "message": msg}
                if stage: payload["stage"] = stage
                if status: payload["status"] = status
                payload.update(kwargs)
                await active_agent_ws.send_text(json.dumps(payload))
                await asyncio.sleep(1) # Give UI time to animate

        # 2. Mission Received (Perception)
        await send_agent("execution_step", "Take a screenshot of my desktop", stage="perception")
        await asyncio.sleep(2)
        print("[Capture] Taking 02_mission_received.png...")
        pyautogui.screenshot("images/02_mission_received.png")

        # 3. Governance Block (Security Block)
        await send_agent("execution_step", "Analyzing system impact...", stage="governance")
        await asyncio.sleep(2)
        await send_agent("error", "Security Block: This action requires ALPHA clearance.", stage="governance")
        await asyncio.sleep(2)
        print("[Capture] Taking 03_security_block.png...")
        pyautogui.screenshot("images/03_security_block.png")

        # Reset to Idle via speech end
        await send_agent("speech_end", "")
        await asyncio.sleep(4)

        # 4. React Loop / Local Execution
        await send_agent("execution_step", "Start dictation mode", stage="perception")
        await asyncio.sleep(2)
        await send_agent("execution_step", "Validating safety parameters...", stage="governance")
        await asyncio.sleep(2)
        print("[Capture] Taking 04_react_loop.png...")
        pyautogui.screenshot("images/04_react_loop.png")
        
        await send_agent("execution_step", "Executing physical keystrokes...", stage="actuation")
        await asyncio.sleep(2)
        print("[Capture] Taking 05_local_execution.png...")
        pyautogui.screenshot("images/05_local_execution.png")
        
        await send_agent("final_response", "I have finished the dictation.")
        await asyncio.sleep(2)
        print("[Capture] Taking 06_mission_complete.png...")
        pyautogui.screenshot("images/06_mission_complete.png")
        
        await asyncio.sleep(4)

        # 7. Cloud Execution (CodeAct)
        await send_agent("execution_step", "Create a basic python server", stage="perception")
        await asyncio.sleep(2)
        await send_agent("execution_step", "Routing to Neural Core for CodeAct...", stage="researching")
        await asyncio.sleep(2)
        print("[Capture] Taking 07_cloud_execution.png...")
        pyautogui.screenshot("images/07_cloud_execution.png")

        await browser.close()
        print("[Capture] All screenshots saved to images/ folder!")
        
        # Kill vite process
        vite_process.terminate()
        print("[Capture] UI Server terminated.")

if __name__ == "__main__":
    asyncio.run(capture_screenshots())
