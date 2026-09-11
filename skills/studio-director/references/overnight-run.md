# Overnight and production-contract runs

Use this procedure when a prompt hands the session an overnight, unattended or
ledger-driven production run for a game project. It exists because a real run
spent hundreds of millions of tokens polling launches, hand-writing ledgers and
benchmarking a contaminated host, then lost four hours to a planned operating
system restart, and delivered no playable minutes. Every stage below names the
kit command that owns its evidence; the text is the part the model must respect
on its own. Install the matching global rules from
[AGENTS-overnight](../../../references/codex/AGENTS-overnight.md).

## 1. Preflight (under 20 minutes, no launches)

`<GAME>` and `<run>` are the same path: the worktree created in step 1 below
is both the run directory and the project root every kit command uses via
`--project`. Say this once; the rest of the procedure writes only `<run>`.
Everything the run writes lives under `<run>/artifacts/`: the hand-maintained
records sit at `<run>/artifacts/run/` (`STATE.md`, `RETURN.md`, the identity
manifest, and preflight receipts under `<run>/artifacts/run/host/`, one per
attempt); everything else lands where the kit commands already put it
(`<run>/artifacts/launches/`, `<run>/artifacts/bench/`, `<run>/artifacts/identity/`,
`<run>/artifacts/candidate.json`). Every launch and bench label must start with `<run-id>-`
so receipts from different runs are never confused with each other.

1. `git worktree add <run> <pinned revision>` into a path that does not exist yet; never the preserved candidate. `<run>` stays put for the whole run — never recreated or swapped mid-run, and every later stage's `--project` points at it.
2. Create `<run>/artifacts/run/STATE.md` from [state](../../../templates/state.md).
3. `python <KIT>/scripts/studio.py host preflight --window-start <UTC> --window-end <UTC> --output <run>/artifacts/run/host/preflight-<UTC stamp>.json`, a fresh stamped path per attempt so a failed receipt is never overwritten or deleted; record which one is current in `STATE.md` (a defined checkpoint, see below). This gate applies only on Windows hosts: `host preflight` reports `host_kind: unsupported` elsewhere. On Windows, stop with NEEDS-USER if it is not ready; `host apply` may run only after the user has validated the script by hand once. On any other host, record `host preflight: unsupported on this host` in `STATE.md` and continue; the cleanroom snapshot pair (stage 4) stays mandatory everywhere for performance evidence regardless of preflight support.
4. Copy [identity-manifest](../../../templates/identity-manifest.json) to `<run>/artifacts/run/identity-manifest.json` and fill it from the production contract (engine path and sha256, project sources in this worktree), or use the manifest path the contract already provides.
5. `python <KIT>/scripts/studio.py candidate verify --project <run> --manifest <run>/artifacts/run/identity-manifest.json` for the engine, helpers, sources and packages the contract names, hashed from this worktree. A mismatch stops the run. Verification records identities at the moment it runs; it must be run against the same worktree every later stage uses, never a worktree created or swapped afterward.

There is no ledger script: the machine ledgers are the receipts the kit
commands already write (preflight receipts, `owned-launch.json`,
`exit.json`, `cleanroom.json`, identity `verify-*.json`) plus the inventory
`evidence launches` builds from them. Never hand-write or poll for a ledger
or heartbeat; a blocking launch replaces polling. `STATE.md` and `RETURN.md`
are the only hand-maintained run records: `RETURN.md` is write-once, at the
end (Section 6). `STATE.md` is rewritten atomically from its template only at
defined checkpoints: after each preflight attempt, at each stage transition,
after the third compaction (Section 5, root refresh), and at handback. It
gets no other edits.

## 2. Stage gates

