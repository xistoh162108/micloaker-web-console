# v0.2 Live Monitor and Finalize Workflow

## 1. Purpose

Live Monitor Mode lets the user check the incoming microphone/DAQ signal in real time. It is a setup and sanity-check tool. It is not the source of final quantitative results.

## 2. Live preview outputs

- waveform of recent time window
- RMS and peak level
- clipping warning
- live PSD estimate
- scrolling spectrogram
- status text and logs

The default live source is mock preview so the console remains usable without DAQ hardware. The UI may also expose an explicit **Start DAQ Live** control that performs short DAQ preview scans through the same lazy `uldaq` recording backend. If DAQ preview is unavailable, the live API must return a structured preview error while keeping the page and Linux-only workflow usable.

## 3. Preview-only rule

Live data may be downsampled or approximate. UI must label it:

```text
Preview only. Final metrics will be recomputed from saved .bin after recording.
```

## 4. Finalization after recording

After recording ends, automatically start a finalization job:

1. read saved `.bin`
2. remove DC if enabled
3. trim transient windows
4. compute RMS and band powers
5. compute high-resolution Welch PSD
6. detect dominant tone
7. detect clipping/DC/sample-count quality flags
8. generate waveform, PSD, spectrogram plots
9. generate peak and range WAVs if requested
10. save metrics JSON/CSV
11. update run metadata and UI

## 5. Architecture

Use one acquisition source where possible:

```text
DAQ/mock source
  ├── raw .bin writer
  ├── live preview buffer
  └── quick metric calculator
```

Avoid two competing DAQ readers during a recording. DAQ live preview is an explicit setup/sanity-check mode, not a replacement for saved `.bin` capture and finalization.

## 6. Data transfer

Use WebSocket if feasible; otherwise polling is acceptable.

Recommended update rates:

- waveform: 5–10 Hz
- RMS/peak: 5–10 Hz
- PSD: 2–5 Hz
- spectrogram: 2–5 Hz

Keep payload compact:

- waveform: downsample to 500–1000 points
- PSD: 128–256 bins
- spectrogram: send one row at a time or a compact matrix

## 7. Acceptance criteria

- Mock live monitor runs without DAQ.
- Explicit DAQ live preview can be requested and degrades cleanly when DAQ is unavailable.
- Browser updates waveform continuously.
- RMS/peak and clipping status update.
- PSD and spectrogram update.
- Recording can finish and trigger finalization.
- UI distinguishes preview from final results.
- Final metrics come from saved `.bin`.
