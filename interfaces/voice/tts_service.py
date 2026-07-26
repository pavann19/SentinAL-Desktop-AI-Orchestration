# services/tts_service.py
# Modular Text-to-Speech Service using the Kokoro-ONNX model.
# Features: Natural-sounding offline voice, low-latency playback, and auto-sanitization.
#
# V2.0 Fixes:
#   Fix 2.2 — FAST_PHRASE_CACHE is now LRUCache(maxsize=50) — prevents unbounded memory leak.
#   Fix 2.3 — sd.get_stream().active polling wrapped in try/except RuntimeError.
#              Prevents crash when stream finishes before polling loop starts.
#   Fix 2.4 — Removed `sd.default.device[1] = None` global mutation (thread-unsafe no-op).

import os
import re
import time
import numpy as np
import sounddevice as sd
from kokoro_onnx import Kokoro
from cachetools import LRUCache

# ── Configuration ────────────────────────────────────────────────────────────
MODEL_PATH  = os.path.join(os.getcwd(), "data", "models", "kokoro-v1.0.onnx")
VOICES_PATH = os.path.join(os.getcwd(), "data", "models", "voices-v1.0.bin")
LANG_CODE   = 'en-us'
VOICE_NAME  = 'af_heart'

# ── Singleton & Cache ─────────────────────────────────────────────────────────
import threading
_tts_instance = None
_tts_init_lock = threading.Lock()  # FIX 5: Prevents race-condition re-init from asyncio.to_thread

# Fix 2.2: Bounded LRU cache (max 50 entries) — replaces unbounded `{}` dict
FAST_PHRASE_CACHE: LRUCache = LRUCache(maxsize=50)


def speak(text: str, speed: float = 1.0, cancel_event=None,
          mode: str = "HQ", pause_duration: float = 0.0):
    """
    Global entry point for the TTS service.
    Initializes the engine ONCE on cold start, then reuses the singleton.
    FIX 5: Lock ensures only one thread initializes — prevents duplicate
    '[SRE] Initializing Kokoro-ONNX TTS' log spam on concurrent calls.
    """
    global _tts_instance
    if _tts_instance is None:
        with _tts_init_lock:
            if _tts_instance is None:  # Double-check inside lock
                _tts_instance = TTSService()
    _tts_instance.speak(text, speed, cancel_event, mode=mode, pause_duration=pause_duration)


def stop():
    """Immediately halts any active TTS playback."""
    global _tts_instance
    if _tts_instance is not None:
        _tts_instance.stop()


