import pyautogui


def handle_media_control(target: str, prompt: str) -> str:
    """
    Handles volume control and media playback via virtual keys.
    Uses LLM to understand natural language intent.
    """
    prompt_text = prompt if prompt else target
    if not prompt_text:
        return "I couldn't understand the media command."

    # _get_routing_llm() moved INSIDE the try: see window_manager.py's
    # identical fix. Here a fetch failure now hits the SAME except block as
    # an .invoke() failure and returns the same honest error, instead of
    # propagating uncaught out of this function.
    try:
        from agentic_core.processor import _get_routing_llm
        llm = _get_routing_llm("Media Action Classification")
        classification_prompt = (
            f"You are a Media Controller. Classify this user command: '{prompt_text}'.\n"
            "Must output EXACTLY ONE of these strings: 'volumeup', 'volumedown', 'volumemute', 'playpause', 'nexttrack', 'prevtrack'.\n"
            "If it doesn't match perfectly, pick the closest one. Output nothing else."
        )
        resp = llm.invoke([("system", classification_prompt)])
        action = resp.content.strip().lower()
    except Exception as e:
        print(f"[Media Controller] LLM Classification failed: {e}")
        return f"Failed to understand media command: {e}"

    print(f"[Media Controller] Understood action: {action}")

    valid_actions = ['volumeup', 'volumedown', 'volumemute', 'playpause', 'nexttrack', 'prevtrack']
    if action in valid_actions:
        try:
            # For volume up/down, press it multiple times for a noticeable difference
            if action in ['volumeup', 'volumedown']:
                pyautogui.press(action, presses=5)
            else:
                pyautogui.press(action)
            return f"I have executed the media action: {action}."
        except Exception as e:
            return f"Failed to execute physical media key: {e}"
    else:
        return f"I received an invalid media action: {action}"
