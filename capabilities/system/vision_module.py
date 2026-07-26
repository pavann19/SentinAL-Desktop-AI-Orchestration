import os
import concurrent.futures
import pyautogui
import base64
import io
from PIL import Image
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

# Fix 3.4: Vision model is now configurable via env var
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
_VISION_TIMEOUT = 10.0  # Max seconds to wait for VLM response


def take_screenshot_base64() -> str:
    """Captures the current screen and returns it as a base64 encoded PNG string."""
    screenshot = pyautogui.screenshot()
    buffer = io.BytesIO()
    screenshot.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def verify_screen_state(query: str) -> bool:
    """
    Passes a screenshot to the local Vision-Language Model to answer a yes/no query.
    Returns True if the model perceives the condition to be true, False otherwise.

    V2.0 Fixes (Fix 3.4):
    - Model name is now read from OLLAMA_VISION_MODEL env var
    - Returns False (fail-safe) on model-not-found instead of True (fail-open)
    - Hard 10s timeout via concurrent.futures to prevent indefinite blocking
    """
    try:
        base64_image = take_screenshot_base64()
        llm = ChatOllama(model=VISION_MODEL, temperature=0)

        prompt = (
            f"Look at this screenshot of my computer desktop. "
            f"Answer the following query with ONLY the word TRUE or FALSE. "
            f"Query: {query}"
        )
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
            ]
        )

        print(f"[Vision Module] Analyzing screen for query: '{query}'...")

        # Fix 3.4: Hard timeout — don't block the executor thread indefinitely
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(llm.invoke, [message])
            try:
                response = future.result(timeout=_VISION_TIMEOUT)
            except concurrent.futures.TimeoutError:
                print(f"[Vision Module] VLM timed out after {_VISION_TIMEOUT}s — returning False (fail-safe).")
                return False

        text = response.content.upper()
        return "TRUE" in text

    except Exception as e:
        err_str = str(e).lower()
        # Fix 3.4: Return False (fail-safe) on model-not-found, NOT True (fail-open)
        if "404" in str(e) or "not found" in err_str or "model" in err_str:
            print(f"[Vision Module] Model '{VISION_MODEL}' not found — returning False (fail-safe).")
            return False
        print(f"[Vision Module] Error during screen verification: {e}")
        return False
