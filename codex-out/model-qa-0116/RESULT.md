# Model QA 0.1.16 — C2 result

Implemented on `codex/model-qa-0116`, based on 0.1.15 commit
`97ef8d580e9485ac06ac2caaa3f31dcc99fe79b2`. Branch delivery only: no PR,
merge, installation update, paid provider or machine-permission change.
The existing-file edits are required by the explicit C2 repair brief.

## Changes

- Ecology accepts YAML front matter and the existing Markdown forms. Structural
  completeness, proposal status and review status are separate fields.
- Explicit non-living declarations produce N/A; unknown triangle policy produces
  NOT SET. A numeric budget is a maximum only, never an implied minimum.
- Family manifests default to strict assembly attachment. Scatter/clump declarations
  check each connected piece against the declared Y-up ground plane at 3 mm;
  clumps retain raw overlap measurements as INFO. Scatter overlaps remain strict.
- Geometry loading skips images/materials. Worker time defaults to 90 seconds with
  an explicit per-run override. Atomic checkpoints preserve completed rows and
  leave missing measurements UNMEASURED, including allocation/timeout failures.
- Quantized positions, STEP and tangent-scaled CUBICSPLINE skin sampling work at
  the unchanged six samples per clip. Morphs are ignored explicitly: base mesh
  measured, limitation recorded. Source GLBs are never rewritten.
- Five package version declarations now say 0.1.16; no new skill entrypoint was added.

## Validation

The initial 11 new regression tests failed against 0.1.15 (4 failures, 7 errors)
before implementation. The final focused suite passed all 23 tests, with no skips,
including two native Blender integrations and an added manifest-disappearance
regression. Package validation and whitespace checks passed.

Final full suite: 1147 tests, 7 failures, 8 errors, 24 skips; zero new failures. Details are recorded in `validation.json`. The suite is not globally
green on this Windows host: the 15 failures/errors listed below were independently
reproduced on untouched 0.1.15. Thus the brief's literal all-existing-tests-green
criterion remains unmet; no model QA regression is waived by that baseline.

An earlier full run through the isolated venv launcher also hit a lifecycle fixture's
WinError 32 cleanup error. The same test failed on untouched 0.1.15 with that launcher
and passed with the regular Python executable. The final full run uses regular
Python with the local optional-dependency directory on PYTHONPATH. No unrelated
lifecycle source or test was changed.

## Unchanged-input evidence

See [INPUT-RERUNS.md](INPUT-RERUNS.md), `input-rerun-summary.json` and
`execution-audit.json`. The audit verifies 74 unchanged GLBs, 11 unchanged ecology
documents, 26 strict-family reruns and seven explicit applicability experiments.
All runs used 3 mm, 0.05, six samples, 1920x1080 and the 90-second default, with the
same 3 GiB process / 4 GiB job resource bounds. Owned-process cleanup is recorded.
Raw reports and private source mapping remain outside this generic repository.

- Ecology: 42 LOD rows move from FAIL to N/A; 32 to structural PASS. All 11 authored
  living entries remain **proposed**; structural PASS grants no approval.
- Budgets: 40 rows move from FAIL to NOT SET; one measured over-budget row stays
  FAIL. Maximum-only checks do not enforce a separate project's minimum policy.
- Strict geometry: 14 M12 and 17 M13 rows remain FAIL. Unsupported or previously
  unmeasured inputs can now become measured PASS; the comparison distinguishes
  these from applicability changes.
- Explicit clump trials: eight raw FAIL overlap rows become INFO, and one previously
  passing row also becomes INFO. The complete raw M13 pose measurements are identical
  to the matching strict runs. These declarations are provisional experiments,
  not source-owner approval or edits to source metadata.
- Scatter trial: four M12 rows become PASS under per-piece ground contact; the one
  M13 clipping failure remains FAIL. Other clump trials retain floating pieces;
  one previously passing assembly becomes a ground-contact FAIL.
