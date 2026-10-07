# Multimodal revision records

`review revision` is a read-only, optional companion to the existing review before/after workflow. It reports whether a claimed defect correction has traceable records. It does not inspect pixels, decode video, operate an application, confer native capability or certify quality. It is not connected to acceptance/qualification or a run termination policy.

```sh
python /path/to/kit/scripts/studio.py review revision --project /existing/project --evidence artifacts/revision.json
```

The JSON result names coverage, open defects, unsupported closure claims and unresolved interactive handoffs. A successful command means the record could be processed, not that its defects are closed. `closure_supported_by_record` means only that retained bytes and named declarations support the recorded chain; `human_acceptance` remains `not_established`. Malformed input raises a normal kit input error; missing review coverage produces a useful incomplete report.

## Review the right thing

Use matched views/routes to compare revisions and allow bounded exploratory review beyond those anchors. A still can answer a colour or composition question. A model orbit/Blender inspection can expose hidden surfaces. Motion issues need actual temporal observation; gameplay criteria need native ordinary input. Blender rendering does not prove native gameplay. Do not require all modes for every edit.

An independent critic may inspect actual artifacts or receive temporary exclusive desktop control when the user's authorization and runtime capabilities permit it. Only one operator acts at a time. Record the app/candidate, allowed actions, checkpoint, time window, release and state reconciliation; the critic inspects rather than edits and returns evidence-linked findings. The root verifies findings and owns integration. This protocol does not implement an OS lock or displace another project's active operator. When direct control is unavailable, label operator-mediated review explicitly.

## Schema 1: `kind: review-revision`

- `builder`: named author, used for the advisory independence check. This is not authenticated identity.
- `candidates`: kit file records pointing to retained schema-1 candidate manifests, with content and workflow inventories/digests. Historical inventory bytes need not still be the current working tree. The manifest's own bytes/hash must remain available.
- `criteria`: rows with `id`, `kind` (`visual`, `temporal`, `interaction`), `subjects`, `required_scope`, and `environment` (`any`, `native`, `lab`, `blender`). Scope names are project-defined, for example close/reverse/approach; they are not universal mandatory camera names.
- `evidence`: rows with unique `id`, `candidate_id`, `content_digest`, `criterion_id`, `subjects`, `method` (`still`, `clip`, `model_inspection`, `scene_inspection`, `live_interaction`), `environment`, `observer`, `inspection` (`performed`, `not_run`, `unsupported`), `capability` (`supported`, `unsupported`, `unknown`), `inspected_scope`, `unknowns`, `location`, and retained `files` as kit file records.
- Clips additionally name `media`, one of their retained file records, `interval` and `duration_seconds`. Temporal review declares `temporal_inspection: true`; live temporal/interaction observations name actual `context` and `actions`. Every live interaction needs context/actions. Gameplay evidence declares `input_route: ordinary` or `human`; synthetic input cannot establish ordinary gameplay. Interaction clips also require temporal inspection. Notes may retain a real live observation without fabricating a video.
- Optional evidence `handoff`: `control_mode: exclusive` or `operator_mediated`. An exclusive return needs `released: true` and `state_reconciled: true`; otherwise it remains an operational finding. Omitting this field is not proof of desktop ownership or authorization.
- `defects`: rows with unique `defect_id`, `criterion_id`, `subjects`, `candidate_before`, `before_evidence`, `observed_defect`, `requested_outcome`, and `root_decision` (`open`, `closed`, `rejected`). Claimed closure additionally needs `candidate_after`, changed content, `change_summary`, `after_evidence`, `critic_recheck` and `root_recheck`.
- Each recheck names `observer`, `status: performed`, `verdict: met`, the revised `candidate_id`/`content_digest`, reviewed `evidence` IDs, `inspected_scope`, `unknowns` and `observation`. Both must cover the affected subjects/scope; the critic must differ from the builder. Relevant findings still need the lead's actual scrutiny: arbitrary prose in unknowns cannot be semantically resolved by this checker.
- Optional defect `before_run`/`after_run`: hashed existing `run.json` records. When provided, the original before/after roles, previous link and affected criterion must match. They are not rewritten or adopted into acceptance.
- Rejected findings require `decision_basis: reference` or `user_intent` and `decision_reason`; rejection is reported separately from a corrected defect.

Candidate identity currently uses candidate ID plus content digest. Workflow-only/camera-only changes do not count as a content-defect revision. Compare those through existing review runs and a suitable criterion; do not fabricate content changes to obtain closure. This first extension targets authored-content correction chains, not every kind of experimental improvement.

All fields are local named attestations. File hashes detect drift, not whether an observer told the truth or a clip actually contains the declared event. Keep synthetic examples conspicuously test-only. An inspection report or an accepted string cannot grant human acceptance.

## Tests and a real pilot

The [small synthetic example](../examples/review-revision/README.md) can be run through the CLI without any engine/provider operations. Its hashes refer to local toy text files only.

`python -m unittest discover -s tests -p test_review_revision.py -v` exercises record linkage, six-pocket coverage, still/clip/live distinctions, changed candidates, ordinary input, retained evidence drift, independent rechecks and unresolved handoffs. The fixtures contain synthetic text bytes, not images or gameplay.

For a real efficacy pilot, select an existing pocket, preserve exact current identity, perform directed plus exploratory inspection, record one actual defect, make a focused revision and conduct a matched independent/root recheck. Keep unrelated access/motion defects open. Offline schema tests and retrospective documentary reviews cannot substitute for that complete real cycle.
