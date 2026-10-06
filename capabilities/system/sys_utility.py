import subprocess


def resolve_system_action(target: str, prompt: str = "") -> str:
    """Resolve supported utility commands without a model choosing a side effect."""
    text = ((target or "").strip() or (prompt or "").strip()).lower()
    aliases = {
        "recycle_bin": ("recycle_bin", "empty recycle bin", "empty the recycle bin", "clear recycle bin"),
        "dark_mode": ("dark_mode", "dark mode"),
        "light_mode": ("light_mode", "light mode"),
        "mute_mic": ("mute_mic", "mute microphone", "mute mic"),
        "brightness_down": ("brightness_down", "lower brightness", "brightness down"),
    }
    matches = [action for action, phrases in aliases.items() if any(phrase in text for phrase in phrases)]
    return matches[0] if len(matches) == 1 else "unknown"


def handle_sys_utility(target: str, prompt: str = "") -> str:
    """Execute a recognized utility action; unsupported or ambiguous commands fail."""
    request = (target or "").strip() or (prompt or "").strip()
    if not request:
        return "ERROR: I didn't catch which system setting you wanted to change."
    target = request

    action = resolve_system_action(target, prompt)

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
        return "ERROR: Microphone mute isn't implemented — it needs an external dependency. Nothing was changed."
        
    elif action == "brightness_down":
        # Can use WMI, but keeping it simple for now
        return "ERROR: Brightness control isn't implemented — it needs WMI permissions. Nothing was changed."
        
    else:
        return f"ERROR: I don't know how to perform that system action yet: {action}"
