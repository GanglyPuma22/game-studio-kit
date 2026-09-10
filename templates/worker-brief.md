# Worker brief: <deliverable id>

- Deliverable file: `<run>/workers/<id>/<name>.json`
- Schema: (fields, types, required; one `limits` list naming what this file does not establish; top-level `"status": "complete" | "incomplete"` and `"incomplete_fields": []`)
- Summary file: `<run>/workers/<id>/SUMMARY.md`, under 400 words
- Inputs (path and sha256 each; read the summaries, not the sources they summarize):
  -
- Question this deliverable answers:
- Out of scope (no desktop, GPU, provider or launch access; no edits outside the deliverable):
- Budget: 90 minutes, 8M tokens, two compactions, whichever comes first. Stop and return at the budget even if incomplete; keep every field's declared type, use `null` for a value not produced, and list its name in `incomplete_fields`.
- On return: write both files, print the deliverable path, terminate. Accept no follow-up task.
