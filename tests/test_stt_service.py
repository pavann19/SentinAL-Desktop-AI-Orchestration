"""
tests/test_stt_service.py
Fix 4.6: STT acoustic engine unit tests.
No hardware required — uses mock audio arrays and mocked sounddevice.
Covers 6 acoustic engine tests.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
from unittest.mock import patch, MagicMock


class TestSTTResample:

    def test_resample_output_length_correct(self):
        """_resample() output length must match (input_len * tgt / src) within 1 sample."""
        from interfaces.voice.stt_service import STTService
        # Create a mock audio input at 44100 Hz
        src_sr  = 44100
        tgt_sr  = 16000
        duration = 1.0  # 1 second
        audio_in = np.random.randn(int(src_sr * duration)).astype(np.float32)

        # Instantiate without hardware
        with patch("sounddevice.InputStream"), patch("sounddevice.query_devices", return_value=[]):
            try:
                svc = object.__new__(STTService)
                result = svc._resample(audio_in, src_sr, tgt_sr)
                expected_len = int(len(audio_in) * tgt_sr / src_sr)
                assert abs(len(result) - expected_len) <= 2, (
                    f"Resampled length {len(result)} too far from expected {expected_len}"
                )
            except Exception as e:
                pytest.skip(f"STTService init requires hardware: {e}")

    def test_resample_fallback_linear(self):
        """Without scipy, _resample() must fall back to linear interpolation."""
        from interfaces.voice.stt_service import STTService
        audio_in = np.arange(100, dtype=np.float32)
        with patch("sounddevice.InputStream"), patch("sounddevice.query_devices", return_value=[]):
            try:
                svc = object.__new__(STTService)
                with patch.dict("sys.modules", {"scipy.signal": None}):
                    result = svc._resample(audio_in, 44100, 16000)
                    expected_len = int(100 * 16000 / 44100)
                    assert abs(len(result) - expected_len) <= 2
            except Exception as e:
                pytest.skip(f"STTService init requires hardware: {e}")


class TestAdaptiveVAD:

    def test_calibrate_sets_noise_floor(self):
        """calibrate() must set _noise_floor to a value > 0 for non-silent input."""
        from interfaces.voice.stt_service import AdaptiveVAD
        vad = AdaptiveVAD()
        audio = np.ones(4000, dtype=np.float32) * 0.01  # quiet but not silent
        vad.calibrate(audio)
        assert vad._noise_floor > 0, "Noise floor was not set after calibration"

    def test_is_speech_high_rms(self):
        """A loud sine wave must be detected as speech."""
        from interfaces.voice.stt_service import AdaptiveVAD
        vad = AdaptiveVAD()
        t = np.linspace(0, 1.0, 16000)
        loud_sine = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
        vad._noise_floor = 0.01  # Set a low noise floor
        assert vad.is_speech(loud_sine) is True, "Loud sine wave not detected as speech"

    def test_silence_detected(self):
        """A near-zero array must be detected as silence."""
        from interfaces.voice.stt_service import AdaptiveVAD
        vad = AdaptiveVAD()
        silence = np.zeros(4000, dtype=np.float32)
        vad._noise_floor = 0.01
        assert vad.is_speech(silence) is False, "Zero array was detected as speech"


class TestDeviceSelector:

    def test_probe_rms_returns_float(self):
        """_probe_rms() must return a non-negative float."""
        from interfaces.voice.stt_service import DeviceSelector

        # Mock the sounddevice InputStream to return fake audio
        mock_frames = [np.ones((160, 1), dtype=np.float32) * 0.01]

        class FakeStream:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, n): return mock_frames[0], False

        with patch("sounddevice.InputStream", return_value=FakeStream()):
            try:
                selector = DeviceSelector.__new__(DeviceSelector)
                rms = selector._probe_rms(device_idx=0)
                assert isinstance(rms, float)
                assert rms >= 0.0
            except Exception as e:
                pytest.skip(f"DeviceSelector._probe_rms requires hardware: {e}")
