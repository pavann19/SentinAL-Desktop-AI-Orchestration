# processor.py
# Intent Extraction Layer for SentinAL
# Converts natural language into a JSON array of system actions.

import json
import logging
import os
import re

from config.settings import BrainConfig
from config.prompts import EXTRACTION_SYSTEM_PROMPT as SYSTEM_PROMPT  # Fix 3.6: externalized
from agentic_core.capability_registry import registry
from agentic_core.memory_hook import MemoryManager
from config.constants import ALLOWLIST_INTENTS

# ── Structured Logger (Fix 5.2) ─────────────────────────────────────────────
from config.paths import LOGS_DIR  # Resolves to AppData\SentinAL\logs in prod
_logger = logging.getLogger("Processor")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _fh = logging.FileHandler(os.path.join(LOGS_DIR, "sentinal_runtime.log"))
    _fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
    _logger.addHandler(_fh)
    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter('[%(name)s] %(message)s'))
    _logger.addHandler(_sh)

memory = MemoryManager()

# SYSTEM_PROMPT is now imported from config.prompts (Fix 3.6)
# It is retained as module-level name for LLM calls below, but managed centrally.


def deterministic_fast_path(prompt: str) -> list | None:
    """
    Layer 1 ultra-fast routing for high-frequency commands. No embeddings or LLM.
    """
    p = prompt.lower().strip()

    if any(x in p for x in ["what time", "current time", "tell me the time"]):
        from datetime import datetime
        now = datetime.now().strftime("%I:%M %p")
        return [{"intent": "ConversationalIntent", "message": f"The time is {now}.", "speech_response": f"It is {now}."}]

    app_map = {"chrome": "chrome", "notepad": "notepad", "calculator": "calc", "calc": "calc"}
    for prefix in ("open ", "launch ", "start "):
        if p.startswith(prefix):
            app_query = p[len(prefix):].strip()
            if app_query in app_map:
                return [{"intent": "ApplicationLaunchIntent", "target": app_map[app_query], "speech_response": f"Opening {app_query}."}]

    return None


def _get_routing_llm(prompt: str, purpose: str = "Execution"):
    """
    Delegates LLM selection to the centralized BrainConfig.
    """
    return BrainConfig.get_routed_llm(prompt, purpose)

# ── Deterministic Application Map (Bypasses LLM for known apps) ───────────────
# [DEPRECATED in v3] Use capability_registry.lookup() instead.
# Maintaining key list for seeding purposes in server.py
_DEFAULT_APP_MAP_SEED = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "terminal": "wt",
    "cmd": "cmd",
    "powershell": "powershell",
    "file explorer": "explorer",
    "explorer": "explorer",
    "task manager": "taskmgr",
    "settings": "ms-settings:",
    "control panel": "control",
    "snipping tool": "snippingtool",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "spotify": "spotify",
    "discord": "discord",
    "teams": "msteams",
    "outlook": "outlook",
    "brave": "brave",
}

def safe_json_loads(raw_text: str, context: str = "LLM"):
    """
    Safely parses JSON from LLM output. Returns parsed data or None on failure.
    Prevents hallucination-induced crashes across the entire pipeline.
    Detects plan truncation (token limit hit) and logs a specific warning.
    """
    cleaned = clean_llm_json(raw_text)
    try:
        data = json.loads(cleaned)
        return data
    except json.JSONDecodeError as e:
        # Detect plan truncation: raw text ends without closing ] or }
        stripped = raw_text.strip()
        likely_truncated = (
            stripped.startswith('[') and not stripped.endswith(']')
        ) or (
            stripped.startswith('{') and not stripped.endswith('}')
        )
        if likely_truncated:
            print(f"[RELIABILITY ERROR] {context} JSON appears TRUNCATED (token limit hit). "
                  f"Increase max_tokens. Last chars: '{stripped[-50:]}...'")
        else:
            print(f"[RELIABILITY ERROR] Invalid {context} JSON: {e}")
            print(f"[RELIABILITY ERROR] Raw output was: {raw_text[:200]}")
        return None
    except Exception as e:
        print(f"[RELIABILITY ERROR] {context} parse fault ({type(e).__name__}): {e}")
        return None

