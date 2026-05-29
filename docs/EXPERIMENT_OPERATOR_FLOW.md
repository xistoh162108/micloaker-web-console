# Experiment Operator Flow

This document fixes the intended lab workflow for the MiCloaker console.

## Physical setup

- Ultrasonic speaker playback is controlled from the Mac.
- The measurement microphone is connected to the Linux machine.
- The Mac Helper is optional, but when connected it should control the Mac playback file, output device, sample rate, channel count, gain, and delay.
- Current jamming WAV files should live under the Mac Helper `jamming_sound` folder, for example `jamming_sound/25khz_1hr.wav` and `jamming_sound/32.8khz_1hr.wav`.
- Linux DAQ capture writes the primary raw `.bin` voltage file.

## Run metadata semantics

- `carrier_freq_khz` is the ultrasonic jamming carrier frequency.
- `carrier_freq_khz = 0` means no jamming signal is emitted.
- `uj` remains the internal compatibility field, but the UI and newly generated comparison plots should show `Unjammed: false` for `uj0` and `Unjammed: true` for `uj1`.
- `sound_condition` describes ordinary sound captured in the room, not the ultrasonic jamming signal.
- sound_condition describes ordinary sound captured in the room; the UI may display it as ordinary recorded sound.
- Ordinary sound examples include quiet baseline, meeting-room sound, speech, and WER material.

## Target single-run workflow

1. Create or open a session.
2. Create one run with metadata for frequency, unjammer condition, ordinary sound condition, microphone, room, geometry, DAQ settings, and safety notes.
3. If Mac Helper is connected, select the sound file, device ID, sample rate, channels, gain, and playback delay for that run.
4. Validate playback before any synchronized play-and-record action.
5. Validate that the selected jamming WAV file matches the run metadata frequency. A `25 kHz` run must use the 25 kHz jamming WAV, and a `32.8 kHz` run must use the 32.8 kHz jamming WAV.
6. Allow separate test controls:
   - playback only, for checking the ultrasonic speaker path;
   - recording only, for checking Linux microphone/DAQ capture;
   - play and record, for synchronized Mac playback plus Linux measurement.
   - play and capture, for synchronized Mac playback plus Linux measurement with operator approval before report-grade finalization.
7. Show visual status for Mac playback, Linux capture, live waveform, RMS/peak, clipping, PSD, and spectrogram on the same console page.
8. Write the raw `.bin` first and never overwrite it silently.
9. Convert `.bin` to WAV previews so the operator can listen and confirm that the microphone captured the expected signal.
10. Require explicit operator approval before downstream report-grade processing when approval-gated mode is enabled. The capture-only routes write raw `.bin`, create WAV previews, and set the run status to `awaiting_approval`; the operator then listens/inspects and clicks Finalize From `.bin`.
11. After approval, finalize from the saved `.bin`, generate WAV previews, plots, metrics, logs, and exportable artifacts.

## Analysis intent

The first required comparison is energy or band-power comparison between unjammer conditions, shown to operators as `Unjammed: false` versus `Unjammed: true`, using saved `.bin` data as the quantitative source. Later calibration, WER/CER, and other measurements can be layered on top of the same session/run structure.

Plots should be clean enough for reports or papers: waveform, PSD, spectrogram, comparison PSD overlay, and attenuation bar charts should default to publication-friendly labels, readable ticks, and exportable image files.
