# File Naming and Metadata

## 1. Session ID

Recommended:

```text
YYMMDD_<experiment_slug>
```

Example:

```text
260528_r25k_audible_noise
```

## 2. Run ID

Recommended:

```text
YYMMDD-HHMMSS_<freq_tag>_<uj_tag>_<sound_tag>_<mic_tag>_<trial>
```

Examples:

```text
260528-193012_r25k_uj0_sound0_micUSB1608ch0_01
260528-193245_r25k_uj1_sound0_micUSB1608ch0_01
260528-194010_r32k8_uj0_sound1_micUSB1608ch0_01
```

## 3. Frequency tags

```text
25     -> r25k
32.8   -> r32k8
0      -> r0
```

## 4. File names

```text
bin/<run_id>.bin
wav/<run_id>__scale-peak.wav
wav/<run_id>__scale-range-fs10V.wav
plots/<run_id>_waveform.png
plots/<run_id>_psd.png
plots/<run_id>_spectrogram.png
results/<run_id>_metrics.json
```

## 5. Metadata schema

Run metadata should include:

```json
{
  "run_id": "...",
  "session_id": "...",
  "created_at": "...",
  "condition": {
    "carrier_freq_khz": 25.0,
    "uj": "uj0",
    "sound_condition": "sound0",
    "mic_id": "USB1608_CH0",
    "room": "lab",
    "distance_cm": null,
    "angle_deg": 0,
    "notes": ""
  },
  "recording": {
    "source": "daq|mock|upload",
    "sample_rate_hz": 8000,
    "actual_sample_rate_hz": 8000,
    "duration_s": 10,
    "channels": [0],
    "input_mode": "SINGLE_ENDED",
    "ai_range": "BIP10VOLTS",
    "dtype": "<f8",
    "written_samples": 80000
  },
  "conversion": {
    "remove_dc": true,
    "scale_modes": ["peak", "range"],
    "full_scale_volts": 10.0
  },
  "analysis": {
    "status": "finalized",
    "source": "bin",
    "trim_start_s": 0.2,
    "trim_end_s": 0.2,
    "primary_band_hz": [300, 3400],
    "metrics_path": "results/...json"
  },
  "mac_helper": {
    "enabled": false,
    "connected": false,
    "health_ok": false,
    "last_error": "Mac Helper not configured"
  },
  "files": {
    "bin": "bin/<run_id>.bin",
    "wav_peak": "wav/<run_id>__scale-peak.wav",
    "wav_range": "wav/<run_id>__scale-range-fs10V.wav"
  },
  "quality_flags": []
}
```
