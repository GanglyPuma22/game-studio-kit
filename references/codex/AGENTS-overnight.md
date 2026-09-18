<!-- game-studio-kit overnight-rules begin -->
# Overnight and production runs (Game Studio Kit)

When a prompt names an overnight, unattended, production or ledger-driven run, or hands you a production contract for a game project, read `skills/studio-director/references/overnight-run.md` in the installed kit in full before the first command; it carries the procedure, budgets, scope ladder and templates. There is no `studio` on PATH: run every command as `python <KIT>/scripts/studio.py <command>` with an explicit project or output root.
- The root session is the only desktop, GPU and provider owner. Workers get text-only work (proof mathematics, test triage, matrices, inventories, hashing, patch review), one deliverable per spawn; never desktop, GPU or provider access.
- Never poll: `studio launch` blocks and returns one verdict, and `python <KIT>/scripts/studio.py batch --project <run> --plan <file>` is the blocking primitive that replaces a hand-rolled wait loop; separate `launch` calls are right only when a run's arguments depend on an earlier run's verdict or each run needs its own `bench cleanroom` window. Never wrap them in a script that starts runs and then checks on them, and never hand-write or poll a ledger or heartbeat; the receipts and `studio evidence launches` are the ledger.
- Run `studio host preflight` before the first launch. On Windows, stop with NEEDS-USER if it is not ready; elsewhere it reports `host_kind: unsupported`, which is recorded and does not stop the run.
- Performance is measured at the current scope in a `bench cleanroom` window before any refinement or scope expansion; a pass at a lower rung is never cited for a higher one.
- Never claim acceptance from exit codes, unit tests or source coverage; preserve failures and lead `RETURN.md` with player-facing metrics.
<!-- game-studio-kit overnight-rules end -->
