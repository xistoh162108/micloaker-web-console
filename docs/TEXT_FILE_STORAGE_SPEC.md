# Text-file Storage Specification

## 1. Core decision

Do not use a database. The app stores all persistent state using text files and ordinary experiment files. This keeps the system simple, transparent, and recoverable.

## 2. Storage types

| Purpose | Format |
|---|---|
| Session metadata | JSON |
| Run metadata | JSON |
| Session/run index | JSONL |
| Job history | JSONL |
| App events | JSONL |
| Metrics | JSON + CSV |
| Compare results | JSON + CSV |
| Reports | Markdown |
| Logs/tracebacks | `.log` text files |
| Export manifests | JSON |

## 3. Workspace structure

```text
workspace/
  sessions/
    <session_id>/
      session.json
      runs.jsonl
      events.jsonl
      bin/
      wav/
      plots/
      results/
      metadata/
        <run_id>.json
      logs/
        <run_id>.log
      comparisons/
        <compare_id>.json
        <compare_id>.csv
      summary.csv
      session_report.md
  uploads/
  .micloaker/
    config.json
    sessions.jsonl
    jobs.jsonl
    app_events.jsonl
    app.log
```

## 4. Indexing model

Use append-only JSONL index files for quick listing. Example `sessions.jsonl`:

```jsonl
{"event":"session_created","session_id":"260528_r25k_test","created_at":"...","path":"sessions/260528_r25k_test/session.json"}
```

Example `runs.jsonl` inside a session:

```jsonl
{"event":"run_created","run_id":"...","created_at":"...","metadata_path":"metadata/<run_id>.json"}
{"event":"run_finalized","run_id":"...","finished_at":"...","metrics_path":"results/<run_id>_metrics.json"}
```

The source of truth is the per-session/per-run JSON file. JSONL indexes are convenient lists and can be rebuilt by scanning files.

## 5. Recovery behavior

On app startup:

1. Ensure workspace folders exist.
2. Load `config.json` if present.
3. Scan `sessions/*/session.json`.
4. Scan each session's `metadata/*.json`.
5. Rebuild in-memory lists.
6. If JSONL index files are missing or stale, offer a “Rebuild Index” action or rebuild automatically.

## 6. Atomic writes

For JSON files, write atomically:

```text
write to <file>.tmp
fsync if feasible
rename tmp → final
```

This reduces corruption if the app is stopped during a write.

## 7. Append-only logs

For JSONL and `.log` files, append lines. Each line should include timestamp and event/job/run IDs.

## 8. No silent overwrites

If an output file exists, create a new numbered filename or require explicit overwrite confirmation. Raw `.bin` should never be overwritten silently.

## 9. Benefits

- Easy to inspect manually.
- Easy to zip and send.
- No migration burden.
- No DB corruption issue.
- Fits temporary lab-tool usage.

## 10. Limitations

This is not optimized for tens of thousands of runs. That is acceptable for the current experiment tool. For this version, do not add a database.
