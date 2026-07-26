# logger.py
import json
import os
from datetime import datetime

LOG_FILE = "logs/system_logs.json"

def log_event(user_input: str, intent: dict, validation: str, execution: str):
    """
    Records a system event into a JSON log file.
    Non-blocking helper for tracking assistant activity.
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "input": user_input,
            "intent": intent,
            "validation": validation,
            "execution": execution,
            "execution_status": execution,   # alias — required by /ws/telemetry reader
        }
        
        logs = []
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
            with open(LOG_FILE, "r") as f:
                try:
                    logs = json.load(f)
                except json.JSONDecodeError:
                    logs = []
        
        logs.append(entry)
        
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)
            
    except Exception as e:
        # Non-intrusive: print to console but don't crash the system
        print(f"[Logger Warning] Failed to record log: {e}")
