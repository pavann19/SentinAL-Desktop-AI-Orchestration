import asyncio
import os
import psutil
import time
import shutil
from playwright.async_api import async_playwright
SERVER_URL = "http://localhost:5173"
WS_URL = "ws://localhost:8000/ws/agent"

def get_server_process():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline') or []
            if 'python' in proc.info.get('name', '').lower() and any('server.py' in cmd for cmd in cmdline):
                return psutil.Process(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None

async def run_stress_test():
    print("=== SentinAL Chaos Engineering Stress Test ===")
    
    server_proc = get_server_process()
    if not server_proc:
        print("[Warning] Could not find running server.py process for metric tracking. Metrics will be skipped.")

    successes = 0
    total_latency = 0
    peak_ram_mb = 0

    base_dir = os.path.join(os.environ["USERPROFILE"], "Desktop")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(90000)
        
        # Load the React Dashboard
        print(f"[*] Navigating to {SERVER_URL}...")
        try:
            await page.goto(SERVER_URL, timeout=10000)
            await page.wait_for_load_state('networkidle')
        except Exception as e:
            print(f"[Error] Failed to load React Dashboard: {e}")
            await browser.close()
            return

        for i in range(1, 6):
            print(f"\n--- Iteration {i}/5 ---")
            folder_name = f"StressTest_{i}"
            expected_path = os.path.join(base_dir, folder_name)
            
            # Clean up before run just in case
            if os.path.exists(expected_path):
                shutil.rmtree(expected_path)

            mock_command = f"Create a folder named {folder_name} on my Desktop"

            iteration_start = time.time()
            
            latency_ms = 0
            try:
                # We use page.evaluate to spawn an isolated WebSocket test specifically for this mocked command
                result = await page.evaluate('''async (cmd) => {
                    return new Promise((resolve, reject) => {
                        const ws = new WebSocket("ws://localhost:8000/ws/agent");
                        const sequence = [];
                        
                        ws.onopen = () => {
                            ws.send(JSON.stringify({text: cmd}));
                        };
                        
                        ws.onmessage = (evt) => {
                            const msg = JSON.parse(evt.data);
                            if (msg.type === "execution_step" && msg.stage) {
                                sequence.push(msg.stage);
                            } else if (msg.type === "final_response") {
                                ws.close();
                                resolve(sequence);
                            } else if (msg.type === "error") {
                                ws.close();
                                reject("Received error: " + msg.message);
                            }
                        };
                        setTimeout(() => reject("WebSocket Timeout after 90s"), 90000);
                    });
                }''', mock_command)

                latency_ms = (time.time() - iteration_start) * 1000
                total_latency += latency_ms
                
                print(f"[WS] Sequence Received: {' -> '.join(result)}")
                
                # Verify specific sequence transition
                if "perception" in result and "actuation" in result:
                    # Verify OS-level change
                    # Wait up to 2 seconds for the file system to catch up if needed
                    await asyncio.sleep(1)
                    if os.path.exists(expected_path):
                        print(f"[System] Verification PASS: {expected_path} exists.")
                        successes += 1
                        shutil.rmtree(expected_path) # Clean up after success
                    else:
                        print(f"[System] Verification FAIL: Folder {expected_path} was not created.")
                else:
                    print(f"[System] Verification FAIL: Sequence logic missing crucial stages.")
            
            except Exception as e:
                err_str = str(e)
                if "Timeout" in err_str:
                    print(f"[Error] Thread Deadlock detected (Timeout): {err_str}")
                elif "database is locked" in err_str.lower():
                    print(f"[Error] Race Condition detected (SQLite lock): {err_str}")
                else:
                    print(f"[Error] Run {i} Failed: {err_str}")

            # Capture process metrics
            try:
                cpu_pct = server_proc.cpu_percent(interval=0.1)
                mem_mb = server_proc.memory_info().rss / (1024 * 1024)
                peak_ram_mb = max(peak_ram_mb, mem_mb)
                print(f"[Metrics] server.py -> CPU: {cpu_pct}% | RAM: {mem_mb:.2f} MB | Latency: {latency_ms:.0f} ms")
            except Exception as e:
                print(f"[Metrics] Could not read process metrics: {e}")

            # Short breath between actions to simulate human cadence
            await asyncio.sleep(2)
            
        await browser.close()

    print("\n=== Final Stress Test Report ===")
    avg_latency = total_latency / successes if successes > 0 else 0
    print(f"Status: {successes}/5 Successes")
    print(f"Average Latency: {avg_latency:.2f} ms")
    print(f"Peak RAM: {peak_ram_mb:.2f} MB")
if __name__ == "__main__":
    try:
        asyncio.run(run_stress_test())
    except RuntimeError as e:
        if "Event loop is closed" not in str(e):
            raise
