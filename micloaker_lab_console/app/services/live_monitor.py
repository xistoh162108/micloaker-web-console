from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from typing import Any

import numpy as np

from .daq import DaqNotConfiguredError, DaqUnavailableError, record_voltage
from .mock_daq import generate_mock_voltage


def preview_contract() -> dict[str, Any]:
    """Describe live-preview cadence and provenance for UI/API consumers."""
    return {
        "preview_saved": False,
        "final_metrics_source": "saved_bin_after_recording",
        "recommended_update_rates_hz": {
            "waveform_min": 5,
            "waveform_max": 10,
            "rms_peak_min": 5,
            "rms_peak_max": 10,
            "psd_min": 2,
            "psd_max": 5,
            "spectrogram_min": 2,
            "spectrogram_max": 5,
        },
        "payload_limits": {
            "waveform_points_min": 500,
            "waveform_points_max": 1000,
            "psd_bins_min": 128,
            "psd_bins_max": 256,
            "spectrogram_rows_max": 60,
        },
        "client_poll_intervals_ms": {
            "preview": 200,
            "recording": 200,
            "idle": 1000,
        },
    }


@dataclass
class LiveMonitor:
    sample_rate_hz: int = 8000
    running: bool = False
    source: str = "mock"
    channel: int = 0
    input_mode: str = "SINGLE_ENDED"
    ai_range: str = "BIP10VOLTS"
    tick: int = 0
    spectrogram_rows: list[list[float]] = field(default_factory=list)

    def start(
        self,
        *,
        source: str = "mock",
        sample_rate_hz: int | None = None,
        channel: int = 0,
        input_mode: str = "SINGLE_ENDED",
        ai_range: str = "BIP10VOLTS",
    ) -> None:
        if source not in {"mock", "daq"}:
            raise ValueError("live preview source must be 'mock' or 'daq'")
        self.source = source
        if sample_rate_hz:
            self.sample_rate_hz = int(sample_rate_hz)
        self.channel = int(channel)
        self.input_mode = input_mode
        self.ai_range = ai_range
        self.running = True
        self.tick = 0
        self.spectrogram_rows.clear()

    def stop(self) -> None:
        self.running = False

    def snapshot(self) -> dict[str, Any]:
        if not self.running:
            return {
                "running": False,
                "preview_only": True,
                "result_grade": "preview",
                "preview_source": self.source,
                **preview_contract(),
                "sample_rate_hz": self.sample_rate_hz,
                "preview_label": "Preview only. Final metrics will be recomputed from saved .bin after recording.",
                "waveform_point_count": 0,
                "psd_bin_count": 0,
                "spectrogram_row_count": len(self.spectrogram_rows),
        }
        self.tick += 1
        data = self._sample_preview()
        if self.source == "mock" and data.size:
            data = np.roll(data, self.tick * max(1, data.size // 40))
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        rms = float(np.sqrt(np.mean(data * data))) if data.size else 0.0
        freqs, psd = _welch_psd(data, self.sample_rate_hz, nperseg=256)
        row = np.log10(psd[:128] + 1e-18).tolist()
        self.spectrogram_rows.append(row)
        self.spectrogram_rows = self.spectrogram_rows[-60:]
        waveform = data[:: max(1, data.size // 600)].tolist()
        return {
            "running": True,
            "preview_only": True,
            "result_grade": "preview",
            "preview_source": self.source,
            **preview_contract(),
            "sample_rate_hz": self.sample_rate_hz,
            "preview_tick": self.tick,
            "preview_label": "Preview only. Final metrics will be recomputed from saved .bin after recording.",
            "rms_v": rms,
            "peak_v": peak,
            "clipping": peak >= 9.8,
            "waveform": waveform,
            "psd_freq_hz": freqs[:128].tolist(),
            "psd": psd[:128].tolist(),
            "spectrogram": self.spectrogram_rows,
            "waveform_point_count": len(waveform),
            "psd_bin_count": min(128, len(psd)),
            "spectrogram_row_count": len(self.spectrogram_rows),
        }

    def _sample_preview(self) -> np.ndarray:
        if self.source == "mock":
            return generate_mock_voltage(self.sample_rate_hz, 0.25, "uj0", 25.0)
        try:
            data_result = record_voltage(
                sample_rate_hz=self.sample_rate_hz,
                duration_s=0.25,
                channels=[self.channel],
                input_mode=self.input_mode,
                ai_range=self.ai_range,
            )
        except (DaqUnavailableError, DaqNotConfiguredError) as exc:
            raise RuntimeError(f"DAQ live preview unavailable: {exc}") from exc
        data = data_result[0] if isinstance(data_result, tuple) else data_result
        return np.asarray(data, dtype=np.float64)


live_monitor = LiveMonitor()


def _welch_psd(data: np.ndarray, sample_rate_hz: float, *, nperseg: int) -> tuple[np.ndarray, np.ndarray]:
    try:
        signal = importlib.import_module("scipy.signal")
    except ImportError as exc:
        raise RuntimeError("SciPy is required for live PSD preview. Install scipy or stop Live Monitor preview.") from exc
    return signal.welch(data, fs=sample_rate_hz, nperseg=nperseg)
