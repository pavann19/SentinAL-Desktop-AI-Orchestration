# wake_intelligence.py
# SentinAL Wake Intelligence Layer (WIL) v2.0
#
# Architecture:
#   Stage 1: HARDWARE GATE     — Porcupine (near-zero CPU keyword detection)
#   Stage 2: SOFTWORD FILTER   — Text-level fuzzy+phonetic detection on transcript
#   Stage 3: COMMAND EXTRACTOR — Strips wake phrase, returns clean payload
#   Stage 4: INTENT HINT       — Tags embedded command vs pure wake for router
#
# Design Principles:
#   - Deterministic (no LLM involved at any stage)
#   - Sub-1ms matching (pure in-memory operations)
#   - False-positive resilient (multi-stage gating)
#   - Natural language aware (phrase-based, not single-word)

import re
from dataclasses import dataclass, field
from typing import Optional

# ── Identity Configuration ────────────────────────────────────────────────────
# The core identity anchor. All phrase variants must resolve to this.
WAKE_IDENTITY = "jarvis"

# ── Phonetic Codec ────────────────────────────────────────────────────────────
# Maps common misheard pronunciations to the canonical identity.
# Built from real-world STT error analysis on "Jarvis" utterances.
PHONETIC_ALIASES: list[str] = [
    "jarvis", "jarvish", "javis", "jarv", "jarvs", "jarviz",
    "jarves", "jarbi", "jarbis", "gervis", "gervish",
    "jarby",      # baby talk variant
    "jarvas",     # extended vowel
    "jarvet",     # French-accent distortion
    "jarrviss",   # elongation
]

# ── False Positive Suppression ────────────────────────────────────────────────
# Words that look phonetically similar but are statistically almost always
# false triggers based on normal human vocabulary.
FALSE_POSITIVES: set[str] = {
    "java", "harvest", "service", "garbage", "farvis", "nervous", "marvel", "starving"
}

# ── Prefix Patterns ───────────────────────────────────────────────────────────
# Natural spoken prefixes users attach before the identity.
WAKE_PREFIXES: list[str] = [
    r"hey",
    r"okay",
    r"ok",
    r"yo",
    r"listen",
    r"alright",
    r"right",
    r"oi",
    r"hello",
    r"hi",
]

# ── Suffix / Connector Patterns ───────────────────────────────────────────────
# Natural words users append after the identity before the actual command.
WAKE_SUFFIXES: list[str] = [
    r",\s*",     # "Jarvis, open chrome"
    r"\s+",      # natural space
    r"\s+can\s+you\s+",    # "Jarvis can you open..."
    r"\s+please\s+",       # "Jarvis please open..."
    r"\s+would\s+you\s+",  # "Jarvis would you..."
    r"\s+could\s+you\s+(?:please\s+)?(?:just\s+)?",  # "Jarvis could you please just..."
    r"\s+kindly\s+",       # "Jarvis kindly..."
    r"\s+just\s+",         # "Jarvis just..."
]

# ── Interrupt Identity ────────────────────────────────────────────────────────
INTERRUPT_WORDS: set[str] = {"stop", "cancel", "wait", "pause", "halt", "abort", "enough"}

# ── Noise Guard ───────────────────────────────────────────────────────────────
# If a transcript after stripping the wake phrase is shorter than this,
# treat it as pure activation (no embedded command).
MIN_COMMAND_CHARS = 3

# ── Result Dataclass ─────────────────────────────────────────────────────────

@dataclass
class WakeDecision:
    """Result of processing a transcript through the Wake Intelligence Layer."""
    is_wake: bool                          # Was a wake phrase detected?
    confidence: float                      # 0.0-1.0 detection confidence
    method: str                            # How was it detected: "hardware", "exact", "fuzzy", "phonetic"
    raw_transcript: str                    # Original text from STT
    clean_command: Optional[str] = None    # Command with wake phrase stripped (None if pure activation)
    is_interrupt: bool = False             # Was an interrupt word detected?
    is_embedded: bool = False              # Was the command embedded in the wake phrase sentence?
    notes: list[str] = field(default_factory=list)  # Debug trace for logging


