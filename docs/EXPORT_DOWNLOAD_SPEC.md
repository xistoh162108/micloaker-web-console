# Export and Download Specification

## 1. Individual files

Allow download of:

- `.bin`
- peak WAV
- range WAV
- metadata JSON
- metrics JSON/CSV
- plots PNG/SVG
- logs

## 2. Run ZIP

A run ZIP contains:

```text
<run_id>/
  bin/<run_id>.bin
  wav/<run_id>__scale-peak.wav
  wav/<run_id>__scale-range-fs10V.wav
  metadata/<run_id>.json
  results/<run_id>_metrics.json
  results/<run_id>_metrics.csv
  plots/<run_id>_waveform.png
  plots/<run_id>_psd.png
  plots/<run_id>_spectrogram.png
  logs/<run_id>.log
```

If files are missing, include a manifest marking them missing rather than failing silently.

## 3. Session ZIP

A session ZIP contains:

```text
<session_id>/
  session.json
  summary.csv
  runs/... all run packages
  comparisons/... compare results
  session_report.md
  export_manifest.json
```

## 4. Multi-session ZIP

Contains multiple session ZIP-like folders and a top-level manifest.

## 5. Export manifest

Every ZIP should include:

```json
{
  "exported_at": "...",
  "app_version": "...",
  "workspace": "relative or redacted",
  "included_files": [],
  "missing_files": [],
  "notes": ""
}
```

## 6. Safety

- Use relative paths inside ZIP.
- Do not include absolute home paths unless user explicitly requests.
- Do not include files outside workspace.