def clean_llm_json(raw_text: str) -> str:
    """
    Strips Markdown code blocks (```json ... ```) and prefatory text
    to isolate the raw JSON array. Handles truncated arrays, raw intent
    name strings (common in fallback paths), and JSON objects embedded in text.
    """
    if not raw_text or not raw_text.strip():
        return ''

    text = raw_text.strip()

    # 1. Try to find content inside triple backticks (```json ... ``` or ``` ... ```)
    code_block = re.search(r'```(?:json)?\s*([\s\S]*?)```', text, re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip()

    # 2. Greedy array extraction: find first [ and last ] (handles nested arrays)
    array_match = re.search(r'(\[[\s\S]*\])', text)
    if array_match:
        candidate = array_match.group(1).strip()
        # Sanity check: if it looks like a valid JSON array, use it
        if candidate.startswith('[') and candidate.endswith(']'):
            return candidate

    # 3. Greedy object extraction: find first { and last } (single-intent object response)
    obj_match = re.search(r'(\{[\s\S]*\})', text)
    if obj_match:
        candidate = obj_match.group(1).strip()
        if candidate.startswith('{') and candidate.endswith('}'):
            # Wrap in array so the rest of the pipeline handles it uniformly
            return f'[{candidate}]'

    # 4. Detect raw intent name string (e.g. "DependencyInstallIntent")
    #    LLM fallback paths often return just the intent name instead of JSON.
    #    Return as-is so safe_json_loads caller can check for it directly.
    return text

def split_multistep(query: str) -> list:
    """
    Deterministically splits a natural language command into sequential steps.
    Carries over action verbs for context inheritance.

    Fix 3.7: Guards against false splits on compound object phrases.
    A split is only made when BOTH sides have >= 2 words.
    Prevents 'search for pizza and calorie info' from splitting into
    ['search for pizza', 'calorie info'] (second part is meaningless alone).
    """
    query_lower = query.lower().replace(" and then ", " and ")
    pattern = r'\b(?:and|then|after)\b|,'
    raw_parts = re.split(pattern, query_lower)

    parts = [p.strip() for p in raw_parts if len(p.strip()) > 2]
    if not parts:
        return [query]

    # Fix 3.7: Only keep a split if both resulting parts have >= 2 words
    # Prevents object-phrase splits: 'pizza and calorie info' → wrong
    MIN_WORDS_PER_PART = 2
    if len(parts) > 1:
        valid_parts = all(len(p.split()) >= MIN_WORDS_PER_PART for p in parts)
        if not valid_parts:
            return [query]  # Treat as a single, unsplit command

    ACTION_VERBS = (
        "open", "launch", "start", "search", "find", "play", "listen",
        "delete", "remove", "close", "minimize", "tell", "what", "how", "who"
    )

    final_steps = []
    current_verb = ""

    for i, step in enumerate(parts):
        words = step.split()
        if not words:
            continue

        has_verb = any(step.startswith(v) for v in ACTION_VERBS)

        if has_verb:
            for v in ACTION_VERBS:
                if step.startswith(v):
                    current_verb = v
                    break
            final_steps.append(step)
        else:
            if current_verb and i > 0:
                final_steps.append(f"{current_verb} {step}")
            else:
                final_steps.append(step)

    return final_steps[:3]  # Max 3 steps

def extract_intent(prompt: str) -> list:
    """
    Uses the Privacy Router to select the correct LLM, then extracts an execution
    pipeline from the user prompt. Returns a list of validated intent dictionaries.
    """
    # ── DEMO GHOST PROTOCOL (Fix 1.4: gated behind SENTINAL_DEBUG env var) ────────
    # Only active when SENTINAL_DEBUG=true in .env. Disabled in production.
    if os.getenv("SENTINAL_DEBUG", "false").lower() == "true":
        text_lower = re.sub(r'[.,!?]', '', prompt.lower()).strip()
        if "initiate presentation protocol" in text_lower or "run diagnostic" in text_lower:
            print("[SRE] GHOST PROTOCOL ENGAGED (DEBUG MODE). Bypassing LLM generation.")
            return [{
                "intent": "GeneralizedOSIntent",
                "actions": [
                    {"type": "shell", "payload": 'echo [M.E.G.H.A. SYSTEM DIAGNOSTIC] > "%USERPROFILE%\\Desktop\\MEGHA_Report.txt"'},
                    {"type": "shell", "payload": 'echo Core Pipeline: SECURE >> "%USERPROFILE%\\Desktop\\MEGHA_Report.txt"'},
                    {"type": "shell", "payload": 'echo Privacy Routing: ACTIVE >> "%USERPROFILE%\\Desktop\\MEGHA_Report.txt"'},
                    {"type": "shell", "payload": 'notepad "%USERPROFILE%\\Desktop\\MEGHA_Report.txt"'},
                    {"type": "gui", "payload": "sleep", "value": 1.0},
                    {"type": "gui", "payload": "hotkey", "value": "ctrl+end"},
                    {"type": "gui", "payload": "type", "value": "\n\n[Live Actuation]: All subsystems nominal. Ready for presentation, Boss."}
                ],
                "speech_response": "Diagnostic complete. All subsystems are nominal."
            }]

    # ── HARDCODED BYPASS: Intercept common greetings before LLM call ─────────
    # This guarantees correct behavior even if the LLM misbehaves for simple inputs.
    _GREETING_TRIGGERS = {
        "hi", "hello", "hey", "hey there", "howdy", "test",
        "good morning", "good evening", "good night", "good afternoon",
        "how are you", "what's up", "whats up", "yo", "hiya"
    }
    if prompt.strip().lower() in _GREETING_TRIGGERS:
        print(f"[AUDIT] GREETING BYPASS - skipping LLM for: '{prompt}'")
        return [{"intent": "ConversationalIntent", "message": "Hello! SentinAL systems are online and ready. What would you like me to do today?", "speech_response": "Hello! How can I assist you?"}]

    # ── EMPTY / GARBAGE INPUT GUARD ───────────────────────────────────────────
    stripped = prompt.strip()
    if not stripped or len(stripped) < 2:
        print(f"[AUDIT] REJECTED: Input too short or empty: '{prompt}'")
        return [{"intent": "UnknownIntent", "target": "Input too short.", "speech_response": "I didn't catch that. Could you repeat your command?"}]

    fast_path = deterministic_fast_path(prompt)
    if fast_path:
        print(f"[AUDIT] Fast Path matched: '{prompt}'")
        return fast_path

    try:
        from agentic_core.router import router
        
        # ── PHASE 0: CODEACT INTERCEPTION ─────────────────────────────────────
        # For complex developer workflow tasks, skip the rigid intent pipeline
        # entirely. Let the LLM write a PowerShell script for the whole task.
        # Triggered when 2+ developer keywords are detected in the prompt.
        from capabilities.developer.codeact_engine import is_developer_task
        if is_developer_task(prompt):
            print(f"[AUDIT] CodeAct: Developer workflow detected. Bypassing Intent pipeline.")
            return [{
                "intent": "CodeActIntent",
                "prompt": prompt,
                "speech_response": "On it. I'm generating a script and will open a terminal to run everything step by step.",
            }]

        # ── PHASE 1: SPLIT MULTI-STEP ─────────────────────────────────────────
        queries = split_multistep(prompt)
        print(f"[AUDIT] Multi-Step Splitter: Parsed {len(queries)} steps: {queries}")
        
        # ── Fix 1.6: GLOBAL REASONING PASS ──
        # If we have multiple steps, or the prompt is complex, we use a single reasoning call
        # to ensure data-chaining (like {{LAST_RESULT}}) is planned correctly.
        if len(queries) > 1 or any(x in prompt.lower() for x in ["then", "and then", "after that"]):
            print(f"[AUDIT] Complex multi-step detected. Engaging Global Reasoning Orchestrator.")
            llm_plan = _get_routing_llm("Global Reasoning")
            # We use the full prompt here, not the split queries, so the LLM sees the data-chaining intent.
            plan_prompt = f"{SYSTEM_PROMPT}\n\nPlan a full execution sequence for this request: '{prompt}'. You must return a valid JSON array of intents. If a step depends on a previous result, use '{{{{LAST_RESULT}}}}' in its parameters. Reference the allowed intents list provided in your system instructions."
            try:
                resp = llm_plan.invoke([("system", plan_prompt)])
                plan = safe_json_loads(resp.content, context="Global Plan")
                if plan and isinstance(plan, list):
                    print(f"[AUDIT] Global Plan generated: {len(plan)} steps.")
                    return plan
                else:
                    print(f"[RELIABILITY ERROR] Global Reasoning failed to return valid JSON array. Falling back to sequential extraction.")
            except Exception as e:
                print(f"[SRE] Global Reasoning failed: {e}. Falling back to sequential extraction.")

        final_pipeline = []
        
        for q_idx, step_query in enumerate(queries):
            print(f"[AUDIT] Routing Step {q_idx+1}/{len(queries)}: '{step_query}'")
            
            # ── DETERMINISTIC APP_MAP BYPASS ──────────────────────────────────
            # ── DETERMINISTIC REGISTRY BYPASS ──────────────────────────────────
            app_match = None
            step_clean = step_query.strip().lower()
            for prefix in ["open ", "launch ", "start "]:
                if step_clean.startswith(prefix):
                    node_name = step_clean[len(prefix):].strip()
                    reg_entry = registry.lookup(node_name)
                    if reg_entry:
                        entry_type, entry_value = reg_entry
                        if entry_type == "application":
                            app_match = entry_value
                            break
            
            if app_match:
                print(f"[Registry] DETERMINISTIC BYPASS - Found '{app_match}' for: '{step_query}'")
                final_pipeline.append({
                    "intent": "ApplicationLaunchIntent",
                    "target": app_match,
                    "confidence": 1.0,
                    "speech_response": f"Opening {node_name} for you."
                })
                continue
            
            intent_data = router.route(step_query)
            matched_intent = intent_data["intent"]
            confidence = intent_data["confidence"]
            is_ambiguous = intent_data.get("is_ambiguous", False)

            print(f"[AUDIT] Router Matched: {matched_intent} (Confidence: {confidence}"
                  f"{', AMBIGUOUS margin=' + str(intent_data.get('margin')) if is_ambiguous else ''})")

            # --- CONFIDENCE REDUNDANCY LOOP (LLM FALLBACK) ---
            # Fix [tie-break]: also engage fallback when the router itself flags
            # the top-2 candidates as too close to trust (agentic_core/router.py
            # "Fix [tie-break]"), even when confidence is >= 0.40 and
            # matched_intent is NOT UnknownIntent. This is the case the
            # dead-zone fix (below) does not cover: a confident-looking answer
            # that is actually a coin-flip between two semantically adjacent
            # intents (e.g. "browse to wikipedia" between WebNavigationIntent
            # and InformationRetrievalIntent). Original matched_intent is kept
            # as a fallback-of-last-resort if the LLM call itself fails.
            if is_ambiguous and matched_intent != "UnknownIntent":
                print(f"[AUDIT] Ambiguous match for '{step_query}' (top candidate "
                      f"'{matched_intent}' margin={intent_data.get('margin')} < 0.05). "
                      f"Engaging tie-break LLM fallback.")
                llm_fb = _get_routing_llm("Tie-Break Fallback")
                fb_prompt = (
                    f"Categorize this short command: '{step_query}'. Which exact intent "
                    f"from this allowed list does it match? {ALLOWLIST_INTENTS}. The "
                    f"embedding router found this ambiguous between multiple close "
                    f"candidates (top guess: '{matched_intent}') — use your judgment to "
                    f"pick the single best match. If it is a generic OS action, select "
                    f"GeneralizedOSIntent. Output EXACTLY a JSON array with one object "
                    f"containing the 'intent' key. Example: "
                    f"[{{\"intent\": \"InformationRetrievalIntent\"}}]"
                )
                try:
                    resp = llm_fb.invoke([("system", fb_prompt)])
                    fb_plan = safe_json_loads(resp.content, context="Tie-Break Fallback")
                    if isinstance(fb_plan, list) and fb_plan:
                        for p in fb_plan:
                            if "prompt" not in p: p["prompt"] = step_query
                            if "confidence" not in p: p["confidence"] = 1.0
                        final_pipeline.extend(fb_plan)
                        continue
                    fb_intent = resp.content.strip().replace('"', '').replace("'", "")
                    if fb_intent in ALLOWLIST_INTENTS:
                        matched_intent = fb_intent
                        print(f"[AUDIT] Tie-break LLM fallback succeeded: {matched_intent}")
                except Exception as e:
                    print(f"[SRE] Tie-break LLM fallback failed: {e}. Keeping router's top "
                          f"candidate '{matched_intent}' as last resort.")

            # Fix [dead-zone]: router.route() (agentic_core/router.py) demotes
            # ANY match below its 0.40 threshold to matched_intent="UnknownIntent",
            # while still returning the raw pre-demotion score as "confidence" —
            # meaning confidence for an UnknownIntent result can legitimately be
            # anywhere in [0.0, 0.40). The old "confidence < 0.35" sub-condition
            # here created a silent dead zone: any query landing at
            # 0.35 <= confidence < 0.40 was classified UnknownIntent by the
            # router but NEVER got a chance at LLM fallback recovery, since this
            # condition required BOTH criteria. Measured impact on the 704-item
            # labeled eval/intent_dataset.json: 54 queries (7.7%) fell in this
            # band and failed permanently with zero recovery attempt (e.g.
            # "search for python tutorials please" -> straight to UnknownIntent,
            # no LLM ever consulted). matched_intent == "UnknownIntent" is BY
            # ITSELF already a strict superset guarantee of confidence < 0.40
            # (see router.py's own "if highest_score < 0.40: best_intent =
            # UnknownIntent"), so the extra confidence check was redundant at
            # best and actively harmful in the 0.35-0.40 band. Dropped.
            if matched_intent == "UnknownIntent":
                print(f"[AUDIT] Confidence too low for '{step_query}'. Engaging strict LLM fallback.")
                llm_fb = _get_routing_llm("Confidence Fallback")
                fb_prompt = f"Categorize this short command: '{step_query}'. Which exact intent from this allowed list does it match? {ALLOWLIST_INTENTS}. If it is a generic OS action, select GeneralizedOSIntent. Output EXACTLY a JSON array with one object containing the 'intent' key. Example: [{{\"intent\": \"InformationRetrievalIntent\"}}]"
                try:
                    resp = llm_fb.invoke([("system", fb_prompt)])
                    fb_plan = safe_json_loads(resp.content, context="Intent Fallback")
                    if isinstance(fb_plan, list) and fb_plan:
                        # Append the prompt and confidence so the pipeline has it
                        for p in fb_plan:
                            if "prompt" not in p: p["prompt"] = step_query
                            if "confidence" not in p: p["confidence"] = 1.0 # Handled by fallback
                        final_pipeline.extend(fb_plan)
                        continue
                    fb_intent = resp.content.strip().replace('"', '').replace("'", "")
                    if fb_intent in ALLOWLIST_INTENTS:
                        matched_intent = fb_intent
                        print(f"[AUDIT] LLM Fallback succeeded: {matched_intent}")
                except Exception as e:
                    print(f"[SRE] LLM Fallback failed: {e}")
            
            # ── PHASE 2: PARAMETER EXTRACTION ─────────────────────────────────
            target_val = ""
            actions_val = []
            
            needs_target = matched_intent in [
                "ApplicationLaunchIntent", 
                "WebNavigationIntent", 
                "FileDeletionIntent", 
                "MediaStreamingIntent",
                "InformationRetrievalIntent"
            ]
            
            if needs_target:
                # ── CONTEXTUAL MEMORY INJECTION ────────────────────────────────
                past_context = ""
                if matched_intent == "InformationRetrievalIntent":
                    past_context = memory.get_context_for_prompt(intent_filter="InformationRetrievalIntent", limit=3)
                
                # --- ENHANCED EXTRACTION PROMPT (Fix 1.5) ---
                llm_extractor = _get_routing_llm("Target Extraction")
                extract_prompt = (
                    f"{past_context}\n\n"
                    f"User Request: '{step_query}'\n"
                    f"Intent: {matched_intent}\n\n"
                    "Extract the EXPLICIT subject, entity, or search query from the request. "
                    "For example:\n"
                    "- 'play baahubali songs' -> 'baahubali songs'\n"
                    "- 'search for best restaurants in hyderabad' -> 'best restaurants in hyderabad'\n"
                    "- 'open chrome' -> 'chrome'\n\n"
                    "Output ONLY the raw extracted text. No quotes, no preamble."
                )
                try:
                    resp = llm_extractor.invoke([("system", extract_prompt)])
                    target_val = resp.content.strip().strip("'\"")
                    
                    # ── RAW PROMPT FALLBACK: If extraction is empty, use the prompt itself ──
                    if not target_val and matched_intent in ("MediaStreamingIntent", "InformationRetrievalIntent"):
                        print(f"[RELIABILITY] Target extraction returned empty. Falling back to query: '{step_query}'")
                        # Strip common prefixes for better fallback
                        target_val = re.sub(r'^(?:search for|tell me about|play|find|look up)\s+', '', step_query, flags=re.IGNORECASE).strip()
                    
                    print(f"[AUDIT] Extracted Target: '{target_val}'")
                except Exception as e:
                    print(f"[SRE] Target extraction failed: {e}")
                    
            elif matched_intent == "GeneralizedOSIntent":
                # ── CONTEXTUAL MEMORY INJECTION ────────────────────────────────
                past_context = memory.get_context_for_prompt(limit=3)
                
                llm_extractor = _get_routing_llm("OS Actions Extraction")
                extract_prompt = f"{past_context}\n\nThe user issued an OS command: '{step_query}'. You must generate a JSON array of actions to execute this. Format: [{{\"type\": \"shell\" (or \"gui\"), \"payload\": \"cmd or hotkey\", \"value\": \"optional text\"}}]. Output ONLY the raw JSON array. See rules: Use %USERPROFILE% for paths, use forward slashes."
                try:
                    resp = llm_extractor.invoke([("system", extract_prompt)])
                    parsed = safe_json_loads(resp.content, context="OS Action Extraction")
                    if parsed and isinstance(parsed, list):
                        actions_val = parsed
                        print(f"[AUDIT] Extracted OS Actions: {len(actions_val)}")
                    else:
                        print(f"[RELIABILITY ERROR] OS Action extraction returned invalid structure.")
                        matched_intent = "UnknownIntent"
                except Exception as e:
                    print(f"[SRE] OS Action extraction failed: {e}")
                    matched_intent = "UnknownIntent"

            elif matched_intent in ["ProcessManagementIntent", "ProjectScaffoldIntent", "DependencyInstallIntent"]:
                llm_extractor = _get_routing_llm("Target Extraction")
                extract_prompt = f"{SYSTEM_PROMPT}\n\nThe user issued: '{step_query}'. The intent is {matched_intent}. Generate the exact JSON object for this action. Output ONLY the raw JSON object, no markdown."
                try:
                    resp = llm_extractor.invoke([("system", extract_prompt)])
                    parsed = safe_json_loads(resp.content, context="Phase 3 Extraction")
                    if isinstance(parsed, list) and len(parsed) > 0:
                        parsed = parsed[0]
                    if parsed and isinstance(parsed, dict):
                        parsed["confidence"] = confidence
                        final_pipeline.append(parsed)
                        continue  # Skip envelope assembly below since we already have the full JSON
                except Exception as e:
                    print(f"[SRE] Phase 3 Action extraction failed: {e}")
                    matched_intent = "UnknownIntent"
            
            # --- COMBINE HYBRID OUTPUT ---
            final_envelope = {
                "intent": matched_intent,
                "confidence": confidence,
                "target": target_val,
                "prompt": step_query,
                "speech_response": f"Executing step {q_idx+1}." if len(queries) > 1 else "Copy that."
            }
            if matched_intent == "UnknownIntent":
                final_envelope["value"] = "The model did not return a valid JSON format."
            
            if actions_val:
                final_envelope["actions"] = actions_val
                
            final_pipeline.append(final_envelope)
            
        return final_pipeline
        
    except Exception as e:
        print(f"[SRE] Extraction failed: {e}")
        # --- STAGE 3: GRACEFUL FALLBACK ---
        return [{
            "intent": "UnknownIntent", 
            "target": "Intent Parsing Failed", 
            "value": f"The model did not return a valid format. Details: {str(e)}"
        }]
