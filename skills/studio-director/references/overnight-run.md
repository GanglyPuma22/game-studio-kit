# Overnight and production-contract runs

Use this procedure when a prompt hands the session an overnight, unattended or
ledger-driven production run for a game project. It exists because a real run
spent hundreds of millions of tokens polling launches, hand-writing ledgers and
benchmarking a contaminated host, then lost four hours to a planned operating
system restart, and delivered no playable minutes. Every stage below names the
kit command that owns its evidence; the text is the part the model must respect
on its own. Install the matching global rules from
[AGENTS-overnight](../../../references/codex/AGENTS-overnight.md) using the
install snippet in [Windows setup](../../../docs/setup-windows.md#install-global-codex-rules-for-unattended-runs)
or [Linux setup](../../../docs/setup-linux.md#install-global-codex-rules-for-unattended-runs).

## 1. Preflight (under 20 minutes, no launches)

`<GAME>` and `<run>` are the same path: the worktree created in step 1 below
is both the run directory and the project root every kit command uses via
`--project`. Say this once; the rest of the procedure writes only `<run>`.
Everything the run writes lives under `<run>/artifacts/`: the hand-maintained
records sit at `<run>/artifacts/run/` (`STATE.md`, `RETURN.md`, the identity
manifest, `feature-manifest.json`, and preflight receipts under
`<run>/artifacts/run/host/`, one per attempt); everything else lands where the kit commands already put it
(`<run>/artifacts/launches/`, `<run>/artifacts/bench/`, `<run>/artifacts/identity/`,
`<run>/artifacts/candidate.json`). Every launch and bench label must start with `<run-id>-`
so receipts from different runs are never confused with each other.

1. `git worktree add <run> <pinned revision>` into a path that does not exist yet; never the preserved candidate. `<run>` stays put for the whole run — never recreated or swapped mid-run, and every later stage's `--project` points at it.
2. Create `<run>/artifacts/run/STATE.md` from [state](../../../templates/state.md).
3. `python <KIT>/scripts/studio.py host preflight --window-start <UTC> --window-end <UTC> --output <run>/artifacts/run/host/preflight-<UTC stamp>.json`, a fresh stamped path per attempt so a failed receipt is never overwritten or deleted; record which one is current in `STATE.md` (a defined checkpoint, see below). This gate applies only on Windows hosts: `host preflight` reports `host_kind: unsupported` elsewhere. On Windows, stop with NEEDS-USER if it is not ready; `host apply` may run only after the user has validated the script by hand once. On any other host, record `host preflight: unsupported on this host` in `STATE.md` and continue; the cleanroom snapshot pair (stage 4) stays mandatory everywhere for performance evidence regardless of preflight support.
4. Copy [identity-manifest](../../../templates/identity-manifest.json) to `<run>/artifacts/run/identity-manifest.json` and fill it from the production contract (engine path and sha256, project sources in this worktree), or use the manifest path the contract already provides.
5. `python <KIT>/scripts/studio.py candidate verify --project <run> --manifest <run>/artifacts/run/identity-manifest.json` for the engine, helpers, sources and packages the contract names, hashed from this worktree. A mismatch stops the run. Verification records identities at the moment it runs; it must be run against the same worktree every later stage uses, never a worktree created or swapped afterward.
6. Read the production contract's `settings.viewport` and `settings.renderer` (`project.json`). `launch --mode native` (`studio_tools/launch.py`'s `mode_flags`) unconditionally passes `--resolution 1920x1080 --rendering-method forward_plus`; there is no flag to change it. If the contract's declared viewport is not exactly `[1920, 1080]` or its declared renderer is not exactly `forward_plus`, record `declared render settings differ from the fixed native launch profile; no performance evidence citable` in `STATE.md` at this checkpoint and refuse stage 4 when it is reached; carry the same sentence into `RETURN.md`'s Not demonstrated section. This is a known limit of `launch --mode native`, not a bug to work around mid-run: the kit fixes native launches to 1920x1080/forward_plus, so this procedure only cites stage 4-7 evidence when the contract already declares that exact resolution and renderer.
7. Copy [feature-manifest](../../../templates/feature-manifest.json) to `<run>/artifacts/run/feature-manifest.json` and fill `canonical_route` from the production contract's own `canonical_route` ([production contracts](../../../references/production-contracts.md)), recording `"route_source": "contract"`. A contract that predates that field has no route: derive one from its `input_route` and the project's main scene, record `"route_source": "derived"`, and flag it in `RETURN.md` for the user to confirm. Leave `features` empty; the run appends one row per feature it wires in, because a feature with no row is not part of the run's claim.

There is no ledger script: the machine ledgers are the receipts the kit
commands already write (preflight receipts, `owned-launch.json`,
`exit.json`, `cleanroom.json`, identity `verify-*.json`) plus the inventory
`evidence launches` builds from them. Never hand-write or poll for a ledger
or heartbeat; a blocking launch replaces polling. When a stage owes more than
one launch, the command that replaces a hand-rolled wait loop is
`python <KIT>/scripts/studio.py batch --project <run> --config <host config>
--sha256 <engine> --plan <plan>`. It runs the planned launches in order, blocks
until the last one has finished, and returns one verdict under a total cap
separate from each run's own timeout. Separate `launch` calls are right only when
a run's arguments depend on an earlier run's verdict, which a fixed plan cannot
express, and when each launch needs its own `bench cleanroom` window: stage 4
wants one capture per rung, each with its own snapshot pair, and a batch inside
one wrapper produces a single attribution window instead. The batch rollup is a
crash record, never a file to read for progress.

A diagnostic batch declares what it is testing. A plan built to reproduce or
isolate a cause carries `must_vary`, the fields that have to differ across its
runs, and `invariants`, the fields that have to stay fixed; a plan that repeats
one condition under a new label is refused rather than run, because the refusal
is cheap and the four green verdicts it would have produced are not. A green
batch that did not vary its cause is `invalid_experiment`, not evidence: it
establishes that the build still starts, which was already known. Validate the
reproduction condition in the cheapest place it can be observed before paying
for long native runs — a defect seen at twilight is not reproduced by four
daylight runs, however green they come back.
`STATE.md`, `RETURN.md` and `<run>/artifacts/run/feature-manifest.json` are the
only hand-maintained run records: `RETURN.md` is write-once, at the
end (Section 5). `STATE.md` is rewritten atomically from its template only at
defined checkpoints: after each preflight attempt, at each stage transition, and at handback. It
gets no other edits.

## 2. Stage gates

| Stage | Owner | Kit command / artifact | Max launches | Max minutes | Stop rule |
|---|---|---|---|---|---|
| 1 Host readiness | root | `host preflight` receipt | 0 | 20 | not ready (Windows) → NEEDS-USER; unsupported elsewhere → continue |
| 2 Source compile | root (script), via kit commands; worker analyzes | terrain/composition build owned and written by the root; worker report JSON, then `candidate new` + `validate-record` | 0 | 60, one compaction | missing report or `compile_verdict: fail` → stop stage |
| 3 Native admission | root | `launch --mode native --timeout <remaining, max 3600> --cutoff-utc <stage deadline>` verdict JSON | 2 | 30 | second verdict not `completed` → stop (retryable) |
| 4 Performance cleanroom | root, idle | `bench cleanroom -- launch ...` with `attributable: true` | one capture per rung plus one repeat (five for the four-rung example) | 45 | fails the frame budget → one attribution pass, no new scope (retryable) |
| 5 Traversal | root | `launch --mode native --timeout <remaining, max 3600> --cutoff-utc <stage deadline>` with the game's route probe and synthetic input ([studio-playtest](../../studio-playtest/SKILL.md)) | 3 per hypothesis, 6 in total | 60 | harness bug → headless fixture, never a native relaunch; stop at 6 total launches (retryable) |
| 6 Visual review | root, desktop | `launch --mode native --timeout <remaining, max 3600> --cutoff-utc <stage deadline>` native stills against the style reference | 2 | 45 | no defect list → stop |
| 7 Audiovisual and human acceptance | operator, then user | `launch --mode native --timeout <remaining, max 3600> --cutoff-utc <stage deadline>` recorded route, listening notes | 1 | 30 | never claimed by the root |

**Stage 2 completion.** The compile report must carry `compile_verdict: pass`
or `compile_verdict: fail`; `fail` or a missing report stops the run at
stage 2. On a `pass` — and again after any later content correction — the
root first verifies the engine version, then creates and validates the
candidate:

1. **Engine version check.** Run `python <KIT>/scripts/studio.py doctor
   --output <run>/artifacts/run/host/doctor-<UTC stamp>.json` (once per run,
   or reuse the current run's receipt if nothing about the host changed) and
   read `capabilities.godot.version`. `doctor` probes the exact
   `executables.godot` path the host config also hands to `launch`
   (`studio_tools/config.py`'s `executable`), so a match is authoritative for
   this host, not merely corroborating. Compare the reported version to the
   production contract's declared `engine.version` (`project.json`); a
   mismatch stops the run before stage 3. [Known limit: if
   `capabilities.godot` carries no `version` field (status `needs_setup` —
   the configured executable is missing, or its `--version` output did not
   match a recognizable version string), no kit command can verify the
   engine version; record `engine version: unverified — doctor could not
   probe the configured executable` in `STATE.md` and stop at stage 2 rather
   than recording the declared version unverified. There is no
   `launch --version` fallback: `launch --mode check` requires `--script`
   and runs an engine script, it does not expose a bare `--version` result as
   its own verdict.]
2. `python <KIT>/scripts/studio.py candidate new --project <run> --id
   <run-id> --engine-version <version>` then `python <KIT>/scripts/studio.py
   validate-record --project <run> --record artifacts/candidate.json` before
   stage 3 starts.

**Finalize the candidate (after stage 7).** Stage 2's `validate-record` runs
before any review evidence exists; no stage finalizes the candidate on its
own — this step does. After stage 7 completes, the root attaches the hashed
captures and review evidence gathered across stages 3-7 to
`artifacts/candidate.json`, setting the five `verdicts`
(`visual`, `interaction`, `motion`, `audio`, `performance`) and
`acceptance.decision`/`reviewer`/`rationale` to match the evidence shape and
methods [acceptance](../../../references/acceptance.md) and
`studio_tools/evidence.py`'s `validate_candidate` require (for example, an
audio pass also needs the evidence entry's `listening` object). [Known limit:
no kit command writes `candidate.json`'s `verdicts`, `defects` or
`acceptance` fields directly. `review ingest`, `review qualify` and
`review assess` (`studio_tools/review_records.py`,
`studio_tools/validation.py`) produce and validate the underlying
run/analysis/qualification evidence a verdict cites, but attaching that
evidence to the candidate record is a direct edit to
`artifacts/candidate.json` today.] After editing the record, the root
re-runs `python <KIT>/scripts/studio.py validate-record --project <run>
--record artifacts/candidate.json`; a failure here means the finalized
record is not usable, and the run reports that rather than presenting an
unvalidated scorecard. `RETURN.md` (Section 5) cites only this validated
final record.

**Corrections invalidate evidence.** Every gate's evidence is bound to the
candidate's immutable content identity, not to the record file's own bytes.
`candidate.json`'s `content_digest` field (`studio_tools/evidence.py`) hashes
only `content_files` — the project's actual game content — so editing
`verdicts`, `defects` or `acceptance` inside the same file, as the finalize
step above does, never changes `content_digest`; a receipt is never staled by
that. `STATE.md` records the current `candidate_id` and `content_digest`
(never a whole-file sha256 of `artifacts/candidate.json`, which changes the
moment finalize attaches verdict evidence), and every stage 3-7 receipt
logged in `STATE.md` is recorded together with the `content_digest` it was
produced under. A receipt is stale when its recorded `content_digest`
differs from the current one — never because the record file's own hash
changed. Whenever `candidate new` is re-run after a content correction (an
actual change to project files, which does change `content_digest`), every
stage 3-7 receipt recorded under the previous `content_digest` is invalid
— there is no exception for a correction that only touched a renderer, LOD or scope setting —
and stages 3 through 7 are repeated in order under the new `content_digest`.
The final scorecard may cite only receipts produced under the final
`content_digest`.

A stage 4 failure blocks stages 5 to 7. No geometry refinement to satisfy a
tolerance proof until stage 4 passes at the scope the refinement will create.
Stage 4's render settings are fixed, not requested: `launch --mode native`
always launches at 1920x1080 with the `forward_plus` renderer regardless of
what the run passes it, so Preflight step 6 (Section 1) is the only gate —
if the contract does not declare that exact resolution and renderer, stage 4
never runs.

**Stage 5 mode.** Traversal launches use `--mode native` explicitly;
`launch`'s default mode is `import`, and no headless mode can establish
traversal. The route probe and its synthetic input are defined by
[studio-playtest](../../studio-playtest/SKILL.md): a probe is a `SceneTree`
harness built from [the template](../../../templates/playtest-harness.gd) that
presses the project's own input actions along a declared route, logs
frame-stamped events, asserts named checks and quits itself. It establishes
wiring only — no unattended stage may promote a green harness into traversal
that a person has accepted. An unattended run drives it with `launch --mode
native --script`, since `playtest`'s session modes all assume somebody is
there; `playtest --session driven` is the same harness with a person available
to look at the result.

**Launch deadlines.** Every `launch` invocation — stages 3, 5, 6 and 7 above,
and the cleanroom-wrapped launch in Section 4 — passes `--timeout <seconds
remaining in the stage, max 3600>` and `--cutoff-utc <stage deadline UTC>`
explicitly. The host config's default timeout is not a stage bound. The
stage deadline is the stage's start time, recorded in `STATE.md` at its
stage-transition checkpoint, plus that stage's budget from the Max minutes
column above.

**Tell the harness to wait.** A blocking command only works if the tool call
carrying it waits as long as the command may run. Set the outer yield directive
on that call — `// @exec: {"yield_time_ms": N}` in the Codex harness — and size N
from the bound that command actually enforces, because only `launch` has a
`--timeout`:

| Command | N in milliseconds |
|---|---|
| `launch` | (`--timeout` in seconds plus 30) times 1000 |
| `batch` | (`--max-minutes` times 60, plus 30) times 1000. An omitted `--max-minutes` is 60 minutes, and that one deadline bounds every run in the plan, so the plan's own timeouts never extend it |
| `playtest --session driven`, and `--session handoff` with a non-zero `--max-minutes` | (`--max-minutes` times 60, plus 30) times 1000. An omitted `--max-minutes` is 60 minutes |
| `playtest --session handoff --max-minutes 0` | the harness's maximum: the session ends when the player quits, so there is no bound to size against |
| `playtest --session attended` | none. Nothing waits for an attended session; it returns at once, and one later `playtest collect` completes it after the person says they are done |

A `yield_time_ms` inside the command's own arguments is not that directive and
does not extend the call. With no directive the harness returns after its default
outer yield, about 30 seconds, which is a harness default and not a host cap: the
directive is what has been measured to hold a call open, an explicit 360-second
one holding a single call for 263 uninterrupted seconds. Harness versions may cap
it, and this procedure claims neither that they do nor that they do not. So a
return before the verdict JSON is never evidence that the run hung — the engine
is still running, and starting a second one puts two engines on the same profile.
When the call returns early despite the directive, the expected path is exactly
one `wait` sized to the time the command still has, and that `wait` is not
polling; the same single sized `wait` is expected after an uncapped `handoff`,
which has no bound to size against. What stays forbidden is the rest: repeated
short waits, empty `write_stdin` calls and a second engine. Two audited runs
spent 72 and 27 waits plus 20 empty writes on one launch, which is the shape this
rule exists to end.

**Scope ladder.** Define the rungs from smallest to full scope before the run,
each with a `safe_id`-valid ID (letters, digits, hyphens, underscores) and a
one-line description; for a planetary terrain game: `macro-terrain` (macro
terrain only), `three-sites` (three certified sites), `hero-obstructions`
(hero area plus obstruction geometry), `habitat-chunk` (one habitat chunk).
Substitute one of these IDs for `<rung>` wherever `--scope <rung>` appears
below. Each rung must pass the frame budget in a cleanroom capture before the
next rung is added: one capture per rung plus one repeat (five captures for
the four-rung example). Pass the rung's ID as `--scope <rung>` to both `bench
cleanroom` and `launch`; both commands persist it in
their receipts. A pass at a lower rung is never cited for a higher one.

## 3. Workers

The root keeps only desktop and visual work; everything text-only leaves it.
Spawn a worker (or run a script) for text work: proof mathematics, test triage,
matrices, inventories, hashing, patch review. Never give a worker desktop, GPU
or provider access. The root (or a script the root runs) owns stage 2 builds through kit
commands and writes the build outputs; a worker only analyzes those outputs
and reports on them. Use [worker-brief](../../../templates/worker-brief.md):
one deliverable file with a JSON schema, its inputs by path and hash, and one
budget line (90 minutes, 8M tokens, two compactions, whichever first). Worker
deliverables and summaries live at `<run>/artifacts/run/workers/<worker-id>/`
— never as a top-level `workers` folder outside `artifacts/`:
`studio_tools.evidence.inventory` hashes everything outside `artifacts/` as
project content, so a worker return outside it would stale the candidate
digest. Where a worker must write anything beyond its
JSON deliverable, the brief's "Allowed outputs" list enumerates the exact
paths; it is empty by default. The worker
returns the JSON record plus a summary under 400 words and terminates; it
takes no follow-up task. The root spawns a new worker that reads state from
files and never re-reads a source a previous worker already summarized.

A worker report is not integration. When the root reads one, it records the
lane's `maturity` in `<run>/artifacts/run/feature-manifest.json` at the step the
report's own evidence supports: assertion counts, a clean export and a green
launch reach `source-ready`, and the root having read the deliverable and its
receipts reaches `root-reviewed`. Neither reaches the route. A completed worker
task leaves the active-worker list; its deliverable stays in the manifest at its
maturity until something wires it in, because three lanes were once reported
complete while nothing had been integrated into the game and the active-worker
list was the only place that said so.

## 4. Benchmarks

```text
python <KIT>/scripts/studio.py bench cleanroom --project <run> --config <host config> --label <run-id>-<stage>-<n> \
  --scope <rung> --timeout 2700 --agent-log <agent activity log> -- \
  python <KIT>/scripts/studio.py launch --project <run> --config <host config> --sha256 <engine> --mode native \
  --script <probe> --timeout <remaining, max 3600> --cutoff-utc <stage deadline> --label <run-id>-<stage>-<n> --scope <rung> --result <summary json>
```

The nested `launch` runs as its own process; the outer command's `--config`
does not propagate to it, so pass `--config <host config>` to both. The
command owns the wait: set the outer yield directive on the tool call that
carries it (Launch deadlines, Section 2) from the capture `--timeout`, not from
the nested launch's. Make no tool calls until it returns; read its one verdict.
Inside a cleanroom window this matters more than elsewhere. Whether a `wait`
continuation reaches the agent activity log depends on what the agent's
`--agent-log` records, which this procedure cannot decide for a host: a timestamp
inside the window sets `attributable` to false, so a capture is safest under a
directive that holds for the whole window. If the harness returns early anyway,
record in `STATE.md` that the stage's captures were completed under a capped
harness, so a later `attributable: false` has a known cause instead of an
unexplained one. A capture whose `attributable` is false, or that lacks the snapshot
pair, cannot be cited. Close only processes the run itself started; record
everything else in the reasons and leave it running.

## 5. Return

Write `RETURN.md` once, at the end, from [return](../../../templates/return.md):
player-facing metrics first (minutes of ordinary-control play, distance
travelled, landings, encounters), then the scorecard by stage and scope, then
what was not demonstrated, then the evidence index produced by
`python <KIT>/scripts/studio.py evidence launches <run>/artifacts/launches`.
A run never reuses a worktree: the pinned worktree from Preflight step 1 is
`--project` for every launch this run makes, so `<run>/artifacts/launches`
is this run's own inventory root and holds only its launches. There is no
flag to filter by run; never place another run's launches under this
worktree. If the run stopped before any launch was owned (at preflight or stage 2, so
no `owned-launch.json` exists yet), skip that command — it raises when the
run root has no launches — and write `launch inventory: none (no launches)`
under Evidence index together with the stop reason.

The scorecard may cite only receipts produced under the final candidate's
`content_digest` (Section 2); a receipt left over from an earlier
`content_digest` is not evidence. Preserve failures. Never claim acceptance from exit codes, unit
tests or source coverage.

**Accepted features.** `<run>/artifacts/run/feature-manifest.json` is the run's
record of what was wired in and who saw it. A row's `human_verdict` is `pending`
(the value it is created with, which is the absence of a verdict), `accepted` or
`rejected`; only `accepted` with evidence on the canonical route at the final
`content_digest` is acceptance ([studio-playtest](../../studio-playtest/SKILL.md)).
A row may be set to `accepted` only when its `evidence` holds, beside the
observation receipt, an identity receipt taken immediately after that session and
before any edit: `python <KIT>/scripts/studio.py candidate new --project <run>
--id <run-id>-<feature> --engine-version <version> --output
artifacts/run/identity/<feature>.json` (the same verified `<version>` stage 2
passed, so the two identity receipts never disagree about the engine), which is
the command that computes the content inventory digest
(`studio_tools/evidence.py`'s `new_candidate`). Copy that receipt's
`content_digest` into the row; never type one. A playtest receipt records the
commit, whether the tree was dirty, and the scene hash, but not the candidate's
content digest, so without this receipt an accepted row can be repointed at a
later digest — a playtest receipt that records the digest itself would be a
later kit change, not something this run can assume. A row whose `content_digest`
differs from the final candidate's is historical: it cannot be accepted for that
candidate, and the feature has to be observed again.
`RETURN.md`'s Accepted features line points at the manifest, and every row that
is not `accepted` is listed under Not demonstrated: a `rejected` row with the
reason it was rejected, a `pending` row as unreviewed. A feature that ran green
in the scene where it was built belongs there too, because a feature reached only
there is not on the canonical route. Two features accepted in isolated scenes
were never wired into the route and nobody noticed until a person played the
game; the manifest exists to make that visible before handback. If the route was
derived rather than supplied (`route_source: derived`), say so on the same line:
the user is confirming the route as well as the features.

**Lanes by maturity.** Every manifest row also carries `maturity`:
`source-ready`, `root-reviewed`, `integrated`, `native-reviewed`,
`user-accepted`. A lane advances only on the evidence for that step. Assertion
counts, clean exports and green launches set at most `source-ready`;
`root-reviewed` means the root read the deliverable and its receipts;
`integrated` needs the feature wired on the canonical route, with `installed_by`
naming a scene the route enters; `native-reviewed` needs a native launch receipt
on that route; `user-accepted` needs `human_verdict: accepted` with its identity
receipt. `RETURN.md` carries a Lanes by maturity line under the scorecard
counting the rows at each step, so a deliverable that was finished and never
reached the player is visible at handback instead of after it. Never report a
lane at a maturity its evidence does not reach, and never drop a row because its
worker finished.

**Snapshot commit (only when authorized).** A run commits nothing by default.
When the production contract carries the authorization line
`snapshot_commit: authorized`, the last Return step is one commit, because a
handback that leaves the run's own output untracked makes the user baseline it by
hand:

1. Decide what is eligible: the files this run produced or changed that are part of the game. Never `artifacts/`, never machine-only evidence, never a path the contract's exclusion list names. Count what was left out.
2. If nothing is eligible — the run stopped early, or every changed file was excluded — create no branch and commit nothing. Record `snapshot: no eligible changes, ref <current commit>` and the excluded count in both records, and stop here; an empty commit records a baseline that does not exist.
3. Otherwise create branch `run/<run-id>` from the pinned worktree's current commit.
4. Stage the eligible files by name: `git add -- <eligible paths>`, never a whole-tree add.
5. Commit once, `git commit -m "run <run-id>: snapshot at Return" --only -- <eligible paths>`. `--only` commits those paths and nothing else, so a path some earlier action left in the index stays out of the snapshot; count it among the excluded.
6. Record the branch ref and the count of excluded files in `STATE.md` and `RETURN.md`.

No push, no merge, no rebase, and no other branch is touched. The commit is a
baseline the user can diff, never evidence of acceptance: a dimension passes on
its receipts or not at all. Without the authorization line the run commits
nothing and records `uncommitted overlay: <staged> staged, <modified> modified or
deleted unstaged, <untracked> untracked` in both records instead, counted from
`git status --porcelain` in the pinned worktree, so the size of what the user
inherits is at least known — the unstaged column is there because a run's own
edits to tracked files land in it.

## 6. Stop rules

Each stage's own stop rule in the table above is authoritative for that stage
and takes precedence over this section: an unmarked stop rule ends the run
the first time it fires. "Fires twice" below applies only to the stages the
table marks retryable (3 Native admission, 4 Performance cleanroom,
5 Traversal), whose own max-launches counts already bound how many attempts
that is.

Stop and hand back when the authorized cutoff is reached, the run budget is
spent, a retryable stage's stop rule fires twice, or the contract needs a
user decision (entitlement, spend, scope, safety contract). A stopped run
with honest state is a good outcome; a run that continues past its rules is
not.
