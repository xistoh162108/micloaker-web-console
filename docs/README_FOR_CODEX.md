# README for Codex

Implement the app in phases. Prioritize stability over feature count. The Linux Console must work without DAQ and without Mac Helper.

Use `GOAL_PROMPT_UNDER_4000_CHARS.md` as the short goal. Use `AGENTS.md` as the highest priority project instruction. Use the other documents as detailed references.

Important: do not use a database. Implement text-file persistence using JSON, JSONL, CSV, Markdown, and logs.

Expected deliverables:

```text
micloaker_lab_console/
  app/...
  mac_helper/...
  tests/...
  README.md
  requirements.txt
  requirements-mac-helper.txt
```

Minimum first successful demo:

1. Run app locally.
2. Create session.
3. Create mock run.
4. Generate `.bin`.
5. Generate peak/range WAVs.
6. Finalize metrics and plots.
7. Compare two mock runs.
8. Export session ZIP.
9. View logs.

Only after this is stable, add live monitor and Mac Helper.
