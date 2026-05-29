# Analysis Specification

## 1. Target signal

The analysis target is not the ultrasonic carrier itself. It is the low-frequency audible jamming-induced noise recorded by the microphone/DAQ due to microphone non-linearity and sideband interactions.

## 2. Primary metric

For baseline or ultrasonic-jamming recordings, compare `uj0` and `uj1` band power:

```text
A_dB = 10 log10(P_uj0 / P_uj1)
```

where `P` is the integrated Welch PSD power over the selected audible band.

Ordinary sound metadata is independent from the jamming carrier. `sound_condition` can represent quiet baseline, meeting-room sound, speech, or WER material. `carrier_freq_khz = 0` means no ultrasonic jamming signal was emitted.

Default primary band:

```text
300–3400 Hz
```

Wide band:

```text
20–3900 Hz for fs=8000 Hz
```

Dominant tone band:

```text
dominant_freq ± 50 Hz
```

## 3. Data source priority

1. Saved `.bin` float64 voltage data: primary.
2. Range WAV with known full-scale voltage: cross-check.
3. Peak WAV: listening and spectral-shape preview only.

## 4. Processing pipeline

For each file:

1. load signal
2. convert to mono if needed
3. remove DC if enabled
4. trim start/end transient windows
5. compute total RMS
6. compute Welch PSD
7. integrate band power
8. detect dominant frequency in analysis band
9. compute dominant-tone power
10. detect clipping/zero-signal/DC/sample-count flags
11. save metrics and plots

## 5. Quality flags

- `clipping_possible`
- `dc_offset_large`
- `zero_or_near_zero_signal`
- `sample_count_mismatch`
- `too_short_after_trim`
- `metadata_mismatch`
- `peak_wav_used_for_quantitative_analysis_warning`

## 6. Compare output

```json
{
  "source": "bin",
  "band_hz": [300, 3400],
  "uj0_power": 1.0e-4,
  "uj1_power": 1.0e-5,
  "attenuation_db": 10.0,
  "remaining_fraction": 0.1,
  "reduction_percent": 90.0,
  "warnings": []
}
```

## 7. Plots

Generate clean plots:

- waveform with time axis
- PSD with band highlight
- spectrogram
- uj0/uj1 PSD overlay
- attenuation bar chart

Use readable labels and units. Save PNG and SVG.
