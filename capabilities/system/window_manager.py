import os
from datetime import datetime

import pyautogui


def handle_window_management(target: str, prompt: str) -> str:
    """
    Handles window snapping, screenshots, and screen recording using real hardware hooks.
    Uses LLM to understand natural language intent.
    """
    prompt_text = prompt if prompt else target
    if not prompt_text:
        return "I couldn't understand the window management command."

    # _get_routing_llm() moved INSIDE the try: a fetch failure (not just an
    # .invoke() failure) must degrade to the same keyword fallback below,
    # rather than propagating uncaught out of this function. Same class of
    # gap found and fixed in executor.py's stdout-summarization block, then
    # again independently in dictation/media_control/sys_utility while
    # writing this test file - a systemic pattern, not a one-off.
    try:
        from agentic_core.processor import _get_routing_llm
        llm = _get_routing_llm("Window Action Classification")
        classification_prompt = (
            f"You are a Window Management controller. Classify this user command: '{prompt_text}'.\n"
            "Must output EXACTLY ONE of these strings: 'screenshot', 'snap_left', 'snap_right', 'minimize_all', 'maximize', 'switch_desktop'.\n"
            "If it doesn't match perfectly, pick the closest one. Output nothing else."
        )
        resp = llm.invoke([("system", classification_prompt)])
        action = resp.content.strip().lower()
    except Exception as e:
        print(f"[Window Manager] LLM Classification failed: {e}")
        action = "screenshot" if "screenshot" in prompt_text.lower() else "unknown"

    print(f"[Window Manager] Understood action: {action}")

    try:
        if action == "screenshot":
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            # Naive/local (ruff DTZ005): used only to build a locally-unique
            # filename, never compared or stored — local time is fine.
            filename = f"SentinAL_Screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"  # noqa: DTZ005
            full_path = os.path.join(desktop_path, filename)
            pyautogui.screenshot(full_path)
            return f"I have taken a screenshot and physically saved it to your desktop as {filename}."
            
        elif action == "minimize_all":
            pyautogui.hotkey('win', 'd')
            return "I have minimized all windows."
            
        elif action == "snap_left":
            pyautogui.hotkey('win', 'left')
            return "I snapped the active window to the left."
            
        elif action == "snap_right":
            pyautogui.hotkey('win', 'right')
            return "I snapped the active window to the right."
            
        elif action == "maximize":
            pyautogui.hotkey('win', 'up')
            return "I maximized the current window."
            
        elif action == "switch_desktop":
            # Best effort to switch right
            pyautogui.hotkey('win', 'ctrl', 'right')
            return "I switched your virtual desktop."
            
        else:
            return f"I received a window command I don't know how to physically execute yet: {action}"
            
    except Exception as e:
        return f"Failed to execute window action: {e}"
