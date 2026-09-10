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

`<run>` is `<GAME>/artifacts/runs/<run-id>/`: `STATE.md`, the ledgers, worker
returns and the preflight receipt live there. Every launch and bench label
must start with `<run-id>-` so receipts from different runs are never
confused with each other.

1. `python <KIT>/scripts/studio.py host preflight --window-start <UTC> --window-end <UTC> --output <run>/preflight.json`. Stop with NEEDS-USER if it is not ready; `host apply` may run only after the user has validated the script by hand once.
2. `python <KIT>/scripts/studio.py candidate verify --project <GAME> --manifest <run>/identity-manifest.json` for the engine, helpers, sources and packages the contract names. A mismatch stops the run.
3. Fresh worktree at the pinned revision; never the preserved candidate.
4. Create `<run>/STATE.md` from [state](../../../templates/state.md) and the ledgers by script. Ledgers are appended one line per event; matrices are written once, at the end.

## 2. Stage gates

| Stage | Owner | Kit command / artifact | Max launches | Max minutes | Stop rule |
|---|---|---|---|---|---|
| 1 Host readiness | root | `host preflight` receipt | 0 | 20 | not ready → NEEDS-USER |
| 2 Source compile | worker, CPU only | scripted terrain/composition build with a report JSON | 0 | 60, one compaction | report missing → stop stage |
| 3 Native admission | root | `launch --mode native` verdict JSON | 2 | 30 | second verdict not `completed` → stop |
| 4 Performance cleanroom | root, idle | `bench cleanroom -- launch ...` with `attributable: true` | one capture per rung plus one repeat (five for the four-rung example) | 45 | fails the frame budget → one attribution pass, no new scope |
| 5 Traversal | root | `launch` with the game's route probe and synthetic input | 3 per hypothesis, 6 in total | 60 | harness bug → headless fixture, never a native relaunch; stop at 6 total launches |
| 6 Visual review | root, desktop | native stills against the style reference | 2 | 45 | no defect list → stop |
| 7 Audiovisual and human acceptance | operator, then user | recorded route, listening notes | 1 | 30 | never claimed by the root |

Stage 4 runs immediately after any renderer, LOD or scope change and blocks
stages 5 to 7 on failure. No geometry refinement to satisfy a tolerance proof
until stage 4 passes at the scope the refinement will create.

**Scope ladder.** Define the rungs from smallest to full scope before the run
(for a planetary terrain game: macro terrain only; three sites; hero area plus
obstructions; one habitat chunk). Each rung must pass the frame budget in a
cleanroom capture before the next rung is added: one capture per rung plus one
repeat (five captures for the four-rung example). Pass the same `--scope
<rung>` to both `bench cleanroom` and `launch`; both commands persist it in
their receipts. A pass at a lower rung is never cited for a higher one.

## 3. Workers

Spawn a worker only for text work: proof mathematics, test triage, matrices,
inventories, hashing, patch review. Never give a worker desktop, GPU or provider
access. Use [worker-brief](../../../templates/worker-brief.md): one deliverable
file with a JSON schema, its inputs by path and hash, and one budget line
(90 minutes, 8M tokens, two compactions, whichever first). The worker returns
the JSON record plus a summary under 400 words and terminates; it takes no
follow-up task. The root spawns a new worker that reads state from files and
never re-reads a source a previous worker already summarized.

## 4. Benchmarks

```text
python <KIT>/scripts/studio.py bench cleanroom --project <GAME> --label <run-id>-<stage>-<n> \
  --scope <rung> --timeout 2700 --agent-log <agent activity log> -- \
  python <KIT>/scripts/studio.py launch --project <GAME> --sha256 <engine> --mode native \
  --script <probe> --cutoff-utc <window end> --label <run-id>-<stage>-<n> --scope <rung> --result <summary json>
```

The command owns the wait. Make no tool calls until it returns; read its one
verdict. A capture whose `attributable` is false, or that lacks the snapshot
pair, cannot be cited. Close only processes the run itself started; record
everything else in the reasons and leave it running.

## 5. Root refresh

After the third context compaction, update `STATE.md` (current commit and
candidate identity, selected sources with hashes, stage reached with verdict
paths, open blockers, next step, budget used) and end the turn with:
"Compaction limit reached. Start a fresh session from `<run>/STATE.md`."
Do not continue past compaction three.

## 6. Return

Write `RETURN.md` once, at the end, from [return](../../../templates/return.md):
player-facing metrics first (minutes of ordinary-control play, distance
travelled, landings, encounters), then the scorecard by stage and scope, then
what was not demonstrated, then the evidence index produced by
`python <KIT>/scripts/studio.py evidence launches <GAME>/artifacts/launches`.
Preserve failures. Never claim acceptance from exit codes, unit tests or
source coverage.

## 7. Stop rules

Stop and hand back when the authorized cutoff is reached, the run budget is
spent, a stage's stop rule fires twice, or the contract needs a user decision
(entitlement, spend, scope, safety contract). A stopped run with honest state
is a good outcome; a run that continues past its rules is not.
