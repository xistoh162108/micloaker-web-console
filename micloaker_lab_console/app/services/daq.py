from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np


class DaqUnavailableError(RuntimeError):
    pass


class DaqNotConfiguredError(RuntimeError):
    pass


def daq_available() -> bool:
    return importlib.util.find_spec("uldaq") is not None


def daq_health() -> dict:
    if daq_available():
        return {
            "ok": True,
            "available": True,
            "backend": "uldaq",
            "mode": "real",
            "message": "uldaq is installed; real DAQ recording will validate hardware when recording starts.",
        }
    return {
        "ok": True,
        "available": False,
        "backend": "mock",
        "mode": "mock",
        "message": "uldaq is unavailable; mock DAQ mode remains available.",
    }


def record_voltage(*args, **kwargs):
    """Record float64 voltage samples from the first available ULDAQ device.

    Importing uldaq stays inside this function so tests and mock mode work on
    machines without DAQ hardware or vendor libraries.

    This is intentionally a small generic USB analog-input path. Hardware with
    custom triggering, clocking, or channel layout should wrap this function or
    extend the string-to-ULDAQ mappings below without changing mock mode.
    """
    try:
        import uldaq  # type: ignore
    except Exception as exc:
        raise DaqUnavailableError("uldaq is unavailable; use mock recording or install/configure DAQ drivers.") from exc

    sample_rate_hz = int(kwargs["sample_rate_hz"])
    duration_s = float(kwargs["duration_s"])
    channels = [int(ch) for ch in kwargs.get("channels", [0])]
    if sample_rate_hz <= 0 or duration_s <= 0:
        raise DaqNotConfiguredError("DAQ sample_rate_hz and duration_s must be positive.")
    if not channels:
        raise DaqNotConfiguredError("At least one DAQ channel is required.")
    if channels != list(range(min(channels), max(channels) + 1)):
        raise DaqNotConfiguredError("ULDAQ scan requires contiguous channels for this minimal recorder.")

    descriptors = uldaq.get_daq_device_inventory(uldaq.InterfaceType.USB)
    if not descriptors:
        raise DaqUnavailableError("No ULDAQ USB devices found; use mock recording or connect/configure DAQ hardware.")

    device = uldaq.DaqDevice(descriptors[0])
    try:
        device.connect()
        ai_device = device.get_ai_device()
        input_mode = _enum_value(uldaq.AiInputMode, kwargs.get("input_mode", "SINGLE_ENDED"))
        ai_range = _enum_value(uldaq.Range, kwargs.get("ai_range", "BIP10VOLTS"))
        channel_count = len(channels)
        samples_per_channel = max(1, int(round(sample_rate_hz * duration_s)))
        data = _create_float_buffer(uldaq, channel_count, samples_per_channel)
        rate = ai_device.a_in_scan(
            min(channels),
            max(channels),
            input_mode,
            ai_range,
            samples_per_channel,
            float(sample_rate_hz),
            getattr(uldaq.ScanOption, "DEFAULTIO", 0),
            getattr(uldaq.AInScanFlag, "DEFAULT", 0),
            data,
        )
        samples = np.asarray(data, dtype=np.float64)
        if channel_count > 1:
            samples = samples.reshape((samples_per_channel, channel_count))[:, 0]
        return samples.astype("<f8", copy=False), float(rate)
    except DaqUnavailableError:
        raise
    except Exception as exc:
        raise DaqNotConfiguredError(f"ULDAQ recording failed: {exc}") from exc
    finally:
        _disconnect_device(device)


def _enum_value(enum_cls: Any, name: str) -> Any:
    try:
        return getattr(enum_cls, str(name))
    except AttributeError as exc:
        raise DaqNotConfiguredError(f"Unsupported ULDAQ option {name!r} for {enum_cls.__name__}.") from exc


def _create_float_buffer(uldaq: Any, channel_count: int, samples_per_channel: int) -> Any:
    if hasattr(uldaq, "create_float_buffer"):
        return uldaq.create_float_buffer(channel_count, samples_per_channel)
    return [0.0] * (channel_count * samples_per_channel)


def _disconnect_device(device: Any) -> None:
    try:
        if hasattr(device, "disconnect"):
            device.disconnect()
    except Exception:
        pass
    try:
        if hasattr(device, "release"):
            device.release()
    except Exception:
        pass