class TTSService:
    """
    State-of-the-art Text-to-Speech service using the Kokoro-ONNX engine.
    Implements a clean voice output layer with automatic text filtering.
    """

    def __init__(self, model_path=MODEL_PATH, voices_path=VOICES_PATH,
                 lang_code=LANG_CODE, voice=VOICE_NAME):
        """Initializes the Kokoro-ONNX TTS engine."""
        print(f"[SRE] Initializing Kokoro-ONNX TTS (voice='{voice}')...")
        try:
            if not os.path.exists(model_path) or not os.path.exists(voices_path):
                raise FileNotFoundError("Model or voices file not found in data/models/.")
            self.kokoro    = Kokoro(model_path, voices_path)
            self.lang_code = lang_code
            self.voice     = voice
        except Exception as e:
            print(f"[SRE] TTS init failed: {e}")
            self.kokoro = None

    def _sanitize_text(self, text: str) -> str:
        """
        Strips JSON blocks, terminal commands, and Markdown formatting.
        Ensures the assistant only speaks the natural language part.
        """
        # 1. Remove Markdown code blocks
        clean = re.sub(r'```[\s\S]*?```', '', text)

        # 2. Remove JSON arrays/objects
        clean = re.sub(r'\[\s*\{.*\}\s*\]', '', clean, flags=re.DOTALL)
        clean = re.sub(r'\{\s*".*":.*\s*\}', '', clean, flags=re.DOTALL)

        # 3. Remove shell command lines
        lines = clean.split('\n')
        filtered_lines = []
        for line in lines:
            trimmed = line.strip()
            if re.match(r'^(mkdir|cd|npx|npm|pip|python|dir|ls|cls|cmd|copy|move|del|rd)\b',
                        trimmed, re.IGNORECASE):
                continue
            if re.match(r'^[a-zA-Z]:\\|^%USERPROFILE%|^[./\\]', trimmed):
                continue
            filtered_lines.append(line)

        clean = "\n".join(filtered_lines).strip()
        clean = re.sub(r'\n+', ' ', clean)
        return clean

    def speak(self, text: str, speed: float = 1.0, cancel_event=None,
              mode: str = "HQ", pause_duration: float = 0.0):
        """
        Converts text to speech and plays it immediately.
        Filters out system commands and JSON structures before speaking.
        If a cancel_event is provided, actively polls it to interrupt playback.
        """
        if not self.kokoro:
            print("[SRE] TTS speak failed: Engine not initialized.")
            return

        clean_text = self._sanitize_text(text)
        if not clean_text:
            print("[SRE] TTS skipped: natural language part is empty.")
            return

        mode = (mode or "HQ").upper()
        if mode == "FAST":
            clean_text = clean_text.split(".")[0].strip() or clean_text
            speed = max(speed, 1.1)

        print(f"[AUDIT] TTS speaking [{mode}]: \"{clean_text[:80]}...\"")

        try:
            cache_key = (clean_text, speed, self.voice, self.lang_code)
            if mode == "FAST" and cache_key in FAST_PHRASE_CACHE:
                samples, sample_rate = FAST_PHRASE_CACHE[cache_key]
            else:
                samples, sample_rate = self.kokoro.create(
                    clean_text,
                    voice=self.voice,
                    speed=speed,
                    lang=self.lang_code
                )
                if mode == "FAST":
                    FAST_PHRASE_CACHE[cache_key] = (samples, sample_rate)

            if samples is not None and len(samples) > 0:
                print(f"[AUDIT] TTS playing at {sample_rate}Hz")
                try:
                    # Fix 2.4: Removed `sd.default.device[1] = None` — it was a
                    # thread-unsafe global mutation. sd.play() uses system default automatically.
                    sd.play(samples, sample_rate)

                    if cancel_event:
                        # Fix 2.3: Wrapped in try/except RuntimeError — sd.get_stream()
                        # raises RuntimeError if stream already finished before polling starts.
                        try:
                            while sd.get_stream().active:
                                if cancel_event.is_set():
                                    print("[SRE] TTS UI Interrupt received! Aborting hardware stream.")
                                    sd.stop()
                                    break
                                time.sleep(0.05)
                        except RuntimeError:
                            pass  # Stream already finished — normal on short phrases
                    else:
                        sd.wait()

                    if pause_duration > 0:
                        time.sleep(pause_duration)

                except sd.PortAudioError as pa_err:
                    print(f"[SRE] TTS audio device error: {pa_err}")
                    print("[SRE] Ensure speakers/headphones are connected.")
                except Exception as play_err:
                    print(f"[SRE] TTS playback failed: {play_err}")

        except Exception as e:
            print(f"[SRE] TTS generation failed: {e}")

    def stop(self):
        """Mechanically stops the sounddevice audio playback."""
        print("[SRE] Mechanically aborting TTS playback.")
        sd.stop()


if __name__ == "__main__":
    tts = TTSService()
    test_input = """
    Certainly! I'll set up that React project for you now.
    [{"intent": "WorkspaceAutomationIntent", "target": "mkdir project && cd project && npx create-react-app ."}]
    This process might take a minute depending on your network speed.
    """
    print("\n[Test] Running sanitization & speech verification...")
    tts.speak(test_input)
    print("\n[Test Complete]")
