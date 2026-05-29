from __future__ import annotations

import importlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from .raw_bin import read_raw_float64_bin

plt.rcParams.update(
    {
        "path.simplify": True,
        "path.simplify_threshold": 0.8,
        "agg.path.chunksize": 10000,
        "svg.fonttype": "none",
    }
)

MAX_WAVEFORM_PLOT_POINTS = 12000
MAX_PSD_PLOT_BINS = 2048


def plot_run(
    bin_path: Path,
    sample_rate_hz: float,
    plots_dir: Path,
    run_id: str,
    *,
    band_hz: tuple[float, float] = (300.0, 3400.0),
    remove_dc: bool = True,
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
    overwrite: bool = False,
) -> dict[str, str]:
    data = read_raw_float64_bin(bin_path)
    data = _trim_for_plot(data, sample_rate_hz, trim_start_s, trim_end_s)
    plots_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "waveform_png": plots_dir / f"{run_id}_waveform.png",
        "waveform_svg": plots_dir / f"{run_id}_waveform.svg",
        "psd_png": plots_dir / f"{run_id}_psd.png",
        "psd_svg": plots_dir / f"{run_id}_psd.svg",
        "spectrogram_png": plots_dir / f"{run_id}_spectrogram.png",
        "spectrogram_svg": plots_dir / f"{run_id}_spectrogram.svg",
    }
    existing = [path for path in paths.values() if path.exists()]
    if existing and not overwrite:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(f"refusing to overwrite existing plots without explicit overwrite: {names}")
    _waveform(data, sample_rate_hz, paths["waveform_png"], paths["waveform_svg"])
    _psd(data, sample_rate_hz, paths["psd_png"], paths["psd_svg"], band_hz, remove_dc=remove_dc)
    _spectrogram(data, sample_rate_hz, paths["spectrogram_png"], paths["spectrogram_svg"], remove_dc=remove_dc)
    return {k: str(v.parent.name + "/" + v.name) for k, v in paths.items()}


def _trim_for_plot(data: np.ndarray, fs: float, trim_start_s: float, trim_end_s: float) -> np.ndarray:
    start = max(0, int(round(float(trim_start_s) * float(fs))))
    end_trim = max(0, int(round(float(trim_end_s) * float(fs))))
    end = data.size - end_trim if end_trim else data.size
    if start >= end:
        return data
    return data[start:end]


