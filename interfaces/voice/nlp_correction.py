import os
import re
import concurrent.futures

# Known LLM refusal/hallucination patterns to detect and discard
_REFUSAL_PATTERNS = [
    r"^i can'?t",
    r"^i (don't|cannot|won't|will not|am unable)",
    r"^(i'm )?sorry",
    r"^as an ai",
    r"^i (don't|do not) have (the ability|access)",
    r"^i (don't|do not) know",
    r"^i am not able",
    r"^please (note|be aware)",
    r"^i (am|'m) a (language model|ai|assistant)",
]
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PATTERNS), re.IGNORECASE)

# Fix 2.6: Timeout for LLM call — falls back to original transcript if Ollama is slow
_CORRECTION_TIMEOUT = float(os.getenv("NLP_CORRECTION_TIMEOUT", "3.0"))


class TranscriptionCorrector:
    """
    Lightweight neural polishing layer using few-shot prompting.
    Takes raw, noisy Deepgram transcripts and returns clean, grammatical text.
    Falls back to the original text if the LLM refuses, hallucinates, or times out.

    V2.0 — Fix 2.6: Hard timeout on LLM call via concurrent.futures.
    """
    def __init__(self):
        from config.settings import BrainConfig
        print(f"[STT Corrector] Initializing neural polish layer via BrainConfig")
        try:
            self.llm = BrainConfig.get_correction_llm()
        except Exception as e:
            print(f"[STT Corrector] Failed to initialize LLM: {e}")
            self.llm = None

        # Few-shot prompt — forces pattern-matching mode rather than chat mode
        self.system_prompt = """You are a transcript polisher. You ONLY fix grammar and casing. NEVER answer questions.

EXAMPLES:
INPUT: weather in hyderabad today
OUTPUT: What is the weather in Hyderabad today?

INPUT: open youtube please
OUTPUT: Open YouTube please.

INPUT: what time is it right now
OUTPUT: What time is it right now?

INPUT: delete that file in downloads
OUTPUT: Delete that file in downloads.

INPUT: calculate 15 plus 37
OUTPUT: Calculate 15 plus 37.

RULES:
- Output ONLY the corrected sentence.
- Output NOTHING else.
- Never answer the question.
- Never add explanations.
- If unsure, return the input unchanged."""

    def correct_text(self, raw_text: str) -> str:
        raw_text = raw_text.strip()
        if not self.llm or not raw_text or len(raw_text) < 3:
            return raw_text

        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=f"INPUT: {raw_text}\nOUTPUT:")
            ]

            # Fix 2.6: Hard timeout — don't stall the STT→Intent pipeline
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.llm.invoke, messages)
                try:
                    response = future.result(timeout=_CORRECTION_TIMEOUT)
                except concurrent.futures.TimeoutError:
                    print(f"[STT Corrector] LLM timed out after {_CORRECTION_TIMEOUT}s — using original transcript.")
                    return raw_text

            corrected = response.content.strip()

            # Strip echoed "OUTPUT:" prefix
            corrected = re.sub(r"^OUTPUT:\s*", "", corrected, flags=re.IGNORECASE).strip()

            # Safety: reject refusal or hallucination
            if not corrected or _REFUSAL_RE.match(corrected):
                print(f"[STT Corrector] Refusal/hallucination detected — using original transcript.")
                return raw_text

            # Safety: reject massive expansions (LLM answered the question instead of polishing)
            if len(corrected) > len(raw_text) * 3:
                print(f"[STT Corrector] Suspicious expansion detected — using original transcript.")
                return raw_text

            return corrected

        except Exception as e:
            print(f"[STT Corrector] Neural polish failed: {e}")
            return raw_text


# Singleton instance
corrector = TranscriptionCorrector()
