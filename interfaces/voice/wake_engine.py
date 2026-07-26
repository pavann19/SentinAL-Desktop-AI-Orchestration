# wake_engine.py
# SentinAL Wake Response Engine v2.0
#
# Generates the instant verbal acknowledgement when the Wake Intelligence
# Layer confirms activation. 100% deterministic — no LLM involved.
#
# Layers:
#   - Time-of-day context (morning / afternoon / evening / night)
#   - Returning-user detection (gap > 60 min)
#   - Embedded command fast-path (skip greeting when command already given)
#   - Personality layer (JARVIS-style brevity + warmth)

import random
import time
from datetime import datetime


class WakeResponseEngine:
    """
    Generates a context-aware, personality-driven acknowledgement response
    when SentinAL is activated. Near-zero latency — all responses are
    pre-defined templates selected deterministically.
    """

    # ── Response Templates ────────────────────────────────────────────────────

    TEMPLATES = {
        "morning": [
            "Good morning, Boss.",
            "Morning. Systems fully online.",
            "Ready for the day.",
            "Morning. What do you need?",
        ],
        "afternoon": [
            "I'm here.",
            "Afternoon. Standing by.",
            "Ready.",
            "Good afternoon, Boss.",
        ],
        "evening": [
            "Good evening.",
            "Evening, Boss. What's the mission?",
            "Systems operational. Ready.",
            "Standing by.",
        ],
        "night": [
            "Still at it, Boss?",
            "I'm here.",
            "Up late. What do you need?",
            "Night owl mode. Ready.",
        ],
        "returning": [
            "Welcome back.",
            "You're back. Systems ready.",
            "Online and ready, Boss.",
            "Good to have you back.",
        ],
        "standard": [
            "Yes.",
            "Go ahead.",
            "I'm listening.",
            "At your service.",
            "Ready.",
        ],
        "rapid_retry": [
            "Still here, Boss.",
            "I'm listening.",
            "Go ahead, I caught that.",
            "Yes, Boss.",
        ],
        "weekend": [
            "Happy weekend, Boss. What's up?",
            "Relaxing today? I'm ready.",
            "Weekend mode active.",
        ],
        "terse": [
            "Go.",
            "Yes.",
            "Ready.",
        ],
        # When the wake phrase includes an embedded command, skip the greeting
        # and give a brief acknowledgement that signals execution:
        "executing": [
            "On it.",
            "Right away.",
            "Processing.",
            "Got it.",
        ],
    }

    # ── Public Interface ──────────────────────────────────────────────────────

    @classmethod
    def get_response(cls, last_active_time: float = 0, has_command: bool = False, system_load: str = "OPTIMAL") -> str:
        """
        Return the best wake acknowledgement given context.

        Args:
            last_active_time: Unix timestamp of last interaction (0 if never).
            has_command:      True if user embedded a command in the wake phrase
                              (e.g. "Jarvis, open Chrome"). In this case, return
                              a short exec-acknowledgement instead of a greeting.
            system_load:      Current CPU/TaskManager load (e.g., 'OPTIMAL', 'STRAINED').
        """
        # Fast-path: embedded command gets a brief "On it." style response
        if has_command:
            return random.choice(cls.TEMPLATES["executing"])

        if system_load == "STRAINED":
            return random.choice(cls.TEMPLATES["terse"])

        now = datetime.now()
        hour = now.hour
        is_weekend = now.weekday() >= 5
        
        time_since_last_active = time.time() - last_active_time if last_active_time > 0 else float('inf')
        is_returning = time_since_last_active > 3600
        is_rapid_retry = time_since_last_active < 8  # Invoked again within 8 seconds

        if is_rapid_retry:
            category = "rapid_retry"
        elif is_returning:
            category = "returning"
        elif is_weekend and random.random() < 0.3:
            category = "weekend"
        elif 5 <= hour < 12:
            category = "morning"
        elif 12 <= hour < 17:
            category = "afternoon"
        elif 17 <= hour < 22:
            category = "evening"
        else:
            category = "night"

        # 25% of the time, use a generic "standard" reply for variety
        if random.random() < 0.25:
            category = "standard"

        return random.choice(cls.TEMPLATES[category])

    @classmethod
    def get_wake_response(cls, context=None) -> str:
        """
        Compatibility entry point for the conversational OS layer.
        Accepts a system state snapshot dict.
        """
        context = context or {}
        last_active = (
            context.get("last_interaction_time")
            or context.get("last_interaction")
            or 0
        )
        has_command = context.get("has_embedded_command", False)
        # Check system threat level/load from context if available
        system_load = context.get("ai_core_status", "OPTIMAL") 
            
        return cls.get_response(last_active_time=last_active, has_command=has_command, system_load=system_load)


# ── Singleton accessor ────────────────────────────────────────────────────────
wake_engine = WakeResponseEngine()
