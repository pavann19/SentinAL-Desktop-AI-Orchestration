import subprocess


def handle_sys_utility(target: str, prompt: str = "") -> str:
    """
    Handles system utilities like recycle bin, dark mode, brightness, mic.
    Uses LLM for robust action classification.

    Two fixes from the 40x3 benchmark baseline, where "switch to light mode"
    scored 0/3:

    1. Falls back to the full prompt when `target` is empty. Extraction returned
       an empty target for that phrasing, so classification never ran. Every
       comparable handler (dictation, media_control, window_manager) already
       does `prompt_text = prompt if prompt else target`; this one did not.

    2. Failure messages are ERROR-prefixed. api_wrapper.process_command() keys
       execution status on that prefix, so the old bare "I didn't catch the
       system utility command." was reported to the user as execution="Success"
       — a failure presented as a success, the same defect class as the
       fabricated-success stubs fixed in 24aad7f.
    """
    request = (target or "").strip() or (prompt or "").strip()
    if not request:
        return "ERROR: I didn't catch which system setting you wanted to change."
    target = request

    # _get_routing_llm() moved INSIDE the try: see window_manager.py's
    # identical fix for why a fetch failure must degrade the same way an
    # .invoke() failure does, not propagate uncaught.
    try:
        from agentic_core.processor import _get_routing_llm
        llm = _get_routing_llm("System Utility Classification")
        classification_prompt = (
            f"You are a System Utility controller. Classify this user command: '{target}'.\n"
            "Must output EXACTLY ONE of these strings: 'recycle_bin', 'dark_mode', 'light_mode', 'mute_mic', 'brightness_down'.\n"
            "If it doesn't match perfectly, pick the closest one. Output nothing else."
        )
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
            return f"ERROR: Failed to empty recycle bin: {e}"
            
    elif action == "dark_mode":
        try:
            cmd = 'Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name AppsUseLightTheme -Value 0; Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name SystemUsesLightTheme -Value 0'
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True)
            return "Windows Dark mode has been enabled."
        except Exception:
            return "ERROR: Failed to enable dark mode via PowerShell."
            
    elif action == "light_mode":
        try:
            cmd = 'Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name AppsUseLightTheme -Value 1; Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize -Name SystemUsesLightTheme -Value 1'
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True)
            return "Windows Light mode has been enabled."
        except Exception:
            return "ERROR: Failed to enable light mode via PowerShell."
            
    elif action == "mute_mic":
        # Requires nircmd or a complex C# bridge, simulating a generic response for Phase 1
        return "ERROR: Microphone mute isn't implemented — it needs an external dependency. Nothing was changed."
        
    elif action == "brightness_down":
        # Can use WMI, but keeping it simple for now
        return "ERROR: Brightness control isn't implemented — it needs WMI permissions. Nothing was changed."
        
    else:
        return f"ERROR: I don't know how to perform that system action yet: {action}"
