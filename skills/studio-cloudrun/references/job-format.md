# Cloud run job format

One JSON object per job. `python <KIT>/scripts/studio.py cloudrun validate --job <file>` checks every rule below; `cloudrun plan` prints the steps a runner will take.

| Key | Required | Rule |
|---|---|---|
| `schema` | yes | `1` |
| `id` | yes | 3-64 lowercase letters, digits and dashes. Names the results branch `studio-results/<id>`, so reuse an id only to replace its results. |
| `type` | yes | A key of `studio cloudrun types` (`godot-capture`, `model-run`). Reserved types are refused. |
| `repo` | yes | `owner/name`. The service also checks it against its `ALLOW_REPOS`. |
| `ref` | yes | Branch or commit. The runner packs exactly this commit. The service checks branches against `ALLOW_REFS`. |
| `setup` | no | One line of shell run from the repository root before `command` (fetch the engine, import). |
| `command` | yes | One line of shell run from the repository root. Write results under `$OUT_DIR`. `$STUDIO_COMMIT` holds the full commit id (the copy has no `.git`). |
| `where` | no | `colab` (default) or `here`. |
| `gpu` | no | `L4` (default), `T4` or `A100`; what the account can hold decides how many run at once. |
| `max_minutes` | yes | 1-240. Setup and command together; the runner adds 20 minutes for the runtime to start and copy in. |
| `results_max_mb` | no | 1-500 (default 200). Past it, only files under 10 MB come back. Files over 10 MB never go to a results branch. |
| `godot` | no | `{"url": "https://...zip", "sha256": "<64 hex>"}`: the runner downloads the engine, checks it and sets `GODOT`. A game that fetches its own engine in `setup` leaves this out. |
| `env` | no | `{"NAME": "value"}`, upper-case names, one-line values. Not `OUT_DIR`, `GODOT`, `JOB_ID`, `STUDIO_COMMIT`, `DISPLAY`, and nothing that looks like a token, secret, password or key. |

## model-run jobs

`model-run` replaces `repo`, `ref`, `setup`, `command`, `godot` and `env` (all refused) with:

| Key | Required | Rule |
|---|---|---|
| `recipe` | yes | A folder under `skills/studio-cloudrun/recipes` with a `recipe.json`. |
| `plan` | yes | `{"cues": [...]}` plus recipe settings. Each cue: unique `id`, the recipe's text field (`prompt` or `caption`), `seeds` (distinct whole numbers, one output each), `seconds` (or a plan-wide `seconds`) within the recipe's limits. Total outputs within the recipe's `max_outputs`. |
| `max_units` | yes | 0.01-20 compute units: the runtime is stopped when this much time at the observed rate has passed. `0` (and only 0) for `where: attended`. |
| `max_rate` | no | Units per hour; the run stops at once if the session's rate is higher. |
| `gpu` | no | Defaults to the recipe's; must be one the recipe lists. |
| `where` | no | `colab` (the service; default) or `attended` (the person's own notebook runtime, [attended.sh](../scripts/attended.sh); spend fixed at 0, no `max_rate` or `budget`). |
| `budget` | no | `{"group": id, "units": total}`: one ceiling across several jobs. Refused once the group has spent its total; each runtime capped at what is left; `max_units` must not exceed the total; all jobs of a group name the same total. |
| `inputs` | no | Speech recipes only: up to 8 `{"path", "sha256", "private"}` files, paths relative to the folder passed as `--inputs` (or the runner's second argument). `private` defaults to true: sent to the runtime only, never to results. |

Speech and casting plans (`kind` `speech` or `voice-casting` in `recipe.json`) use `language`, `character` (`{id, profile_version}`), `max_seconds` (plan-wide or per cue, within the recipe's limit; a longer take is kept and flagged `overlength`), optional `controls` (only those the recipe lists), cues with `id`, `text` (one line, exact words), optional `line_id` and `delivery`, `seeds`, and optional `repeats` (`{cue, seed, after_reload: true}`, each one more output). Speech plans need `reference: {input, sha256, transcript}` naming a private input; casting plans need `controls.instruct` and no reference. See studio-audio's [open voices](../../studio-audio/references/open-voices.md).

## Queue file

`queue.txt` on the queue branch, one job file name per line (`<id>.json`, the file itself under `jobs/`). Blank lines and `#` comments are skipped. A line `STOP` stops the service after running jobs finish. A job runs once per service host; to rerun, use a new id or ask the host's owner to clear it from `service.done`.

## Results

`runner.json`: `{"id", "setup_exit", "run_exit", "minutes", "gpu"}`. `BUILD.txt` (Colab only): repository, ref, commit, GPU and the `gpu=` line. `env.txt`: what the runtime had. `setup.log`, `run.log`, `progress.txt`. Everything else is the job's own `OUT_DIR`.
