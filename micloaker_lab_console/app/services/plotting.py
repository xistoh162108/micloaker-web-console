from __future__ import annotations

import importlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from .raw_bin import read_raw_float64_bin


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
    fig, ax = plt.subplots(figsize=(5, 3), constrained_layout=True)
    ax.bar(["attenuation"], [result["attenuation_db"]], color="#2f6f73")
    ax.set_ylabel("dB")
    ax.set_title("UJ0 to UJ1 attenuation")
    ax.grid(axis="y", alpha=0.25)
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
        ax.semilogy(f0, p0, label="uj0", color="#1f4e79", linewidth=1.0)
    if f1.size and p1.size:
        ax.semilogy(f1, p1, label="uj1", color="#8f3b2d", linewidth=1.0)
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
    t = np.arange(data.size) / float(fs)
    fig, ax = plt.subplots(figsize=(8, 3), constrained_layout=True)
    ax.plot(t, data, linewidth=0.8, color="#1f4e79")
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
    fig, ax = plt.subplots(figsize=(8, 3), constrained_layout=True)
    if freqs.size:
        ax.semilogy(freqs, psd, color="#6b4e16", linewidth=1.0)
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
    ax.axvspan(lo, hi, color="#d8a03d", alpha=0.18, label=label or _band_label((lo, hi)))


def _band_label(band_hz: tuple[float, float]) -> str:
    return f"{float(band_hz[0]):g}-{float(band_hz[1]):g} Hz"


def _spectrogram(data: np.ndarray, fs: float, png: Path, svg: Path, *, remove_dc: bool) -> None:
    fig, ax = plt.subplots(figsize=(8, 3), constrained_layout=True)
    if data.size:
        if remove_dc:
            data = data - np.mean(data)
        nperseg = min(512, max(64, data.size // 8))
        ax.specgram(data, NFFT=nperseg, Fs=fs, noverlap=nperseg // 2, cmap="viridis")
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
