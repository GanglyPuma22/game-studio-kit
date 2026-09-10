# Overnight and production runs

These rules apply whenever a prompt names an overnight, unattended, production or ledger-driven run, or hands you a production contract for a game project. They exist because one such run spent hundreds of millions of tokens and delivered zero playable minutes. The full procedure is `skills/studio-director/references/overnight-run.md` in the installed Game Studio Kit; its commands enforce what this text asks for.

## Root session
- You are the only desktop and GPU owner. Never spawn a worker with desktop, GPU or provider access.
- After your third context compaction, update `STATE.md` (current commit, selected sources, stage reached, open blockers, next step, budget used) and end the turn asking the user to start a fresh session from it. Do not continue past compaction three.
- Desktop and visual work only: terrain and modelling GUIs, Blender MCP, inspection of native stills, lifecycle helpers, live playtests. Everything text-only (proof mathematics, test triage, matrices, ledgers, inventories, hashing, patch review) goes to a worker or a script.
- Never poll a running process with sleeps, waits or empty stdin writes. Launch through `studio launch` and read its single verdict when it returns.
- Ledgers and heartbeats are appended by script, one line per event. Write `RETURN.md` once, at the end, from `studio evidence launches`. Do not rewrite matrices mid-run.

## Workers
- One deliverable per spawn. The brief names the deliverable file, its JSON schema and the budget.
- Budget: 90 minutes, 8M tokens, two compactions, whichever comes first. Stop and return at the budget even if incomplete.
- Return a JSON record plus a summary under 400 words, then terminate. No follow-up tasks; the root spawns a new worker that reads state from files.
- Never re-read a source file that a previous worker already summarized into a file. Read the summary.

## Critical path
- Performance is measured at the current scope, in a `studio bench cleanroom` window, before any geometry refinement, LOD change, tolerance proof or scope expansion. A performance failure triggers one bounded attribution pass, not new scope.
- Scope ladder: rungs from smallest to full scope, defined before the run. Each rung passes the frame budget before the next is added. A pass at a lower rung is never cited for a higher one.
- Harness bugs are fixed and re-tested in a headless fixture, never by relaunching a multi-minute native run.

## Host and benchmarks
- Run `studio host preflight` for the window before the first launch; stop with NEEDS-USER if it is not ready.
- Before and after every timed capture the cleanroom snapshot pair must exist and the capture must be attributable. No tool calls of any kind during the window. Close only run-owned processes; record everything else.

## Handback
- The first lines of `RETURN.md` are player-facing metrics: minutes of ordinary-control play, distance travelled, landings, encounters. Then the scorecard by stage and scope.
- Preserve failures. Never claim acceptance from exit codes, unit tests or source coverage.
