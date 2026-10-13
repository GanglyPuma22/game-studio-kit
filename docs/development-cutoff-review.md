# Development policy and runtime cutoffs

Development is the default run policy. Missed quality/performance targets, noisy
attribution and exhausted local hypotheses guide the next bounded operation;
they cannot authorize whole-run handback by themselves. Strict qualification
requires explicit authority and applies only the declared action/scope/run
effect. A batch's failure, timeout or stop-on-first-failure ends that batch;
root still evaluates the run's remaining authorized lanes and overall limits.

The run-decision validator checks a caller-supplied record and refuses invalid
stop claims. It is a guard, not a driver: it neither forces agent execution nor
automatically loads policy, writes decisions or schedules another command.
Authority hashes expose provenance; root must verify the actual instruction and
the truth of observations. A source-ready/test-complete deliverable cannot
authorize `goal_done`, which still requires every lane to declare complete with
evidence and user-accepted maturity.

Development completion is separate from human acceptance. A policy lane may name
`completion_maturity` from source-ready through user-accepted; omission retains
user-accepted. The development-only `development_complete` authority requires
every authorized lane to be complete with hashed evidence at or beyond its
declared target. Preserve integration and native goals as lanes with appropriate
targets; an integration lane targeting native-reviewed remains unfinished at
source-ready. Strict mode refuses `development_complete` and retains the
user-accepted threshold for all finished lanes.

`all_lanes_blocked` requires at least one binding-blocked lane; all other lanes
must also be binding-blocked or complete at their applicable policy target.
Feasible or deferred lanes cannot be discarded even when their maturity reaches
the target. A source lane explicitly targeting source-ready can finish while a
native lane is binding-blocked; that handback preserves the unfinished native
work and pending human review. Decision results list non-user-accepted lane IDs
in `pending_human_review` and always return `human_acceptance_established: false`.
These are declaration checks, and no result establishes human acceptance.

Human stop and actual overall cutoff remain binding even with feasible lanes,
remaining local experiment allowance or poor performance. Stop affected work
immediately on human cancellation; receipt validation is not a prerequisite to
honoring cancellation. No check here establishes user playtest acceptance.

Before an operation, calculate its deadline from the actual authorized cutoff,
the remaining explicit overall budgets and its current bounded experiment
window; reserve handback time near cutoff. Pass that bound explicitly to each
command. Neither command below discovers a run-policy record automatically.

```text
python <KIT>/scripts/studio.py batch --project <RUN> --config <HOST> --sha256 <ENGINE-SHA256> --plan <PLAN> --max-minutes <MINUTES> --cutoff-utc <UTC>

python <KIT>/scripts/studio.py bench cleanroom --project <RUN> --config <HOST> --timeout <SECONDS> --cutoff-utc <UTC> -- python <KIT>/scripts/studio.py launch --project <RUN> --config <HOST> --sha256 <ENGINE-SHA256> --timeout <SECONDS> --cutoff-utc <UTC>
```

Batch intersects its local wall-clock bound with the supplied cutoff and
forwards the earliest of that deadline and each plan row's cutoff to launch.
Launch rechecks after preparation. Expired bounds prevent subsequent launches.
The existing plan schema and failure policy remain compatible.

Cleanroom bounds settling and its owned capture timeout, rechecking after
preparation. Its capture can be any command, so it preserves the arguments.
Every nested studio command must explicitly receive the same or earlier cutoff;
the outer capture timeout alone does not supply the nested command's semantic
deadline. Expiry during preparation yields refused/diagnostic capture evidence.
With no cutoff supplied, existing invocation bounds and receipt fields remain.

Cutoffs bound launch/capture admission and waiting. Final snapshots, receipt
writes and safe owned-process cleanup may finish afterward. Process ownership,
performance-pass evidence and paid-request guards are preserved. Blocking calls
still need a sufficiently sized outer harness directive and a single verdict;
there is no new polling loop.

Provider cumulative accounting, cross-record hypothesis usage/rename enforcement,
automatic immutable decision creation and reserve computation remain deferred.
The patch cannot prevent host/API interruption or guarantee autonomous progress.
