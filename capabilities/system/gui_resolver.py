# capabilities/system/gui_resolver.py
# GUI Coordinate Resolver for SentinAL.
# Completes the ⚠️ Partial PyAutoGUI integration by adding element-finding logic.
#
# Strategy (multi-tier, fastest-first):
#   Tier 1: pyautogui.locateOnScreen — image-based element matching
#   Tier 2: pygetwindow — find windows by title substring
#   Tier 3: Windows Accessibility API (pywinauto) — find controls by name/label
#   Tier 4: VLM screenshot fallback (vision_module.py) — last resort
#
# Returns (x, y) pixel coordinates or None on failure.

import logging
import os
import time

import pyautogui

_logger = logging.getLogger("GUIResolver")


# ── Tier 1: Image-Based Matching ─────────────────────────────────────────────
def find_by_image(image_path: str, confidence: float = 0.85) -> tuple[int, int] | None:
    """
    Locates an on-screen element by matching a template image.
    Requires opencv-python (pip install opencv-python).

    Args:
        image_path:  Path to the reference PNG/JPG image
        confidence:  Match confidence 0-1 (requires opencv-python)

    Returns:
        (center_x, center_y) or None
    """
    if not os.path.exists(image_path):
        _logger.warning(f"find_by_image: image not found at '{image_path}'")
        return None

    try:
        loc = pyautogui.locateOnScreen(image_path, confidence=confidence)
        if loc:
            cx, cy = pyautogui.center(loc)
            _logger.info(f"find_by_image: matched '{image_path}' at ({cx}, {cy})")
            return int(cx), int(cy)
        _logger.debug(f"find_by_image: no match for '{image_path}'")
        return None
    except Exception as e:
        _logger.warning(f"find_by_image error: {e}")
        return None


# ── Tier 2: Window Title Matching ────────────────────────────────────────────
def find_window_center(title_substring: str) -> tuple[int, int] | None:
    """
    Finds a window by title substring and returns its center coordinates.
    Focuses the window and waits for it to activate.

    Args:
        title_substring: Case-insensitive fragment of the window title

    Returns:
        (center_x, center_y) or None
    """
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle(title_substring)
        if not windows:
            _logger.debug(f"find_window_center: no window with title '{title_substring}'")
            return None

        win = windows[0]
        try:
            win.activate()
            time.sleep(0.3)
        except Exception as e:
            # Window may already be active; non-fatal, but log rather than
            # silently swallow (ruff S110).
            _logger.debug(f"win.activate() failed for '{title_substring}' (non-fatal): {e}")

        cx = win.left + win.width // 2
        cy = win.top + win.height // 2
        _logger.info(f"find_window_center: '{title_substring}' at ({cx}, {cy})")
        return cx, cy

    except ImportError:
        _logger.warning("pygetwindow not installed — skipping Tier 2 window lookup")
        return None
    except Exception as e:
        _logger.warning(f"find_window_center error: {e}")
        return None


# ── Tier 3: Accessibility API (pywinauto) ────────────────────────────────────
def find_control_by_label(app_title: str, control_label: str) -> tuple[int, int] | None:
    """
    Uses the Windows Accessibility API to find a UI control by its label/name.
    More reliable than image matching for standard Windows controls.

    Args:
        app_title:     Title of the application window to search in
        control_label: The accessible name/label of the control (button text, field label, etc.)

    Returns:
        (center_x, center_y) or None
    """
    try:
        from pywinauto import Application, findwindows

        wins = findwindows.find_windows(title_re=f".*{re.escape(app_title)}.*")
        if not wins:
            _logger.debug(f"find_control_by_label: no window matching '{app_title}'")
            return None

        app = Application(backend="uia").connect(handle=wins[0])
        dlg = app.top_window()

        try:
            ctrl = dlg.child_window(title=control_label, found_index=0)
            rect = ctrl.rectangle()
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
            _logger.info(f"find_control_by_label: '{control_label}' in '{app_title}' at ({cx},{cy})")
            return cx, cy
        except Exception:
            # Fallback: search all descendants
            for ctrl in dlg.descendants():
                try:
                    if control_label.lower() in (ctrl.window_text() or "").lower():
                        rect = ctrl.rectangle()
                        cx = (rect.left + rect.right) // 2
                        cy = (rect.top + rect.bottom) // 2
                        _logger.info(f"find_control_by_label (fuzzy): found at ({cx},{cy})")
                        return cx, cy
                except Exception as e:
                    # A single descendant control being unreadable shouldn't abort
                    # the whole fuzzy search; non-fatal, but log rather than
                    # silently swallow (ruff S112).
                    _logger.debug(f"find_control_by_label fuzzy-match: skipping unreadable control: {e}")
                    continue
        return None

    except ImportError:
        _logger.warning("pywinauto not installed — skipping Tier 3 accessibility lookup")
        return None
    except Exception as e:
        _logger.warning(f"find_control_by_label error: {e}")
        return None