# ─────────────────────────────────────────────────────────────────────────────
# WAKE INTELLIGENCE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class WakeIntelligenceEngine:
    """
    Multi-stage wake phrase detector with zero LLM dependency.

    Stages:
        1. Pre-check: length/noise guard (instant reject for garbage input)
        2. Interrupt check: detect stop/cancel before processing
        3. Exact match: direct substring match on the WAKE_IDENTITY
        4. Phonetic match: check every PHONETIC_ALIASES term
        5. Pattern match: full regex for prefix+identity+suffix+command
        6. Command extraction: strip wake phrase, return clean payload
    """

    def __init__(self):
        # Build all variant patterns up-front (one-time cost at startup)
        self._exact_regex = self._compile_exact_pattern()
        self._embedded_regex = self._compile_embedded_pattern()
        self._alias_set = set(PHONETIC_ALIASES)  # O(1) lookup

    # ── Pattern Compilation ───────────────────────────────────────────────────

    def _compile_exact_pattern(self) -> re.Pattern:
        """Pattern that captures: [optional prefix] + identity + [optional suffix+command]."""
        prefix_group = r"(?:" + r"|".join(WAKE_PREFIXES) + r")?\s*"
        identity = re.escape(WAKE_IDENTITY)
        return re.compile(
            rf"^{prefix_group}({identity})\b",
            re.IGNORECASE
        )

    def _compile_embedded_pattern(self) -> re.Pattern:
        """Pattern for embedded commands like 'Jarvis, open chrome' or 'Hey Jarvis search news'."""
        aliases = r"|".join(re.escape(a) for a in PHONETIC_ALIASES)
        prefix_group = r"(?:" + r"|".join(WAKE_PREFIXES) + r")?\s*"
        suffix_group = r"(?:" + r"|".join(WAKE_SUFFIXES) + r")"
        return re.compile(
            rf"^{prefix_group}(?:{aliases}){suffix_group}(.+)$",
            re.IGNORECASE
        )

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase strip + collapse whitespace + remove punctuation artifacts."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s,]", " ", text)  # keep commas for suffix regex
        text = re.sub(r"\s{2,}", " ", text)
        return text

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        """Compute edit distance — used for fuzzy matching of near-miss aliases."""
        if abs(len(a) - len(b)) > 3:
            return 99  # Quick-reject: too different in length
        if len(a) == 0: return len(b)
        if len(b) == 0: return len(a)
        mat = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            prev, mat[0] = mat[0], i
            for j, cb in enumerate(b, 1):
                prev, mat[j] = mat[j], min(mat[j] + 1, mat[j-1] + 1, prev + (0 if ca == cb else 1))
        return mat[-1]

    def _fuzzy_word_match(self, word: str, position_idx: int = 0) -> tuple[bool, float]:
        """
        Checks if a single word is a fuzzy match to any known alias.
        Applies a positional penalty (later words lower the confidence) to prevent
        random mid-sentence false positives if 'java' or similar is spoken.
        """
        if not word or len(word) < 4:  # Raised from 3 to 4 to block tiny words like 'jar', 'job'
            return False, 0.0

        if word in FALSE_POSITIVES:
            return False, 0.0

        best_conf = 0.0
        # Exact alias hit
        if word in self._alias_set:
            best_conf = 1.0
        else:
            # Levenshtein tolerance: max 2 edits for words ≥ 6 chars, 1 edit for shorter
            threshold = 2 if len(word) >= 6 else 1
            for alias in self._alias_set:
                dist = self._levenshtein(word, alias)
                if dist <= threshold:
                    conf = 1.0 - (dist / max(len(alias), len(word)))
                    if conf > best_conf:
                        best_conf = conf

        if best_conf > 0.0:
            # Position Penalty: Index 0 gets 1.0x, Index 1 gets 0.95x, Index 2 gets 0.85x
            # Words trailing at the end of a sentence are much less likely to be actual wake words
            penalty_multiplier = 1.0 - (position_idx * 0.05) if position_idx < 3 else 0.80
            final_conf = best_conf * penalty_multiplier
            return True, round(final_conf, 2)

        return False, 0.0

    # ── Command Extraction ────────────────────────────────────────────────────

    def _extract_command(self, normalized: str) -> Optional[str]:
        """
        Strips the wake phrase from the transcript, handles multi-wake collisions,
        and aggressively cleans connective phrasing.
        """
        cmd = None
        
        # 1. Try embedded pattern first (handles 'Okay Jarvis, open chrome')
        m = self._embedded_regex.match(normalized)
        if m:
            cmd = m.group(1).strip()
        else:
            # 2. Iterate and split on first phonetic hit
            words = normalized.split()
            for i, word in enumerate(words):
                matched, _ = self._fuzzy_word_match(word, i)
                if matched and i < 4:  # Allow up to 4th word just in case
                    remainder = " ".join(words[i+1:]).strip()
                    if remainder:
                        cmd = remainder
                    break

        if cmd:
            # 3. Multi-Wake Collision Cleanup
            # If the user says "Jarvis hey Jarvis do this", strip subsequent aliases
            aliases_pattern = r"\b(?:" + r"|".join(re.escape(a) for a in PHONETIC_ALIASES) + r")\b"
            cmd = re.sub(aliases_pattern, "", cmd, flags=re.IGNORECASE)

            # 4. Strip aggressive connectors & residual punctuation
            cmd = re.sub(r"^(?:hey|okay|ok|can you|could you|please|would you|i need|just|tell me to|tell|ask)\s+", "", cmd).strip()
            cmd = re.sub(r"^[,.\s]+", "", cmd).strip()
            
            if cmd and len(cmd) >= MIN_COMMAND_CHARS:
                return cmd

        return None

    # ── Main Processing Pipeline ──────────────────────────────────────────────

    def process(self, transcript: str, hardware_fired: bool = False) -> WakeDecision:
        """
        Full wake decision pipeline. Call this on every STT transcript.

        Args:
            transcript:     Raw text from Deepgram / STT engine
            hardware_fired: True if Porcupine hardware already confirmed a keyword

        Returns:
            WakeDecision with all metadata about the detection
        """
        notes = []

        # ── Stage 0: Hardware Fast-Path ─────────────────────────────────────
        if hardware_fired:
            notes.append("hardware_gate_passed")
            # Even with hardware gate, still strip wake phrase for command extraction
            normalized = self._normalize(transcript)
            clean_cmd = self._extract_command(normalized)
            is_interrupt = bool(
                clean_cmd and any(w in clean_cmd.lower().split() for w in INTERRUPT_WORDS)
            )
            return WakeDecision(
                is_wake=True,
                confidence=0.99,
                method="hardware",
                raw_transcript=transcript,
                clean_command=clean_cmd,
                is_interrupt=is_interrupt,
                is_embedded=(clean_cmd is not None),
                notes=notes
            )

        # ── Stage 1: Noise/Length Guard ──────────────────────────────────────
        if not transcript or len(transcript.strip()) < 2:
            return WakeDecision(False, 0.0, "rejected", transcript, notes=["too_short"])

        normalized = self._normalize(transcript)
        words = normalized.split()

        # ── Stage 2: Interrupt Pre-check ────────────────────────────────────
        # Interrupts bypass wake detection and are handled separately
        if any(w in INTERRUPT_WORDS for w in words):
            notes.append("interrupt_detected")
            return WakeDecision(
                is_wake=False,
                confidence=0.0,
                method="interrupt",
                raw_transcript=transcript,
                is_interrupt=True,
                notes=notes
            )

        # ── Stage 3: Exact Match ─────────────────────────────────────────────
        if self._exact_regex.search(normalized):
            notes.append("exact_match")
            clean_cmd = self._extract_command(normalized)
            return WakeDecision(
                is_wake=True,
                confidence=0.97,
                method="exact",
                raw_transcript=transcript,
                clean_command=clean_cmd,
                is_interrupt=False,
                is_embedded=(clean_cmd is not None),
                notes=notes
            )

        # ── Stage 4: Phonetic / Alias Match ─────────────────────────────────
        # Check each word in the first 4 tokens for a phonetic hit
        for i, word in enumerate(words[:4]):
            matched, conf = self._fuzzy_word_match(word, i)
            if matched:
                # Require higher confidence for phonetic hits that appear later in the sentence
                if conf < 0.70:
                    notes.append(f"phonetic_rejected:'{word}' conf={conf}<0.70")
                    continue
                notes.append(f"phonetic_match:'{word}' conf={conf}")
                clean_cmd = self._extract_command(normalized)
                return WakeDecision(
                    is_wake=True,
                    confidence=conf,
                    method="phonetic",
                    raw_transcript=transcript,
                    clean_command=clean_cmd,
                    is_interrupt=False,
                    is_embedded=(clean_cmd is not None),
                    notes=notes
                )

        # ── Stage 5: No Match ────────────────────────────────────────────────
        notes.append("no_match")
        return WakeDecision(
            is_wake=False,
            confidence=0.0,
            method="rejected",
            raw_transcript=transcript,
            notes=notes
        )


# ── Singleton ────────────────────────────────────────────────────────────────
wake_intelligence = WakeIntelligenceEngine()