| Stage | Owner | Kit command / artifact | Max launches | Max minutes | Stop rule |
|---|---|---|---|---|---|
| 1 Host readiness | root | `host preflight` receipt | 0 | 20 | not ready (Windows) → NEEDS-USER; unsupported elsewhere → continue |
| 2 Source compile | root (script), via kit commands; worker analyzes | terrain/composition build owned and written by the root; worker report JSON, then `candidate new` + `validate-record` | 0 | 60, one compaction | missing report or `compile_verdict: fail` → stop stage |
| 3 Native admission | root | `launch --mode native` verdict JSON | 2 | 30 | second verdict not `completed` → stop (retryable) |
| 4 Performance cleanroom | root, idle | `bench cleanroom -- launch ...` with `attributable: true` | one capture per rung plus one repeat (five for the four-rung example) | 45 | fails the frame budget → one attribution pass, no new scope (retryable) |
| 5 Traversal | root | `launch --mode native` with the game's route probe and synthetic input | 3 per hypothesis, 6 in total | 60 | harness bug → headless fixture, never a native relaunch; stop at 6 total launches (retryable) |
| 6 Visual review | root, desktop | native stills against the style reference | 2 | 45 | no defect list → stop |
| 7 Audiovisual and human acceptance | operator, then user | recorded route, listening notes | 1 | 30 | never claimed by the root |

**Stage 2 completion.** The compile report must carry `compile_verdict: pass`
or `compile_verdict: fail`; `fail` or a missing report stops the run at
stage 2. On a `pass` — and again after any later content correction — the
root runs `python <KIT>/scripts/studio.py candidate new --project <run> --id
<run-id> --engine-version <version>` then `python <KIT>/scripts/studio.py
validate-record --project <run> --record artifacts/candidate.json` before
stage 3 starts. `STATE.md` records the resulting `artifacts/candidate.json`
digest; stage 6 and 7 review evidence binds to that digest, so regenerating
the candidate after a correction invalidates any review evidence recorded
against the earlier one.

Stage 4 runs immediately after any renderer, LOD or scope change and blocks
stages 5 to 7 on failure. No geometry refinement to satisfy a tolerance proof
until stage 4 passes at the scope the refinement will create.

**Stage 5 mode.** Traversal launches use `--mode native` explicitly;
`launch`'s default mode is `import`, and no headless mode can establish
traversal.

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

Spawn a worker only for text work: proof mathematics, test triage, matrices,
inventories, hashing, patch review. Never give a worker desktop, GPU or provider
access. The root (or a script the root runs) owns stage 2 builds through kit
commands and writes the build outputs; a worker only analyzes those outputs
and reports on them. Use [worker-brief](../../../templates/worker-brief.md):
one deliverable file with a JSON schema, its inputs by path and hash, and one
budget line (90 minutes, 8M tokens, two compactions, whichever first). Where a
worker must write anything beyond its JSON deliverable, the brief's "Allowed
outputs" list enumerates the exact paths; it is empty by default. The worker
returns the JSON record plus a summary under 400 words and terminates; it
takes no follow-up task. The root spawns a new worker that reads state from
files and never re-reads a source a previous worker already summarized.

## 4. Benchmarks

```text
python <KIT>/scripts/studio.py bench cleanroom --project <run> --config <host config> --label <run-id>-<stage>-<n> \
  --scope <rung> --timeout 2700 --agent-log <agent activity log> -- \
  python <KIT>/scripts/studio.py launch --project <run> --config <host config> --sha256 <engine> --mode native \
  --script <probe> --cutoff-utc <window end> --label <run-id>-<stage>-<n> --scope <rung> --result <summary json>
```

The nested `launch` runs as its own process; the outer command's `--config`
does not propagate to it, so pass `--config <host config>` to both. The
command owns the wait. Make no tool calls until it returns; read its one
verdict. A capture whose `attributable` is false, or that lacks the snapshot
pair, cannot be cited. Close only processes the run itself started; record
everything else in the reasons and leave it running.

## 5. Root refresh

After the third context compaction, update `STATE.md` (current commit and
candidate identity, selected sources with hashes, stage reached with verdict
paths, open blockers, next step, budget used) and end the turn with:
"Compaction limit reached. Start a fresh session from `<run>/artifacts/run/STATE.md`."
Do not continue past compaction three.

## 6. Return

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
under Evidence index together with the stop reason. Preserve failures.
Never claim acceptance from exit codes, unit tests or source coverage.

## 7. Stop rules

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
