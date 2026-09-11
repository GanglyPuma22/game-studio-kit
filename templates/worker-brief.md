# Worker brief: <deliverable id>

- Deliverable file: `<run>/workers/<id>/<name>.json`
- Schema: (fields, types, required; one `limits` list naming what this file does not establish; top-level `"status": "complete" | "incomplete"` and `"incomplete_fields": []`; a stage 2 compile-report deliverable also carries top-level `"compile_verdict": "pass" | "fail"`)
- Summary file: `<run>/workers/<id>/SUMMARY.md`, under 400 words
- Inputs (path and sha256 each; read the summaries, not the sources they summarize):
  -
- Question this deliverable answers:
- Allowed outputs beyond the deliverable and summary (empty by default; the root lists exact paths here only when this worker must write something else):
  -
- Out of scope (no desktop, GPU, provider or launch access; no edits outside the deliverable, the summary and any paths listed above):
- Budget: 90 minutes, 8M tokens, two compactions, whichever comes first. Stop and return at the budget even if incomplete; omit any field not produced and list its name in the required `incomplete_fields` array (empty when complete). Never violate a field's declared type.
- On return: write both files, print the deliverable path, terminate. Accept no follow-up task.
