# STATE: <run id>

Updated: <UTC>  Compactions so far: <n>  (refresh the root after the third)

## Identity
- Worktree / commit:
- Candidate identity (`candidate_id` and `content_digest`, both read from `artifacts/candidate.json`; never the record file's own sha256, which changes when verdict evidence is attached):
- Engine sha256 and identity receipt:
- Engine version check (`doctor`'s `capabilities.godot.version` vs contract `engine.version`, or the documented unverified limit):
- Declared render settings vs `launch --mode native`'s fixed 1920x1080/forward_plus (match, or the documented refusal note):
- Selected sources (path, sha256):

## Progress
| Stage | Scope rung | Candidate content digest | Verdict | Artifact |
|---|---|---|---|---|
<!-- Artifact paths: artifacts/launches/<run-id>-<stage>-<n>/exit.json, artifacts/bench/<run-id>-<stage>-<n>/cleanroom.json -->
<!-- Every stage 3-7 row's candidate content digest must equal the current content_digest above (from artifacts/candidate.json, never the record file's own sha256); a stale digest invalidates the row (see overnight-run.md, Corrections invalidate evidence). -->

## Open blockers
-

## Next step (one)
-

## Budget used
- Cutoff / wall clock:
- Native launches by stage:
- Worker spawns and returns:
- Provider spend:

## Receipts
- Preflight (path of the current, non-superseded attempt):
- Doctor (engine version check):
- Launch inventory:
- Cleanroom captures:
