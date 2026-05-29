# UI/UX Specification

## 1. Design goal

The UI should feel like a practical lab instrument: compact, stable, and easy to operate while a physical experiment is running. The operator must be able to see the active setup, capture controls, live preview, finalization state, latest results, and export/readiness shortcuts without switching through disconnected dashboard tabs.

Detailed pages may still exist for advanced metadata, file browsing, logs, and per-run inspection. The Dashboard is the experiment command center.

## 2. Main navigation

```text
Dashboard | Sessions | New Run | Compare | Live Monitor | Mac Helper | Files | Logs/Debug | Ops
```

## 3. Dashboard Command Center

The Dashboard must be organized by operating priority:

1. Setup
2. Capture And Live Preview
3. Results, Compare, Export
4. Recent Runs and Operations

Always-visible state:

- active session
- DAQ/mock status
- Mac Helper status
- recording/finalization status
- latest run
- latest comparison
- latest finalized visual artifacts, when available
- export and operations shortcuts

Do not hide core experiment controls behind Dashboard tabs. The operator should be able to start live preview, create and record a run, watch live plots, see finalization status, and open the latest finalized artifacts from the same screen.

The command center layout must avoid fixed-width operator controls. Capture buttons, metadata fields, status badges, and plot panels must wrap cleanly without overlapping on Linux lab desktops, laptop screens, and narrow browser windows. Live waveform and finalization status are primary operator surfaces; logs are secondary diagnostic material and should not dominate the first screen.

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

The Dashboard embeds the same operator-critical live signals:

- waveform
- RMS/peak
- clipping
- live PSD
- scrolling spectrogram
- finalization status and latest finalized run links

The separate Live Monitor page is a larger inspection view, not the only place where live status is visible during operation.

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

Logs are secondary diagnostic material. The Dashboard and run detail pages should emphasize visual artifacts, experiment state, and final metrics first.

## 11. Visual style

Use lightweight CSS:

- DaisyUI component vocabulary implemented locally in vanilla CSS
- scientific instrument visual vocabulary: neutral lab surfaces, low-contrast chart chrome, restrained semantic status colors, and cyan/blue data emphasis
- clean cards
- subtle borders
- readable tables
- status badges
- warning badges
- responsive layout
- no frontend build step
- no overlapping controls at desktop, tablet, or mobile widths
- controls wrap cleanly instead of shrinking into each other

Plots should be report-friendly:

- clear titles
- axis labels with units
- grid lines
- readable fonts
- accessible, restrained scientific palettes rather than decorative dashboard gradients
- interactive live chart readouts for waveform time/voltage, PSD frequency/log power, and spectrogram row/frequency/value
- crosshair inspection on live charts without changing the saved quantitative source
- PNG and SVG output
- no over-styled scientific plots

External design references used for the scientific console direction:

- W3C WCAG contrast guidance: https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum
- NOAA CoastWatch color-choice discussion for scientific visualization: https://coastwatch.noaa.gov/cwn/news/2021-09-23/colors-and-confusion-making-better-color-choices-data-visualization.html
- NASA Ames information display principles: https://www.nas.nasa.gov/assets/nas/pdf/techreports/1994/nas-94-002.pdf
