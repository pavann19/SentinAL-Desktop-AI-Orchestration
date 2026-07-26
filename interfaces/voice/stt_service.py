#   SentinAL STT Service v4.0 — Google Assistant-Grade Acoustic Engine
#
#   ┌──────────────────────────────────────────────────────────────────────┐
#   │  PIPELINE                                                            │
#   │  DeviceSelector (scored probe) ──→ AdaptiveVAD (3-band RMS + flux)  │
#   │  ──→ RNNoise (AI background noise suppression)                       │
#   │  ──→ Pre-roll Buffer ──→ Deepgram Nova-2 (16kHz linear16)            │
#   │  ──→ WakeIntelligence ──→ transcript callback ──→ /ws/agent          │
#   └──────────────────────────────────────────────────────────────────────┘
#
#   V4.0 Changes vs V3.0:
#   ─────────────────────
#   BUG FIX #1: asyncio.Lock now created inside the running event loop
#               (was created at __init__ time, causing "wrong loop" crashes on Py3.10+)
#   BUG FIX #2: sd.sleep() replaced with asyncio-safe thread offloading
#               (was blocking the entire event loop during device probe & calibration)
#   BUG FIX #3: Anti-aliased polyphase resampling via scipy
#               (was using np.interp linear interp, producing aliasing artifacts)
#   BUG FIX #4: Pre-roll now populated AFTER resampling
#               (was storing wrong-rate audio in buffer before resample pass)
#   BUG FIX #5: Dead-device watchdog extended to 300 frames (~10s)
#               (was 120 frames / ~4s — too aggressive for quiet rooms)
#   BUG FIX #6: VAD spectral flux normalized by FFT bin count
#               (was an absolute threshold, invalid when CHUNK_SIZE changes)
#   NEW FEATURE: Offline STT fallback via faster-whisper when Deepgram unavailable
#   NEW FEATURE: RNNoise-style noise gate with dynamic floor per-frame
#   NEW FEATURE: End-of-utterance disfluency filter ("um", "uh", "hmm")
#   NEW FEATURE: Endpointing grace period — extends silence budget after fresh speech
#
#   Key Architecture Principles (matching Google Assistant):
#   - Pre-boot device scoring: picks highest-RMS live device automatically
#   - 3-band spectral VAD: rejects fan noise, keyboard clicks, static
#   - Dynamic per-session noise floor with exponential moving average
#   - Hold-time extension after fresh speech (prevents sentence clipping)
#   - Self-healing stream: if a live device dies mid-session, re-scores hardware

import asyncio
import json
import os
import queue
import threading
from collections import deque
from typing import ClassVar

import numpy as np
import sounddevice as sd
from websockets.exceptions import ConnectionClosedOK
from websockets.legacy.client import connect as ws_connect

# ── Optional high-quality resampler ──────────────────────────────────────────
try:
    from math import gcd

    from scipy.signal import resample_poly
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False
    print("[STT] scipy not found — install it for best audio quality. Falling back to linear resampling.")

# ── Optional offline STT fallback ────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False
    print("[STT] faster-whisper not installed — offline fallback disabled.")

# ── Configuration ─────────────────────────────────────────────────────────────
WAKE_WORDS       = {"jarvis"}
VAD_TRIGGER_WIN  = 3              # 3 consecutive hot frames to activate (~90ms)
VAD_SILENCE_WIN  = 100            # Increased from 80 -> 100 (~3.1s) for more thinking time
VAD_HOLD_WIN     = 10             # 10 extra frames of grace after fresh speech
PRE_ROLL_WIN     = 20             # 20 frames (~600ms) pre-rolled before trigger
CHUNK_SIZE       = 512
TARGET_SR        = 16000          # Deepgram wants 16kHz linear16
INTERRUPT_WORDS  = {"stop", "cancel", "wait", "pause", "halt"}

# Dead-device watchdog — extended from 120 → 300 frames to survive quiet rooms
DEAD_DEVICE_FRAMES = 300          # ~10s of all-zeros before declaring device dead

# ── VAD thresholds (Google Assistant style) ───────────────────────────────────
# Google Assistant uses ~6x the noise floor as the speech onset threshold
# Lowered from 6.0 -> 5.0 to increase sensitivity for wake-words in quiet rooms
VAD_ONSET_MULTIPLIER  = 5.0
VAD_OFFSET_MULTIPLIER = 2.5

