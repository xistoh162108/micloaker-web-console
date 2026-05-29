# Legacy Notebook Alignment

The notebooks in `docs/legacy/` are historical workflow references. They are not executable acceptance tests because they include local paths, exploratory cells, captured outputs, and hardware assumptions. The current app should preserve their experiment intent through tested services, text artifacts, and operator workflows.

## Reference Map

| Notebook | Historical role | Current app replacement |
|---|---|---|
| `bin_to_wav.ipynb` | DAQ/raw data conversion into playable WAV files. | `app/services/converter.py` converts saved float64 `.bin` files to mode-tagged peak and range WAVs. Peak WAV is listening preview only; range WAV is cross-check only when full-scale voltage is known. |
| `daq_deploy.ipynb` | DAQ capture experiments and spectrogram checks. | `app/services/daq.py`, `app/services/recorder.py`, and mock fallback handle real or mock recording, one recording job at a time, lazy `uldaq`, logs, and finalization from saved `.bin`. |
| `plot_maker.ipynb` | Audio loading and spectrogram/plot exploration. | `app/services/plotting.py` generates report-friendly waveform, PSD, spectrogram, PSD overlay, and attenuation plots as PNG/SVG artifacts. |
| `SJR_plot_maker.ipynb` | Jamming-condition plot exploration. | Compare workflow computes `uj0`/`uj1` attenuation and saves comparison JSON/CSV plus PSD overlay and attenuation bar plots. |
| `volume_measurer.ipynb` | RMS/volume measurement exploration. | `app/services/analyzer.py` computes RMS, band power, Welch PSD, dominant tone, clipping/DC/sample-count flags, and report-grade metrics from saved `.bin`. |
| `jtest.ipynb` | Exploratory speech/jamming/audio experiments. | Treated as historical context only. No direct runtime behavior is inferred unless it is also specified in PRD/requirements/analysis docs. |

## Rules Carried Forward

- Raw `.bin` voltage data is the quantitative source of truth.
- WAV files are derived artifacts. Peak-normalized WAV is for listening only.
- Plots must be clear enough for reports and saved as durable files, not only displayed in a notebook.
- DAQ-related code must degrade to mock mode when hardware or `uldaq` is unavailable.
- Exact numeric parity with a notebook is not assumed until a known legacy `.bin` fixture and notebook output are provided.

## Verification Status

Automated tests and `scripts/acceptance_audit.py` verify the current replacements in mock mode. Physical DAQ capture, physical Mac playback, and optional exact parity against historical notebook outputs remain lab-validation items.
