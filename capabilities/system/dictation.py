import time

import pyautogui


def handle_dictation(target: str, prompt: str) -> str:
    """
    Handles universal dictation mode using real hardware typing.
    Uses LLM to strip the command trigger and extract the pure payload.
    """
    prompt_text = prompt if prompt else target
    if not prompt_text:
        return "I didn't hear anything to dictate."

    # _get_routing_llm() moved INSIDE the try: see window_manager.py's
    # identical fix for why a fetch failure must degrade the same way an
    # .invoke() failure does, not propagate uncaught.
    try:
        from agentic_core.processor import _get_routing_llm
        llm = _get_routing_llm("Dictation Payload Extraction")
        extraction_prompt = (
            f"You are a dictation extraction system. The user's command is: '{prompt_text}'.\n"
            "Your job is to strip away the trigger words (like 'start dictation', 'type this', 'write this down') "
            "and output ONLY the raw text they want typed. If the whole sentence is the payload, output the whole sentence.\n"
            "Output ONLY the payload string. No quotes, no explanations."
        )
        resp = llm.invoke([("system", extraction_prompt)])
        payload = resp.content.strip()
    except Exception as e:
        print(f"[Dictation] LLM Extraction failed: {e}")
        # Fallback: strip common prefixes
        payload = prompt_text.replace("start dictation", "").replace("type this", "").strip()

    if not payload:
        return "I extracted an empty dictation payload."

    print(f"[Dictation] Extracted Payload: '{payload}'")

    try:
        # Brief pause to ensure the user's focus is on the right window
        time.sleep(1)
        pyautogui.write(payload, interval=0.01)
        return "I have typed your dictation payload."
    except Exception as e:
        return f"Failed to simulate typing: {e}"
