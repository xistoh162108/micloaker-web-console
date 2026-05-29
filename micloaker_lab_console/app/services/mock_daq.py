from __future__ import annotations

import numpy as np


def generate_mock_voltage(sample_rate_hz: int, duration_s: float, uj: str = "uj0", carrier_freq_khz: float = 25.0) -> np.ndarray:
    """Return deterministic float64 voltage data for tests and DAQ-free operation."""
    n = int(round(sample_rate_hz * duration_s))
    t = np.arange(n, dtype=np.float64) / float(sample_rate_hz)
    base_freq = 1000.0 + (carrier_freq_khz % 10.0) * 10.0
    amplitude = 0.20 if uj == "uj0" else 0.07
    signal = amplitude * np.sin(2.0 * np.pi * base_freq * t)
    signal += 0.03 * np.sin(2.0 * np.pi * 440.0 * t)
    signal += 0.002 * np.random.default_rng(12345).standard_normal(n)
    return signal.astype("<f8", copy=False)

