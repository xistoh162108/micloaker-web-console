# UI/UX Specification

## 1. Design goal

The UI should feel like a practical lab instrument: simple enough to use quickly, but flexible enough for real experiments. Avoid clutter by using Simple/Advanced sections.

## 2. Main navigation

```text
Dashboard | Sessions | New Run | Compare | Live Monitor | Mac Helper | Files | Logs/Debug
```

## 3. Dashboard

Cards:

- Current workspace
- Active session
- DAQ status
- Mac Helper status
- Last run
- Last comparison result
- Export shortcuts

Show warnings clearly:

```text
Mac Helper disconnected — Linux-only recording and analysis are available.
DAQ unavailable — mock mode and file upload are available.
```

## 4. Sessions page

- Create session.
- List sessions.
- Open session.
- Export session ZIP.
- Export multi-session ZIP.

Session table columns:

```text
session_id | date | description | runs | analyzed | comparisons | export
```

## 5. New Run page

### Simple section

- session
- frequency: 25, 32.8, custom
- condition: `uj0` / `uj1`
- sound condition: no sound, jamming, speech, custom
- duration
- sample rate
- scale mode: peak/range/both
- notes
- record button

### Advanced section

- DAQ channel/range/input mode
- mic ID
- room
- distance/angle
- trim start/end
- analysis band
- safety metadata
- Mac Helper playback settings

## 6. Run detail page

Show:

- metadata summary
- file links
- audio player for peak/range WAVs
- final waveform plot
- final PSD plot
- final spectrogram
- final metrics table
- quality flags
- logs
- download run ZIP

Labels:

```text
Peak WAV: listening preview only.
Range WAV: scale-valid cross-check if full-scale voltage is correct.
BIN: primary quantitative data.
```

## 7. Compare page

- Select session.
- Select `uj0` run.
- Select `uj1` run.
- Select source: bin primary, range wav cross-check, peak wav disabled/warned.
- Select band: 300–3400 Hz, 20–3900 Hz, custom.
- Compare button.

Output:

- attenuation dB
- remaining fraction
- reduction percent
- PSD overlay
- attenuation bar chart
- warnings for metadata mismatch
- download compare CSV/JSON/plots

## 8. Live Monitor page

Recording state:

```text
Stopped / Previewing / Recording / Finalizing / Finalized
```

Panels:

- live waveform
- RMS/peak meter
- clipping warning
- live PSD
- scrolling spectrogram
- finalization status

Always show:

```text
Live preview is approximate. Final report values are recomputed from saved .bin.
```

## 9. Mac Helper panel

Sections:

### Connection

- Auto discover via Tailscale (optional/best-effort)
- Helper URL manual input
- Connect / Health Check
- Connection status

### Playback setup

- Refresh devices
- Output device dropdown
- Refresh files
- WAV file dropdown
- sample rate selector: 48000 / 96000 / 192000 / custom
- channels selector
- gain slider
- delay ms
- Validate Playback
- Play
- Stop

### Play & Record

- Validate first
- Start Mac playback and Linux recording with configured delay
- Store playback metadata

Disconnected state:

```text
Mac Helper disconnected. Manual Linux-only recording and analysis remain available.
```

## 10. Logs/Debug

- App logs
- Job logs
- Run logs
- Mac Helper client logs
- Traceback viewer
- Copy-to-clipboard button

## 11. Visual style

Use lightweight CSS:

- clean cards
- subtle borders
- readable tables
- status badges
- warning badges
- responsive layout
- no frontend build step

Plots should be report-friendly:

- clear titles
- axis labels with units
- grid lines
- readable fonts
- PNG and SVG output
- no over-styled scientific plots
