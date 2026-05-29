from __future__ import annotations

from pathlib import Path

import numpy as np


class RawBinValidationError(ValueError):
    pass


def validate_raw_float64_bin(path: Path, *, source_label: str = "raw .bin", require_suffix: bool = True) -> dict:
    """Validate a saved raw voltage `.bin` before quantitative processing."""
    if require_suffix and path.suffix.lower() != ".bin":
        raise RawBinValidationError(f"{source_label} must use a .bin extension")
    if not path.is_file():
        raise FileNotFoundError(path)
    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise RawBinValidationError(f"{source_label} is empty")
    if size_bytes % 8 != 0:
        raise RawBinValidationError(f"{source_label} byte length must be divisible by 8 for float64 voltage samples")
    samples = np.fromfile(path, dtype="<f8")
    if samples.size == 0:
        raise RawBinValidationError(f"{source_label} contains no float64 samples")
    if not np.all(np.isfinite(samples)):
        raise RawBinValidationError(f"{source_label} contains NaN or infinite values")
    return {"size_bytes": int(size_bytes), "sample_count": int(samples.size), "dtype": "<f8"}


def read_raw_float64_bin(path: Path) -> np.ndarray:
    validate_raw_float64_bin(path)
    return np.fromfile(path, dtype="<f8")