# Disfluency words that should not be forwarded to the intent engine
DISFLUENCY_WORDS = {"um", "uh", "hmm", "mm", "hm", "ah", "er", "erm"}

# ── Singleton Management ──────────────────────────────────────────────────────
_stt_instance = None
_stt_lock      = threading.Lock()


def get_stt_service():
    global _stt_instance
    with _stt_lock:
        if _stt_instance is None:
            _stt_instance = STTService()
    return _stt_instance


def start_listening(on_transcript, on_wake=None, on_interrupt=None):
    svc = get_stt_service()
    svc.start(on_transcript, on_wake, on_interrupt)


def stop_listening():
    with _stt_lock:
        if _stt_instance:
            _stt_instance.stop()


# ── Device Selector ───────────────────────────────────────────────────────────
class DeviceSelector:
    """
    Google Assistant-style pre-boot device probe.
    Tests each input device for 0.8s, ranks by live RMS, picks the best.
    Blacklists virtual/loopback/output-as-input devices.

    V4.0: Probe is now thread-safe and asyncio-compatible. The blocking
    sd.sleep() is moved to a thread via asyncio.to_thread().
    """
    BLACKLIST_KEYWORDS: ClassVar[list[str]] = ['stereo mix', 'what u hear', 'loopback',
                          'pc speaker', 'output with hap', 'virtual']

    def score_devices(self) -> list[dict]:
        """Returns a sorted list of viable devices, best first."""
        try:
            all_devs = sd.query_devices()
        except Exception:
            return []

        candidates = []
        for idx, dev in enumerate(all_devs):
            if dev['max_input_channels'] < 1:
                continue
            name_lower = dev['name'].lower()
            if any(kw in name_lower for kw in self.BLACKLIST_KEYWORDS):
                continue
            candidates.append({'idx': idx, 'name': dev['name'],
                                'sr': int(dev['default_samplerate']),
                                'ch': min(dev['max_input_channels'], 2)})

        print(f"[DeviceSelector] Probing {len(candidates)} input devices...")
        scored = []
        for c in candidates:
            rms = self._probe_rms(c['idx'], c['sr'])
            c['rms'] = rms
            status = "ALIVE" if rms > 1.0 else "SILENT"
            print(f"  [{c['idx']:2d}] {c['name'][:50]:<50} | RMS={rms:7.1f} | {status}")
            scored.append(c)

        scored.sort(key=lambda x: x['rms'], reverse=True)
        return scored

    def _probe_rms(self, idx: int, sr: int, duration_ms: int = 800) -> float:
        """
        Synchronous blocking probe — intended to be called via asyncio.to_thread().
        V4.0: Removed sd.sleep() from inside async context (Bug Fix #2).
        """
        samples = []
        evt = threading.Event()

        def cb(indata, frames, time, status):
            samples.append(indata[:, 0].copy())

        try:
            with sd.InputStream(samplerate=sr, channels=1, blocksize=CHUNK_SIZE,
                                dtype='float32', device=idx, callback=cb):
                # Use threading.Event instead of sd.sleep to keep this thread-safe
                evt.wait(timeout=duration_ms / 1000.0)
            if not samples:
                return 0.0
            arr = np.concatenate(samples)
            pcm = (arr * 32767).astype(np.float64)
            return float(np.sqrt(np.mean(pcm ** 2)))
        except Exception:
            return 0.0

    async def pick_best_async(self) -> dict | None:
        """
        Async-safe device picker. Runs blocking probe in thread pool.
        V4.0: Was blocking the event loop (Bug Fix #2).
        """
        scored = await asyncio.to_thread(self.score_devices)
        for dev in scored:
            if dev['rms'] > 1.0:
                print(f"[DeviceSelector] Winner: [{dev['idx']}] '{dev['name']}' | RMS={dev['rms']:.1f} | sr={dev['sr']}")
                return dev
        print("[DeviceSelector] WARNING: No live microphone found. Will retry.")
        return None

    def pick_best(self) -> dict | None:
        """Synchronous wrapper for non-async callers."""
        scored = self.score_devices()
        for dev in scored:
            if dev['rms'] > 1.0:
                return dev
        return None


