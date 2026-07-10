import os
import ctypes
import subprocess

def handle_sys_utility(target: str) -> str:
    """
    Handles system utilities like recycle bin, dark mode, brightness, mic.
    Uses LLM for robust action classification.
    """
    if not target:
        return "I didn't catch the system utility command."

    from agentic_core.processor import _get_routing_llm
    llm = _get_routing_llm("System Utility Classification")
    
    classification_prompt = (
        f"You are a System Utility controller. Classify this user command: '{target}'.\n"
        "Must output EXACTLY ONE of these strings: 'recycle_bin', 'dark_mode', 'light_mode', 'mute_mic', 'brightness_down'.\n"
        "If it doesn't match perfectly, pick the closest one. Output nothing else."
    )
    
    try:
        resp = llm.invoke([("system", classification_prompt)])
        action = resp.content.strip().lower()
    except Exception as e:
        print(f"[SysUtility] LLM Classification failed: {e}")
        action = "unknown"

    print(f"[SysUtility] Understood action: {action}")

    if action == "recycle_bin":
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force"], check=True)
            return "I have physically emptied the recycle bin."
        except Exception as e:
            return f"Failed to empty recycle bin: {e}"
            
    elif action == "dark_mode":
        try:
            cmd = 'Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name AppsUseLightTheme -Value 0; Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name SystemUsesLightTheme -Value 0'
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True)
            return "Windows Dark mode has been enabled."
        except Exception:
            return "Failed to enable dark mode via PowerShell."
            
    elif action == "light_mode":
        try:
            cmd = 'Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name AppsUseLightTheme -Value 1; Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name SystemUsesLightTheme -Value 1'
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True)
            return "Windows Light mode has been enabled."
        except Exception:
            return "Failed to enable light mode via PowerShell."
            
    elif action == "mute_mic":
        # Requires nircmd or a complex C# bridge, simulating a generic response for Phase 1
        return "Microphone mute command received. (Requires external dependency for pure python execution)."
        
    elif action == "brightness_down":
        # Can use WMI, but keeping it simple for now
        return "Brightness control command received. (Requires WMI permissions)."
        
    else:
        return f"I received a system utility command I don't know how to physically execute yet: {action}"
