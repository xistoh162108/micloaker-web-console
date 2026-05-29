# Scientific Console UI Requirements

This document records the operator UI direction requested during implementation. It is a requirements addendum for future UI work, not a claim that all items are fully implemented.

## Reference products

The console should feel closer to scientific instrument and graphing software than to a generic generated dashboard.

- OriginPro / Origin: graph layers, data cursors, vertical cursors, zoom/pan, repetitive graphing workflows, and report-grade plotting. See OriginLab's OriginPro product page and panning documentation: https://www.originlab.com/index.aspx?go=Products%2FOriginPro and https://docs.originlab.com/origin-help/pan-graphpage/.
- MATLAB plotting: interactive axes, scroll/pinch zoom, drag pan, restore view, and data tips. See MathWorks interactive plot documentation: https://www.mathworks.com/help/matlab/creating_plots/data-cursor-displaying-data-values-interactively.html.
- PASCO Capstone: live lab data displays, graph/table/digits/meters/oscilloscope/FFT views, graph pop-up tools, scale-to-fit, scroll x-axis, run selectors, highlighters, and data point annotation. See PASCO Capstone and graph display docs: https://www.pasco.com/products/software/capstone and https://help.pasco.com/software/pasco-capstone/display-and-analyze-data/graph-display.
- GeoGebra Graphing Calculator: a clean graphics view, algebra/tool side panels, axes/grid controls, and direct interactive graph manipulation. See GeoGebra Help: https://help.geogebra.org/hc/en-us/articles/8379920754717-Graphing-Calculator.

## Visual style

- Use a restrained scientific palette: white or neutral lab surfaces, dark readable text, thin grid lines, clear axis labels, and a small set of measurement accent colors.
- Avoid AI-looking decorative gradients, floating blobs, generic marketing cards, and oversized hero treatments inside the working console.
- Plot areas should resemble Matplotlib/MATLAB/Origin figures: framed axes, tick marks, units, legends, and stable aspect ratios.
- Controls should look like instrument controls: compact, aligned, predictable, and grouped by experiment step.
- Buttons and form controls must wrap without overlap at desktop and mobile widths.

## One-page experiment console

The primary dashboard must support the working flow from one screen:

1. Session and run context.
2. Jamming signal metadata and ordinary sound metadata.
3. Mac Helper connection, jamming WAV selection, playback sample rate, device, channels, gain, and delay.
4. Playback-only test, recording-only test, and synchronized Play & Record.
5. Visual playback/recording status.
6. Live waveform, RMS/peak, clipping, PSD, and scrolling spectrogram.
7. Latest `.bin`, WAV preview, plots, metrics, and finalization status.
8. Operator approval gate before downstream report-grade processing when that mode is enabled.

Core experiment controls must not be hidden behind mutually exclusive tabs during a run.

## Metadata semantics

- `carrier_freq_khz` is the jamming carrier metadata.
- `carrier_freq_khz = 0` means no jamming signal emitted.
- `sound_condition` is ordinary room sound, speech, or WER material captured by the microphone. It is not the jamming signal.
- Current jamming WAVs should be under the Mac Helper `jamming_sound` directory:
  - `jamming_sound/25khz_1hr.wav`
  - `jamming_sound/32.8khz_1hr.wav`
- Run-level Mac Helper validation/play/play-and-record must reject mismatched jamming files, such as selecting `25khz_1hr.wav` for a `32.8 kHz` run.

## Interaction requirements

- Graphs should provide at least large-view inspection, with future support for pan, zoom, axis-scale changes, tooltips/data cursors, and run selectors.
- Live charts should update quickly enough for lab feedback, using bounded payloads and efficient rendering.
- Logs should be secondary and scrollable; they must not stretch the page as the default operator view.
- JSON is useful for audit/debugging but should be hidden behind details panels unless the operator explicitly opens it.
- Audio preview controls must not overlap file tables, plot panels, or action bars.

## Report-quality outputs

- Final waveform, PSD, spectrogram, PSD overlay, and attenuation charts should be clean enough to paste into reports or papers.
- Every plot should have units, readable labels, legible ticks, consistent colors, and exportable PNG/SVG artifacts.
- Final report-grade metrics must still come from saved raw `.bin`, not peak-normalized WAV previews.
