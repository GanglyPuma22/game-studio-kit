# C2 work card

- Outcome: distinguish applicability/policy from defects and missing measurements;
  parse authored ecology and supported glTF geometry without changing source assets.
- Owner: model QA lane; branch codex/model-qa-0116 from release 0.1.15,
  97ef8d580e9485ac06ac2caaa3f31dcc99fe79b2. Reuse the existing lane checkout.
- Scope: model_qa modules, generic fixtures/tests, documentation, five version files.
  No game changes, providers, merges, PRs or installation updates.
- Evidence: failing-before tests for all six requested changes; full suite compared
  with the recorded platform baseline; unchanged external-input rerun with hashes.
- Allocation: 74 selected read-only input copies, 153,151,944 bytes, plus 11 ecology
  documents outside the kit. Reports are bounded to one run per family and a small
  set of explicit applicability comparisons. Preserve raw logs, partial reports,
  and private input mapping locally; publish only generic aggregate evidence.
- Constants: 3 mm contact, 0.05 outline fraction, six samples, 1920x1080 remain.
  Per-worker timeout 90 seconds by default; no silent reruns with easier settings.
- Return: push only this branch; leave installed 0.1.15 untouched. Retain checkout,
  dependencies and evidence pending reviewer approval; no deletion authorized.