def plot_compare(result: dict, out_dir: Path, compare_id: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bar = out_dir / f"{compare_id}_attenuation.png"
    bar_svg = out_dir / f"{compare_id}_attenuation.svg"
    uj0_pct = float(result.get("uj0_relative_energy_percent", 100.0))
    uj1_pct = float(result.get("uj1_relative_energy_percent", float(result.get("remaining_fraction", 0.0)) * 100.0))
    reduction = float(result.get("reduction_percent", 0.0))
    attenuation = float(result.get("attenuation_db", 0.0))
    fig, ax = plt.subplots(figsize=(5.8, 3.4), constrained_layout=True)
    bars = ax.bar(["UJ0 reference", "UJ1 measured"], [uj0_pct, uj1_pct], color=["#2f5f93", "#0a8793"])
    ax.set_ylabel("Relative band energy (%)")
    ax.set_ylim(0, max(110.0, uj0_pct * 1.12, uj1_pct * 1.12))
    ax.set_title(f"UJ1 remaining energy {uj1_pct:.1f}% ({reduction:.1f}% reduction, {attenuation:.2f} dB)")
    ax.grid(axis="y", alpha=0.25)
    for rect, value in zip(bars, [uj0_pct, uj1_pct]):
        ax.text(rect.get_x() + rect.get_width() / 2.0, rect.get_height(), f"{value:.1f}%", ha="center", va="bottom", fontsize=9)
    fig.savefig(bar, dpi=160)
    fig.savefig(bar_svg)
    plt.close(fig)
    return {"attenuation_png": str(bar.relative_to(out_dir.parent)), "attenuation_svg": str(bar_svg.relative_to(out_dir.parent))}


def plot_psd_overlay(
    metrics0: dict,
    metrics1: dict,
    out_dir: Path,
    compare_id: str,
    *,
    band_hz: tuple[float, float] = (300.0, 3400.0),
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{compare_id}_psd_overlay.png"
    svg = out_dir / f"{compare_id}_psd_overlay.svg"
    f0 = np.asarray(metrics0.get("psd_freq_hz", []), dtype=float)
    p0 = np.asarray(metrics0.get("psd_v2_per_hz", []), dtype=float)
    f1 = np.asarray(metrics1.get("psd_freq_hz", []), dtype=float)
    p1 = np.asarray(metrics1.get("psd_v2_per_hz", []), dtype=float)
    fig, ax = plt.subplots(figsize=(8, 3), constrained_layout=True)
    if f0.size and p0.size:
        ax.semilogy(f0, p0, label="uj0", color="#2f5f93", linewidth=1.0)
    if f1.size and p1.size:
        ax.semilogy(f1, p1, label="uj1", color="#a52828", linewidth=1.0)
    _highlight_band(ax, band_hz, label=_band_label(band_hz))
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD (V^2/Hz)")
    ax.set_title("Comparison PSD Overlay")
    ax.grid(alpha=0.25)
    ax.legend(loc="best")
    fig.savefig(png, dpi=160)
    fig.savefig(svg)
    plt.close(fig)
    return {"psd_overlay_png": str(png.relative_to(out_dir.parent)), "psd_overlay_svg": str(svg.relative_to(out_dir.parent))}


def _waveform(data: np.ndarray, fs: float, png: Path, svg: Path) -> None:
    t, data = _waveform_plot_series(data, fs, MAX_WAVEFORM_PLOT_POINTS)
    fig, ax = plt.subplots(figsize=(8, 3), constrained_layout=True)
    ax.plot(t, data, linewidth=0.8, color="#0a8793")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Voltage (V)")
    ax.set_title("Waveform")
    ax.grid(alpha=0.25)
    fig.savefig(png, dpi=160)
    fig.savefig(svg)
    plt.close(fig)


def _psd(data: np.ndarray, fs: float, png: Path, svg: Path, band_hz: tuple[float, float], *, remove_dc: bool) -> None:
    x = data - np.mean(data) if remove_dc and data.size else data
    nperseg = min(4096, max(256, x.size // 4)) if x.size >= 256 else max(8, x.size)
    freqs, psd = _welch_psd(x, fs, nperseg=nperseg, detrend=False) if x.size else (np.array([]), np.array([]))
    freqs, psd = _thin_xy(freqs, psd, MAX_PSD_PLOT_BINS)
    fig, ax = plt.subplots(figsize=(8, 3), constrained_layout=True)
    if freqs.size:
        ax.semilogy(freqs, psd, color="#2f5f93", linewidth=1.0)
        _highlight_band(ax, band_hz, nyquist=fs / 2)
        ax.legend(loc="best")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD (V^2/Hz)")
    ax.set_title("Welch PSD")
    ax.grid(alpha=0.25)
    fig.savefig(png, dpi=160)
    fig.savefig(svg)
    plt.close(fig)


def _highlight_band(ax, band_hz: tuple[float, float], *, nyquist: float | None = None, label: str | None = None) -> None:
    lo, hi = float(band_hz[0]), float(band_hz[1])
    if nyquist is not None:
        hi = min(hi, float(nyquist))
    if hi <= lo:
        return
    ax.axvspan(lo, hi, color="#b9842c", alpha=0.18, label=label or _band_label((lo, hi)))


def _band_label(band_hz: tuple[float, float]) -> str:
    return f"{float(band_hz[0]):g}-{float(band_hz[1]):g} Hz"


def _spectrogram(data: np.ndarray, fs: float, png: Path, svg: Path, *, remove_dc: bool) -> None:
    fig, ax = plt.subplots(figsize=(8, 3), constrained_layout=True)
    if data.size:
        if remove_dc:
            data = data - np.mean(data)
        nperseg = min(512, max(64, data.size // 8))
        _, _, _, image = ax.specgram(data, NFFT=nperseg, Fs=fs, noverlap=nperseg // 2, cmap="viridis")
        image.set_rasterized(True)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_title("Spectrogram")
    fig.savefig(png, dpi=160)
    fig.savefig(svg)
    plt.close(fig)


def _welch_psd(x: np.ndarray, sample_rate_hz: float, *, nperseg: int, detrend: bool | str) -> tuple[np.ndarray, np.ndarray]:
    try:
        signal = importlib.import_module("scipy.signal")
    except ImportError as exc:
        raise RuntimeError("SciPy is required for report PSD plots. Metrics may still be available in the run results.") from exc
    return signal.welch(x, fs=sample_rate_hz, nperseg=nperseg, detrend=detrend)


def _waveform_plot_series(data: np.ndarray, fs: float, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    """Preserve local extrema while limiting report plot point count."""
    if data.size <= max_points or max_points < 4:
        return np.arange(data.size) / float(fs), data
    bucket_count = max(1, max_points // 2)
    bucket_size = int(np.ceil(data.size / bucket_count))
    trimmed_size = (data.size // bucket_size) * bucket_size
    if trimmed_size < bucket_size:
        stride = max(1, data.size // max_points)
        idx = np.arange(0, data.size, stride)
        return idx / float(fs), data[idx]
    core = data[:trimmed_size].reshape(-1, bucket_size)
    mins = core.min(axis=1)
    maxs = core.max(axis=1)
    min_pos = core.argmin(axis=1) + np.arange(core.shape[0]) * bucket_size
    max_pos = core.argmax(axis=1) + np.arange(core.shape[0]) * bucket_size
    times = np.empty(mins.size * 2, dtype=float)
    envelope = np.empty(mins.size * 2, dtype=data.dtype)
    times[0::2] = min_pos / float(fs)
    times[1::2] = max_pos / float(fs)
    envelope[0::2] = mins
    envelope[1::2] = maxs
    order = np.argsort(times, kind="stable")
    times = times[order]
    envelope = envelope[order]
    if trimmed_size < data.size:
        tail = data[trimmed_size:]
        tail_min_pos = int(tail.argmin()) + trimmed_size
        tail_max_pos = int(tail.argmax()) + trimmed_size
        tail_times = np.array([tail_min_pos, tail_max_pos], dtype=float) / float(fs)
        tail_values = np.array([tail.min(), tail.max()], dtype=data.dtype)
        tail_order = np.argsort(tail_times, kind="stable")
        times = np.concatenate([times, tail_times[tail_order]])
        envelope = np.concatenate([envelope, tail_values[tail_order]])
    return times, envelope


def _thin_xy(x: np.ndarray, y: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    if x.size <= max_points or y.size <= max_points or max_points < 2:
        return x, y
    idx = np.linspace(0, min(x.size, y.size) - 1, max_points, dtype=int)
    return x[idx], y[idx]