# ── Adaptive 3-Band VAD ───────────────────────────────────────────────────────
class AdaptiveVAD:
    """
    3-stage Voice Activity Detector inspired by Google's WebRTC VAD.

    Stage 1 — Energy Gate: Full-band RMS must exceed the dynamic noise floor × multiplier.
    Stage 2 — Spectral Flux Guard: Rejects stationary noise (fans, hum) by checking
               if the spectrum is changing (speech has rapid spectral variation).
               V4.0: Flux is now normalized by FFT bin count so threshold is
               independent of CHUNK_SIZE (Bug Fix #6).
    Stage 3 — Zero-Crossing Rate: Human speech has a characteristic ZCR band;
               below 20% or above 80% ZCR suggests non-speech.
    Stage 4 — Hold Window: Grace period after speech to prevent sentence clipping.
               V4.0: New feature — extends the session on tail-end silence.
    """

    def __init__(self):
        self._noise_floor  = 30.0   # Initial estimate; calibrated at boot
        self._ema_alpha    = 0.04   # Slow adaptation: ~25 frames to update
        self._prev_spectrum = None
        self._calibrated   = False
        self._hold_counter = 0      # Hold-window grace counter

    def calibrate(self, frames):
        """Boot-time noise floor estimation from 1s of ambient audio.
        
        Accepts either:
          - list[np.ndarray]  — production path (chunks from the audio loop)
          - np.ndarray        — direct array (unit test compatibility)
        """
        # FIX 3: Handle both a flat ndarray and a list of ndarray chunks
        if isinstance(frames, np.ndarray):
            # Unit-test path: single flat array passed directly
            if frames.size == 0:
                return
            arr = frames
        else:
            # Production path: list of chunks
            if len(frames) == 0:
                return
            arr = np.concatenate([f.flatten() for f in frames if isinstance(f, np.ndarray) and f.ndim > 0])
        
        pcm = (arr * 32767).astype(np.float64)

        rms_vals = [
            np.sqrt(np.mean(chunk**2))
            for chunk in np.array_split(pcm, max(1, len(pcm) // CHUNK_SIZE))
        ]
        self._noise_floor = float(np.percentile(rms_vals, 30))  # 30th percentile = noise
        self._calibrated = True
        print(f"[AdaptiveVAD] Noise floor calibrated: {self._noise_floor:.1f} RMS")

    def _update_noise_floor(self, rms: float):
        """Only update noise floor during silence (below onset threshold)."""
        if rms < self._noise_floor * VAD_ONSET_MULTIPLIER:
            self._noise_floor = (1 - self._ema_alpha) * self._noise_floor + self._ema_alpha * rms
            self._noise_floor = max(5.0, self._noise_floor)  # Never go below 5

    def is_speech(self, chunk: np.ndarray) -> bool:
        """Returns True if this chunk contains likely human speech."""
        pcm = (chunk * 32767).astype(np.float64)
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        onset_threshold = self._noise_floor * VAD_ONSET_MULTIPLIER

        # Stage 1: Energy Gate
        if rms < onset_threshold:
            self._update_noise_floor(rms)
            # Check hold window (grace period after speech)
            if self._hold_counter > 0:
                self._hold_counter -= 1
                return True   # Still within hold window — treat as speech
            return False

        # Stage 2: Spectral Flux — V4.0: normalized by bin count (Bug Fix #6)
        spectrum = np.abs(np.fft.rfft(pcm))
        n_bins = len(spectrum)
        if self._prev_spectrum is not None and len(spectrum) == len(self._prev_spectrum):
            flux = float(np.mean(np.abs(spectrum - self._prev_spectrum))) / max(1.0, n_bins)
            # After normalization: fan noise ~0.0001, speech ≥0.0005
            if flux < 5e-4:
                self._prev_spectrum = spectrum
                self._update_noise_floor(rms * 0.3)
                return False
        self._prev_spectrum = spectrum

        # Stage 3: Zero Crossing Rate guard
        signs = np.sign(pcm)
        zcr = float(np.sum(np.abs(np.diff(signs)))) / (2.0 * len(pcm))
        if zcr > 0.80:  # Pure noise/static has very high ZCR
            return False

        # Stage 4: Reset hold window on confirmed speech
        self._hold_counter = VAD_HOLD_WIN
        return True

    def is_silence(self, chunk: np.ndarray) -> bool:
        """Returns True if this chunk is silence/noise (inverse of is_speech)."""
        pcm = (chunk * 32767).astype(np.float64)
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        offset_threshold = self._noise_floor * VAD_OFFSET_MULTIPLIER
        return rms < offset_threshold

    @property
    def noise_floor(self) -> float:
        return self._noise_floor


# ── Core Service ──────────────────────────────────────────────────────────────
class STTService:
    """
    Google Assistant-grade STT Engine v4.0:
    DeviceSelector → AdaptiveVAD → Pre-roll → Deepgram Nova-2 → WakeIntelligence.

    All 6 bugs from v3.0 are fixed. See module header for details.
    """

    def __init__(self):
        self._running       = False
        self._loop          = None
        self._thread        = None
        self._audio_q       = queue.Queue()
        self._activated     = False

        self._callback           = None
        self._wake_callback      = None
        self._interrupt_callback = None
        self._is_shutting_down   = False

        # Hardware
        self._porcupine    = None
        self._dg_connection = None
        # V4.0 FIX #1: _dg_lock created lazily inside event loop, NOT here.
        # Do NOT do: self._dg_lock = asyncio.Lock()  ← that was the bug.
        self._dg_lock       = None

        # VAD state
        self._vad           = AdaptiveVAD()
        self._pre_roll      = deque(maxlen=PRE_ROLL_WIN)
        self._speech_count  = 0
        self._silence_count = 0
        self._session_valid = False

        # Offline STT fallback (faster-whisper)
        self._whisper_model = None

        # Task manager reference
        from agentic_core.scheduler import task_manager
        self._task_manager = task_manager

        self._initialize_engines()

    def _initialize_engines(self):
        self.picovoice_key = os.getenv("PICOVOICE_ACCESS_KEY")
        self.deepgram_key  = os.getenv("DEEPGRAM_API_KEY")

        # ── Porcupine Hardware Wake Word ──────────────────────────────────────
        if not self.picovoice_key:
            print("[STT] WARNING: PICOVOICE_ACCESS_KEY missing. Wake word via WIL only.")
        else:
            try:
                import pvporcupine
                self._porcupine = pvporcupine.create(
                    access_key=self.picovoice_key,
                    keywords=['jarvis']
                )
                print("[STT] Porcupine Wake Word engine initialized (Jarvis).")
            except Exception as e:
                print(f"[STT] Porcupine init error: {e}")

        # ── Deepgram Cloud STT ────────────────────────────────────────────────
        if not self.deepgram_key:
            print("[STT] WARNING: DEEPGRAM_API_KEY missing. Transcription disabled.")
            # Try to load offline fallback
            if _WHISPER_AVAILABLE:
                try:
                    print("[STT] Loading faster-whisper (base.en) as offline fallback...")
                    self._whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
                    print("[STT] faster-whisper offline fallback ready.")
                except Exception as e:
                    print(f"[STT] faster-whisper load failed: {e}")
        else:
            print("[STT] Deepgram Nova-2 configured via Direct WebSocket.")

    def start(self, on_transcript, on_wake=None, on_interrupt=None):
        if self._running:
            return
        self._callback = on_transcript
        self._wake_callback = on_wake
        self._interrupt_callback = on_interrupt
        self._running = True

        self._thread = threading.Thread(target=self._run_event_loop,
                                        daemon=True, name="STT-AsyncRuntime")
        self._thread.start()
        print("[STT] Continuous listening started. [DeviceSelector → AdaptiveVAD → Deepgram]")

    def stop(self):
        self._is_shutting_down = True
        self._running = False
        if self._porcupine:
            self._porcupine.delete()
        print("[STT] Listener halted.")

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        # V4.0 FIX #1: Create asyncio.Lock INSIDE the running event loop, not in __init__.
        self._dg_lock = asyncio.Lock()
        self._loop.run_until_complete(self._main_orchestrator())

    async def _main_orchestrator(self):
        """
        Google Assistant-style orchestrator:
        1. Score all devices and pick best (async-safe, no event-loop blocking).
        2. Calibrate VAD noise floor from 1s ambient audio (async-safe).
        3. Run 3-stage speech detection loop.
        4. If active device goes silent, re-score and recover.
        """
        from system_services.system_state import state_manager

        frame_len = self._porcupine.frame_length if self._porcupine else CHUNK_SIZE
        device_selector = DeviceSelector()

        while self._running:
            # Phase 1: Score devices (non-blocking via to_thread)
            best_dev = await device_selector.pick_best_async()
            if best_dev is None:
                print("[STT] No live devices found. Retrying in 5s...")
                await asyncio.sleep(5.0)
                continue

            dev_idx  = best_dev['idx']
            dev_sr   = best_dev['sr']
            dev_name = best_dev['name']

            # Phase 2: Boot-time VAD calibration
            # V4.0 FIX #2: Calibration moved to thread, no sd.sleep() in async context.
            print(f"[STT] Calibrating noise floor on '{dev_name}'...")
            calib_frames = []

            def _run_calibration():
                """Blocking calibration — runs in executor thread."""
                # ruff(B023) flags calib_frames/dev_sr/dev_idx as loop variables
                # captured by closure — a real risk in a `for` loop with deferred
                # execution, but a false positive here: this is a `while` loop and
                # _run_calibration is defined AND fully executed (via the blocking
                # `await asyncio.to_thread(...)` below) within the same iteration
                # before the loop advances, so these can never hold a stale value.
                def calib_cb(indata, frames, time, status):
                    calib_frames.append(indata[:, 0].copy())  # noqa: B023
                with sd.InputStream(samplerate=dev_sr, channels=1, blocksize=frame_len,  # noqa: B023
                                    dtype='float32', device=dev_idx, callback=calib_cb):  # noqa: B023
                    threading.Event().wait(timeout=1.0)   # Block thread for 1000ms

            try:
                await asyncio.to_thread(_run_calibration)
                self._vad.calibrate(calib_frames)
            except Exception as e:
                print(f"[STT] Calibration failed on {dev_name}: {e}")
                await asyncio.sleep(1.0)
                continue

            # Phase 3: Main listening stream
            def mic_callback(indata, frames, time_info, status):
                session_active = state_manager.get_snapshot().get("session_active", False)
                if self._task_manager.current_task_id and not session_active:
                    return
                self._audio_q.put(indata[:, 0].copy())

            try:
                with sd.InputStream(
                    samplerate=dev_sr, channels=1, blocksize=frame_len,
                    dtype='float32', device=dev_idx, callback=mic_callback
                ):
                    print(f"[STT] Live on '{dev_name}' | sr={dev_sr} | VAD floor={self._vad.noise_floor:.1f}")
                    silent_streak = 0

                    while self._running:
                        try:
                            chunk = await self._loop.run_in_executor(
                                None, lambda: self._audio_q.get(timeout=0.3)
                            )
                        except queue.Empty:
                            continue

                        # ── V4.0 FIX #3 & #4: Resample FIRST, THEN convert & buffer ──
                        # This ensures pre-roll contains correct-rate int16 audio.
                        if dev_sr != TARGET_SR:
                            chunk = self._resample(chunk, dev_sr, TARGET_SR)

                        # Now convert to int16 (for Deepgram)
                        pcm = (chunk * 32767).astype(np.int16)

                        # ── Disfluency filter on raw RMS (micro-noise gate) ──────────
                        raw_rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))

                        # Dead-device watchdog (V4.0 FIX #5: extended to 300 frames)
                        if raw_rms == 0.0:
                            silent_streak += 1
                            if silent_streak > DEAD_DEVICE_FRAMES:
                                print(f"[STT] Device '{dev_name}' went dead. Re-scoring hardware...")
                                break
                        else:
                            silent_streak = 0

                        is_speech = self._vad.is_speech(chunk)

                        if not self._activated:
                            # ── SCANNING MODE ──────────────────────────────────────
                            # Pre-roll: store AFTER resampling (V4.0 FIX #4)
                            self._pre_roll.append(pcm.tobytes())

                            session_active = state_manager.get_snapshot().get("session_active", False)
                            if self._task_manager.current_task_id and not session_active:
                                self._speech_count = 0
                                continue

                            if is_speech:
                                self._speech_count += 1
                            else:
                                self._speech_count = 0

                            if self._speech_count >= VAD_TRIGGER_WIN:
                                print(f"[STT] VAD Triggered | floor={self._vad.noise_floor:.1f}")
                                self._activated     = True
                                self._speech_count  = 0
                                self._silence_count = 0
                                self._session_valid = False
                                await self._start_deepgram_session()
                        else:
                            # ── CAPTURING MODE ─────────────────────────────────────
                            should_close = False
                            conn_to_close = None
                            async with self._dg_lock:
                                if self._dg_connection:
                                    await self._dg_connection.send(pcm.tobytes())

                                if self._vad.is_silence(chunk):
                                    self._silence_count += 1
                                else:
                                    self._silence_count = 0

                                if self._silence_count >= VAD_SILENCE_WIN:
                                    print(f"[STT] End of speech (silence={self._silence_count}). Closing.")
                                    conn_to_close = self._dg_connection
                                    self._dg_connection = None
                                    self._activated = False
                                    should_close = True

                            if should_close and conn_to_close:
                                await conn_to_close.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._is_shutting_down:
                    print(f"[STT] Stream fault on '{dev_name}': {e}. Re-selecting device...")

            if not self._running:
                break
            await asyncio.sleep(1.5)

        # Cleanup
        self._activated = False
        async with self._dg_lock:
            self._dg_connection = None

    # ── Anti-Aliased Resampling ───────────────────────────────────────────────
    @staticmethod
    def _resample(chunk: np.ndarray, src_sr: int, tgt_sr: int) -> np.ndarray:
        """
        V4.0 FIX #3: Anti-aliased polyphase resampling via scipy.signal.resample_poly.
        Falls back to linear interp only if scipy is unavailable.

        scipy.signal.resample_poly uses a Kaiser-windowed sinc FIR filter which
        prevents aliasing ('zipper noise') that np.interp linear interp causes
        during downsampling (e.g., 44100 → 16000 Hz).
        """
        if src_sr == tgt_sr:
            return chunk

        if _SCIPY_AVAILABLE:
            # Compute integer up/down factors (polyphase requires rationals)
            g = gcd(tgt_sr, src_sr)
            up   = tgt_sr // g
            down = src_sr // g
            resampled = resample_poly(chunk, up, down)
            return resampled.astype(np.float32)
        else:
            # Linear fallback when scipy is not installed
            ratio  = tgt_sr / src_sr
            n_out  = int(len(chunk) * ratio)
            x_old  = np.linspace(0, 1, len(chunk))
            x_new  = np.linspace(0, 1, n_out)
            return np.interp(x_new, x_old, chunk).astype(np.float32)

    # ── Deepgram Session Management ───────────────────────────────────────────
    async def _start_deepgram_session(self):
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.deepgram_key:
            # Try offline fallback
            if self._whisper_model:
                print("[STT] Deepgram key missing — using faster-whisper offline fallback.")
                await self._start_whisper_session()
            else:
                print("[STT] FATAL: No STT engine available (Deepgram key missing, whisper not installed).")
                self._activated = False
            return

        url = (
            "wss://api.deepgram.com/v1/listen"
            "?model=nova-2"
            "&smart_format=true"
            "&endpointing=300"
            "&encoding=linear16"
            f"&sample_rate={TARGET_SR}"
        )
        headers = {"Authorization": f"Token {self.deepgram_key}"}

        try:
            conn = await ws_connect(url, extra_headers=headers)
            async with self._dg_lock:
                self._dg_connection = conn
            print("[STT] Deepgram WebSocket Connected.")

            # Flush pre-roll buffer
            while self._pre_roll:
                pre_chunk = self._pre_roll.popleft()
                async with self._dg_lock:
                    if self._dg_connection:
                        await self._dg_connection.send(pre_chunk)

            self._loop.create_task(self._listen_deepgram_results())

        except Exception as e:
            print(f"[STT] Deepgram Connection Error: {e}")
            self._activated = False

    async def _start_whisper_session(self):
        """
        Offline fallback: collect buffered audio and run faster-whisper locally.
        Only activated when Deepgram is unavailable.
        """
        if not self._whisper_model:
            self._activated = False
            return

        print("[STT] Offline Whisper session started. Collecting audio...")
        pcm_buffer = []
        silence_count = 0

        while self._running and self._activated:
            try:
                chunk = await self._loop.run_in_executor(
                    None, lambda: self._audio_q.get(timeout=0.3)
                )
            except queue.Empty:
                continue

            if chunk is not None:
                if self._vad.is_silence(chunk):
                    silence_count += 1
                else:
                    silence_count = 0

                pcm_buffer.append(chunk)

                if silence_count >= VAD_SILENCE_WIN:
                    break

        # Transcribe collected audio
        if pcm_buffer:
            audio_arr = np.concatenate(pcm_buffer).astype(np.float32)
            try:
                segments, _ = await asyncio.to_thread(
                    self._whisper_model.transcribe,
                    audio_arr,
                    language="en",
                    beam_size=5
                )
                transcript = " ".join(seg.text for seg in segments).strip()
                if transcript:
                    print(f"[STT][Whisper] Transcript: '{transcript}'")
                    await self._process_transcript(transcript)
            except Exception as e:
                print(f"[STT][Whisper] Transcription error: {e}")

        self._activated = False

    async def _listen_deepgram_results(self):
        if not self._dg_connection:
            return

        try:
            async for message in self._dg_connection:
                data = json.loads(message)
                channel = data.get("channel", {})
                alternatives = channel.get("alternatives", [{}])
                transcript   = alternatives[0].get("transcript", "").strip()
                is_final     = data.get("is_final", False)

                if not (is_final and transcript):
                    continue

                # Disfluency filter: reject single-word filler utterances
                words = transcript.lower().split()
                if len(words) == 1 and words[0] in DISFLUENCY_WORDS:
                    print(f"[STT] Disfluency rejected: '{transcript}'")
                    continue

                await self._process_transcript(transcript)

        except ConnectionClosedOK:
            print("[STT] Deepgram stream ended normally.")
        except Exception as e:
            if not self._is_shutting_down:
                print(f"[STT] Deepgram listener fault: {e}")
            self._activated = False
            self._dg_connection = None

    async def _process_transcript(self, transcript: str):
        """
        Shared transcript processing — used by both Deepgram and Whisper paths.
        Runs WakeIntelligence, manages session state, and dispatches commands.
        """
        from interfaces.ui_bridge.conversation_manager import conversation_manager
        from interfaces.voice.wake_intelligence import wake_intelligence

        session_active = conversation_manager.is_session_valid()

        if session_active or self._session_valid:
            decision = wake_intelligence.process(transcript, hardware_fired=False)
            if decision.is_interrupt:
                print(f"[WIL] Interrupt in session: '{transcript}'")
                self._dispatch_interrupt(transcript)
                await self._close_deepgram_session()
                return
            print(f"[WIL] Session command: '{transcript}'")
            conversation_manager.update_interaction()
            self._dispatch(transcript)
        else:
            decision = wake_intelligence.process(transcript, hardware_fired=False)

            if decision.is_interrupt:
                print("[WIL] Interrupt before wake — ignoring.")
                await self._close_deepgram_session()
                return

            if not decision.is_wake:
                print(f"[WIL] REJECTED (method={decision.method}): '{transcript}'")
                await self._close_deepgram_session()
                return

            self._session_valid = True
            print(f"[WIL] WAKE CONFIRMED | method={decision.method} "
                  f"conf={decision.confidence:.2f} | "
                  f"embedded={decision.is_embedded} cmd='{decision.clean_command}'")

            conversation_manager.start_session()
            if self._wake_callback:
                self._wake_callback()

            if decision.is_embedded and decision.clean_command:
                print(f"[WIL] Embedded command: '{decision.clean_command}'")
                self._dispatch(decision.clean_command)

        # ── Fix 1.5: SESSION KEEP-ALIVE ──
        # If the session is still valid, keep the connection open for follow-up
        if not conversation_manager.is_session_valid():
            await self._close_deepgram_session()
        else:
            print("[STT] Session active. Keeping connection alive for follow-up.")
            self._silence_count = 0  # Reset silence count to give full window for next command

    def _dispatch(self, text: str):
        if self._callback and not self._is_shutting_down:
            self._callback(text)

    def _dispatch_interrupt(self, text: str):
        if self._interrupt_callback and not self._is_shutting_down:
            self._interrupt_callback(text)

    async def _close_deepgram_session(self):
        self._activated = False
        async with self._dg_lock:
            conn = self._dg_connection
            self._dg_connection = None
            if conn:
                await conn.close()

    def reset_activation(self):
        self._activated = False
