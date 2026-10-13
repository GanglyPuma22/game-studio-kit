# Run policy and decision records

Use [run-policy](../templates/run-policy.json) and
[run-decision](../templates/run-decision.json) for overnight development.
They are additive schema-version-1 records validated synchronously by the existing
`validate-record --project <run> --record <relative-path>` command. Templates are
placeholders: replace hashes and references with actual project-owned files.

The default `mode` is `development`, including when omitted. A numeric target
does not authorize strict mode. `strict_qualification` requires a
`strict_authority` with `type: human_instruction|contract`, hashed `reference`
and stable `rule_id`. Overall limits and hard gates use the same authority shape.
Each explicit limit names `id`, `unit: seconds|tokens|launches` and `maximum`.
Omitted limits mean no such explicit user cap was recorded; the actual UTC cutoff
always remains binding. This validator grants no spend permission.

Policy lanes are the complete inventory of meaningful authorized work, including
source-ready work awaiting integration. Each has `id`, `goal_id`, `scope` and
`dependencies` (other lane IDs). Every declared goal needs a lane. Dependencies
must be acyclic. An optional policy-lane `completion_maturity` declares its
development completion target: `source-ready`, `root-reviewed`, `integrated`,
`native-reviewed` or `user-accepted`, in that order. `in-progress` is not a
completion target. Omission retains the `user-accepted` threshold. Targets belong
in the hashed policy, not the decision inventory, and must preserve the authorized
goals: source work cannot stand in for required integration or native review.
The integration template therefore targets `native-reviewed`.
Strict gates name `id`, `effect: block_action|block_scope|stop_run`
and `affected: {kind: action|scope|run, id: ...}`. Only a gate explicitly affecting
the run with `effect: stop_run` is a possible whole-run authority.

The decision hashes its policy and current candidate, binds `candidate_id` and
`content_digest`, and preserves current candidate validation. `remaining` records
exact seconds until the policy cutoff and usage of every explicit overall limit;
unknown usage is rejected rather than treated as zero. No observation makes
diagnostic evidence into a performance pass.

Every lane inventory row carries policy lane ID, maturity, status
(`feasible|deferred|blocked|complete`) and a concrete `next_operation` when
unfinished. A blocked lane requires a binding `blocker.authority` with type
`identity|compile|host|resource|authorization|dependency|hard_gate`, plus nonempty
hashed `blocker.evidence`. Dependency blockers identify `lane_id`; gate blockers
identify `gate_id` and must affect that lane's action or scope. A quality miss
alone is not a blocker. Complete lanes need hashed `completion_evidence`.

Incomplete work, remaining overall budget and a feasible lane require
`selected_lane` and `selected_operation` matching that lane's concrete operation.
A hypothesis stop uses `disposition: stop_experiment`, an affected experiment ID
equal to `hypothesis.stable_family_id`, and observed `used_trials`/`used_seconds`.
The initial experiment defaults are three trials or 900 seconds, whichever first;
exhaustion stops only that family. Preserve family identity and prior usage;
cross-record cumulative accounting/rename enforcement is not implemented here.

`handback|stop_run` require `affected: {kind: run, id: <run-id>}`, nonempty trigger
evidence, and `stop_authority` with type:

- `deadline`: decision time reached the actual policy cutoff.
- `overall_budget`: `rule_id` identifies an exhausted explicit overall limit.
- `human_stop|global_safety`: corresponding trigger code and provenance.
- `goal_done`: every authorized lane complete with evidence and `user-accepted`
  maturity. Source-ready/test-complete rows cannot authorize goal completion;
  root must verify the explicit human acceptance behind that maturity.
- `development_complete`: development mode only, with every authorized lane
  `complete`, nonempty hashed completion evidence, and maturity at or beyond its
  policy completion target. This hands back completed development work awaiting
  human review; it does not claim acceptance. Strict mode refuses this authority
  even when every row declares `user-accepted`.
- `hard_gate`: matching `hard_gate_failed` trigger/gate ID and explicit stop_run effect.
- `all_lanes_blocked`: at least one lane blocked and every remaining lane
  binding-blocked or complete at its development policy target. In strict mode,
  any lane treated as finished still needs `user-accepted` maturity. All complete
  rows need hashed completion evidence. An omitted target defaults to
  `user-accepted`, so source-ready work cannot silently disappear from the run.
  Feasible, deferred, below-target or omitted work cannot support this stop.

Decision results derive `pending_human_review` from all inventory lane IDs whose
maturity is not `user-accepted`. They also return
`human_acceptance_established: false`: the validator checks declarations and
file hashes, never authenticates a person or establishes playtest acceptance.
Even an empty pending list requires root review of the actual acceptance evidence.

Store each decision at a new `artifacts/run/decisions/<unique-id>.json` and validate
before normal final Return. The validator is read-only and does not enforce file
immutability, authenticate human authority, schedule work, inspect the truth of
arbitrary observation files, or prevent host/API interruption. Root review must
verify provenance, observations and gate failure. No progress polling is added.
Batch and cleanroom accept an explicit `--cutoff-utc`; batch forwards the earlier
deadline to each launch, and cleanroom bounds settling and its owned capture.
Callers must supply the cutoff to every nested studio command; arbitrary capture
arguments are preserved. Neither command automatically loads a run-policy record.
See [runtime cutoff use](../docs/development-cutoff-review.md). Provider cumulative
accounting, automatic decision creation and global handback reserve computation
are deferred.

`compare_baseline` is a conservative helper, separate from acceptance. It reports
target status, retained baseline shortfall and causal regression independently.
Only clean observations with exactly equal declared comparison conditions can
show no observed delta. Demonstrated regression additionally requires the declared
repeat criterion and tolerance; noisy/different-condition comparisons remain
unproven. Conditions must include route, scope, engine, renderer, resolution,
hardware and metric/statistic. Root must verify that those conditions are complete
and the observations credible before claiming causality.
