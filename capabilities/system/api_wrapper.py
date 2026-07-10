# api_wrapper.py
# Deterministic Backend Interface for SentinAL
# Replaces the ReAct agent with a strict extracted intent pipeline.
# V2.0 — Fix 3.12: process_command is now async to avoid blocking the ASGI event loop.

import asyncio
import json
from typing import Dict, Any


async def process_command(prompt: str) -> Dict[str, Any]:
    """
    Async pipeline entry point. Wraps the synchronous executor in a thread
    so it does not block the ASGI event loop (Fix 3.12).
    """
    from agentic_core.processor import extract_intent
    from agentic_core.validator import validate_steps
    from agentic_core.executor import execute_pipeline

    # 1. Initialize output structure
    output = {
        "input": prompt,
        "steps": [],
        "validation": "N/A",
        "execution": "N/A",
        "response": ""
    }

    try:
        # ── STAGE 1: INTENT EXTRACTION ──
        steps = extract_intent(prompt)
        output["steps"] = steps

        if any(s.get("intent") == "UnknownIntent" for s in steps):
            output["validation"] = "Error"
            output["execution"] = "Error"
            output["response"] = steps[0].get("target", "Extraction failed.")
            return output

        # ── STAGE 2: VALIDATION ──
        is_valid, validation_msg, _requires_confirm = validate_steps(steps)

        if not is_valid:
            output["validation"] = "Denied"
            output["execution"] = "Blocked"
            output["response"] = validation_msg
            return output

        output["validation"] = "Approved"

        # ── STAGE 3: EXECUTION ── (run in thread pool — Fix 3.12)
        execution_result = await asyncio.to_thread(execute_pipeline, steps)

        if isinstance(execution_result, str) and execution_result.startswith("ERROR"):
            output["execution"] = "Failed"
            output["response"] = execution_result
        else:
            output["execution"] = "Success"
            output["response"] = execution_result

    except Exception as e:
        output["validation"] = "Error"
        output["execution"] = "Error"
        output["response"] = f"Pipeline Integration Error: {str(e)}"

    return output