- Families 23, 24 and 26 hit the 90-second limit and remain UNMEASURED, preserving
  completed rows. Family 02's textured five-LOD input completes in 21.781 worker
  seconds; family 25's quantized/morph input is measured with the morph limitation.
- Switch distances are absent in the unchanged source inputs. All 63 completed M5
  rows therefore remain FAIL; 11 are UNMEASURED. Diagnostic renders do not qualify
  LOD transitions.

The external reruns precede the final manifest-loss exception guard and two report
wording changes. Their exact source hashes are retained in `execution-audit.json`;
measurement code is unchanged afterward. The final focused/full tests exercise the
final source. No rerun was weakened or silently extended to obtain a pass.

## Rerun commands

From the kit checkout, with the optional requirements installed in the selected
Python and Blender-compatible dependency directory:

```powershell
python -m studio_tools check-package --root .
$env:MODEL_QA_BLENDER = '<absolute Blender executable>'
$env:MODEL_QA_PYTHON_SITE_PACKAGES = '<Blender-compatible site-packages>'
python -m unittest discover -s tests -p 'test_model_qa*.py' -v
Remove-Item Env:MODEL_QA_BLENDER, Env:MODEL_QA_PYTHON_SITE_PACKAGES
python -m unittest discover -s tests -v
python -m studio_tools.model_qa '<unchanged family folder>' --budget-tris not-set --ecology none --reason 'Non-living asset' --out '<new output folder>' --blender '<absolute Blender executable>' --python-site-packages '<Blender-compatible site-packages>' --timeout 90
```

For living assets replace the ecology arguments with `--ecology '<entry.md>'`;
use the actual positive maximum where declared. Preserve sidecar manifests and
omit missing switch distances rather than inventing them. Exact private input
mapping, memory-bounded runner commands and all raw logs are retained in the local
handoff alongside the task; they are intentionally excluded from the generic kit.

## Known baseline failures (untouched 0.1.15)

- `test_cleanroom_host.ExecuteTests.test_a_symlinked_artifacts_directory_is_refused_before_anything_runs`
- `test_cleanroom_host.HostPreflightTests.test_active_hours_window_walks_the_utc_timeline_across_a_dst_transition`
- `test_launch_evidence.OwnedLaunchTests.test_engine_replaced_after_verification_refuses_to_start`
- `test_launch_evidence.OwnedLaunchTests.test_engine_replaced_during_the_launch_is_not_completed`
- `test_launch_evidence.OwnedLaunchTests.test_scrub_prefixes_match_case_insensitively_only_on_windows`
- `test_launch_profiles.ProfilePlaceholderTests.test_a_passthrough_brace_that_is_not_a_placeholder_is_left_alone`
- `test_playtest.ProjectRevisionTests.test_a_project_outside_any_checkout_reports_no_commit`
- `test_process_identity.PrelaunchSnapshotTests.test_the_engine_is_rehashed_after_the_prelaunch_snapshot`
- `test_blender_run.BlenderRunOrderingTests.test_an_executable_replaced_between_identity_and_launch_does_not_start`
- `test_blender_run.BlenderRunTests.test_cli_run_writes_receipts_without_argv_or_environment_values`
- `test_launch_evidence.OwnedLaunchTests.test_cutoff_with_sub_second_remaining_still_launches`
- `test_launch_evidence.OwnedLaunchTests.test_self_contained_engine_is_refused_before_launch`
- `test_mesh_topology.ReduceTests.test_a_blender_replaced_while_it_ran_is_not_ok`
- `test_mesh_topology.ReduceTests.test_a_blender_that_changed_before_launch_never_starts`
- `test_playtest.LauncherTests.test_launcher_is_runnable_and_names_the_session_it_documents`

## Review decisions still needed

Approve or reject the branch before any merge/install. The project owner must
supply authoritative applicability declarations, unset budgets, switch distances
and ecology approvals. Three timed-out families require an explicit larger bound
or further performance work to finish measuring. Actual terrain contact, morph
poses and human visual acceptance remain outside these mechanical results.
