# Model QA lane result

Branch: `codex/model-qa`, based on `origin/main`
`97b3397d550e0043966ff9190e5cb1dd2062b412`. Version remains **0.1.14**.
All changes on this branch are new files. No game scripts, existing manifests,
other branches, machine permissions or installed plugin files were changed.

## Delivered

- `python -m studio_tools.model_qa`: one bounded headless Blender worker checks
  every LOD for M12 attachment, M13 measured crossings, M5 four-side outline
  difference and part correspondence, triangle budget, and ecology completeness.
- `report.json`, a compact `REPORT.md`, shared-crop contact sheet, full-resolution
  binary silhouettes, source/input identities, and owned process receipts.
- [A short skill for Claude and Codex](../../skills/studio-model-qa/SKILL.md),
  [setup and limitations](../../docs/model-qa.md), reproducible synthetic GLB
  builders and tests, and an opt-in same-file reference comparison script.
- [Three proof families](../../docs/proof/model-qa/README.md), with generic names
  and unchanged measurements. Input hashes retain exact provenance; the local
  handoff supplies the private source mapping.

## Verification

- Eight focused tests passed with Blender enabled, with no skips. They include
  clean geometry, floating and crossing parts, dropped LOD geometry, animated
  detachment, the 3 mm boundary, stable names, missing metadata and failed/stale
  execution handling. The clean CLI returns 0; defective fixtures return 1.
- Same-file reference parity: **18/18**. M12 verdicts and floating identities,
  plus static M13 verdicts, counts and crossing-pair identities agree. There
  are **no reference disagreements to conceal or retune**.
- Every external LOD passes M12 and M13. Specimen B LOD0 has the same allowed
  minor pair in the reference and port: parts **56 and 102**, span **0.9 mm**,
  at `[-0.022, 0.080, -0.021]` metres. No major clips.
- Package validation and skill validation passed.
- Full repository suite: **1131 tests, 8 failures, 8 errors, 23 skips**.
  **15/15 unrelated failures reproduce on the untouched base**.
  The one lane-induced failure is the manifest coverage check below. The
  full suite was not presented as green.
- The final contact-sheet refinement was followed by the eight focused tests
  and all three proof runs. The report measurements are byte-for-byte
  equivalent as parsed JSON to the prior proof; only presentation changed.
- Blender **5.1.0**, bundled Python **3.13.9**. Dependency versions and exact
  hashes are in the proof JSON. Test dependencies were isolated outside the
  repository; no global packages or machine permissions were changed.

## Open integration step: existing manifest

The lane rules say **new files only**. Adding these runtime resources and the
skill to the existing `studio-kit.json` would violate that constraint.
Consequently
`test_pr1_corrections.CorrectionTests.test_resource_manifest_covers_required_runtime_and_templates`
fails for the eleven new runtime files.

[register-model-qa.patch](register-model-qa.patch) is the exact minimal
registration change, prepared for the reviewer and **not applied**. It adds
the skill, runtime files and setup document, without changing the version.
`git apply --check` passes. Apply it as part of the review/merge work when
changes to existing manifests are authorized:

```text
git apply --check codex-out/model-qa/register-model-qa.patch
git apply codex-out/model-qa/register-model-qa.patch
python -m studio_tools check-package --root .
python -m unittest discover -s tests -p test_pr1_corrections.py -v
```

The standalone module is runnable now; packaging registration remains pending.
This file is an integration patch, not a fallback for Git write failure.

## Asset findings

| Family | LOD0 / LOD1 / LOD2 tris | Maximum budget | LOD1 / LOD2 diagnostic XOR/union | Flagged correspondence parts |
|---|---|---:|---|---|
| A | 10442 / 5931 / 3917 | 5000 | 20.98% / 24.42% | 1277 / 348 |
| B | 7288 / 4310 / 2890 | 5000 | 23.82% / 25.36% | 815 / 213 |
| C | 4400 / 2028 / 1378 | 2000 | 14.65% / 26.17% | 45 / 72 |

All three combined reports are **FAIL**, not review-ready rounds:
ecology documents and actual switch distances were absent from the supplied
inputs. Several LODs exceed the class budgets. At the fallback distances,
outline differences exceed the unchanged default 5% policy and geometry
correspondence flags many parts. A flag can mean simplification or movement as
well as deletion. Every part ID and position is preserved in the JSON.

No defaults were tuned to make these inputs pass. Fallback distances are
diagnostic only. The 5% pixel and 3 mm part-correspondence defaults are explicit
mechanical policies, not user-calibrated artistic acceptance.

## Exact reruns in the retained lane workspace

From the kit worktree, use the Blender executable and matching dependency
directory recorded in the local handoff as `MODEL_QA_BLENDER` and
`MODEL_QA_PYTHON_SITE_PACKAGES`. Each output directory must be new.

```text
python -m unittest discover -s tests -p test_model_qa.py -v
python -m studio_tools.model_qa ../inputs/specimen-a --budget-tris 5000 --ecology ../inputs/specimen-a/ecology.md --out ../proof-a-rerun --timeout 1800
python -m studio_tools.model_qa ../inputs/specimen-b --budget-tris 5000 --ecology ../inputs/specimen-b/ecology.md --out ../proof-b-rerun --timeout 1800
python -m studio_tools.model_qa ../inputs/specimen-c --budget-tris 2000 --ecology ../inputs/specimen-c/ecology.md --out ../proof-c-rerun --timeout 1800
```

Those three commands intentionally reproduce the missing-entry failures.
For actual qualification, supply the authoritative ecology entries and
`--switch-distances` for all levels. The reference comparison's arguments
and source script hashes are retained in the local handoff and proof JSON.
Synthetic inputs can be rebuilt with
`python tests/model_qa_fixtures.py <new-fixture-folder>`.

## Questions for the reviewer

1. Supply each family's authoritative ecology entry and runtime switch distances.
2. Decide whether to calibrate the explicitly heuristic M5 thresholds against
   ordinary game-distance observations; do not infer visual acceptance here.
3. Apply the supplied manifest registration during integration. The version
   bump remains the reviewer's responsibility.

## Preservation and operational limits

This was tool development, not an engine playtest. No game-engine launches,
paid providers, model edits, version bumps, PRs or merges were performed.
Windows preflight reported a pending restart and inactive Update pause;
settings were left unchanged. Short bounded headless Blender tool jobs
completed with clean owned-process receipts. Human artistic acceptance is
pending.

Raw inputs, original checker outputs, earlier diagnostic reports, test logs,
isolated dependencies and the one task worktree remain in the local lane
workspace. The baseline source archive was allocated only to reproduce the
15 existing failures; it is not another game checkout. No existing user data was deleted.
The published branch holds the new tool, synthetic builders, reports, images
and integration patch. It excludes host receipts, private source mappings,
external model binaries, dependency environments and Blender files.