# ── Tier 4: VLM Screenshot Fallback ──────────────────────────────────────────
def find_by_description(description: str) -> tuple[int, int] | None:
    """
    Uses the Vision-Language Model to analyze the screen and estimate
    the location of a UI element by natural language description.
    
    This is the most flexible but slowest tier — only triggered if Tiers 1-3 fail.

    Args:
        description: Natural language description (e.g. 'the Submit button', 'search bar')

    Returns:
        (x, y) or None — note: VLM coordinate estimation is approximate
    """
    try:
        from capabilities.system.vision_module import take_screenshot_base64
        from config.settings import get_llm

        screenshot_b64 = take_screenshot_base64()
        llm = get_llm(task_label="GUI element location")

        prompt = (
            f"You are analyzing a computer screenshot to find the pixel coordinates of a UI element.\n"
            f"Element to find: '{description}'\n\n"
            f"Look at the screenshot carefully. Return ONLY a JSON object with this exact format:\n"
            f'{{\"x\": <center_x_pixel>, \"y\": <center_y_pixel>, \"found\": true}}\n'
            f"If the element is not visible, return: {{\"found\": false}}\n"
            f"No markdown, no explanation. Only the JSON."
        )

        from langchain_core.messages import HumanMessage
        msg = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
        ])

        import concurrent.futures
        import json
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(llm.invoke, [msg])
            try:
                response = future.result(timeout=15.0)
            except concurrent.futures.TimeoutError:
                _logger.warning("find_by_description: VLM timed out")
                return None

        text = response.content.strip()
        # Extract JSON from response
        import re as _re
        match = _re.search(r'\{.*\}', text, _re.DOTALL)
        if match:
            data = json.loads(match.group())
            if data.get("found"):
                x, y = int(data["x"]), int(data["y"])
                _logger.info(f"find_by_description (VLM): '{description}' at ({x},{y})")
                return x, y

        _logger.debug(f"find_by_description: VLM could not locate '{description}'")
        return None

    except Exception as e:
        _logger.warning(f"find_by_description VLM error: {e}")
        return None


# ── Unified Resolver Entry Point ──────────────────────────────────────────────
def resolve_element(
    label: str = "",
    image_path: str = "",
    app_title: str = "",
    confidence: float = 0.85,
) -> tuple[int, int] | None:
    """
    Main entry point — tries each resolution tier in order and returns
    the first successful result.

    Priority:
        1. Image matching (if image_path provided)
        2. Window center (if app_title provided)
        3. Accessibility API (if both app_title + label provided)
        4. VLM screenshot analysis (if label provided, as last resort)

    Args:
        label:      Natural language / accessible name of the element
        image_path: Path to a reference screenshot of the element
        app_title:  Title of the parent window
        confidence: Image match confidence (0-1)

    Returns:
        (x, y) pixel coordinates or None if all tiers fail
    """
    # Tier 1: Image
    if image_path:
        result = find_by_image(image_path, confidence)
        if result:
            return result

    # Tier 2: Window
    if app_title and not label:
        result = find_window_center(app_title)
        if result:
            return result

    # Tier 3: Accessibility
    if app_title and label:
        result = find_control_by_label(app_title, label)
        if result:
            return result

    # Tier 4: VLM fallback
    if label:
        result = find_by_description(label)
        if result:
            return result

    _logger.warning(f"resolve_element: all tiers exhausted for label='{label}', app='{app_title}'")
    return None


import re
