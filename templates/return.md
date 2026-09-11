# Return: <run id>

## Player-facing outcome
- Minutes of ordinary-control play demonstrated:
- Distance travelled on foot / by ship (m):
- Landings completed / attempted:
- Encounters or scripted events reached:
- Recorded route and listening notes (path, observer):

## Scorecard
| Stage | Scope rung | Passed | Verdict artifact | Notes |
|---|---|---|---|---|
| 1 Host readiness | | | `artifacts/run/host/preflight-<UTC stamp>.json` | |
| 2 Source compile | | | worker report JSON (`compile_verdict`) | |
| 3 Native admission | | | `artifacts/launches/<run-id>-<stage>-<n>/exit.json` | |
| 4 Performance cleanroom | | | `artifacts/bench/<run-id>-<stage>-<n>/cleanroom.json` (`attributable`) | |
| 5 Traversal | | | | |
| 6/7 Visual | | pass / fail / not_run | `artifacts/candidate.json` (`verdicts.visual`) | |
| 6/7 Interaction | | pass / fail / not_run | `artifacts/candidate.json` (`verdicts.interaction`) | |
| 6/7 Motion | | pass / fail / not_run | `artifacts/candidate.json` (`verdicts.motion`) | |
| 6/7 Audio | | pass / fail / not_run | `artifacts/candidate.json` (`verdicts.audio`) | |
| 6/7 Performance | | pass / fail / not_run | `artifacts/candidate.json` (`verdicts.performance`) | |

Overall acceptance (`artifacts/candidate.json`'s `acceptance.decision`) stays
pending the user until every mandatory dimension above is `pass`.

## Not demonstrated
- (every contract goal without a passing artifact, with the reason)

## Evidence index
- Launch inventory (`studio evidence launches`):
- Identity receipt (`studio candidate verify`):
- Cleanroom captures:

## Budget used
- Wall clock / cutoff:
- Root compactions / worker spawns:
- Native launches (stage 3 / 4 / 5 / 6 / 7, total):
- Provider spend:

## Next decision for the user
-
