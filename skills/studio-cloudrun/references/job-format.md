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
| `gpu` | no | `L4` (default), `T4`, `A100`, or `CPU` for a runtime with no accelerator (`colab new` with no `--gpu`). Use `CPU` for work that never draws on a GPU: headless sims, balance benches, soaks. It costs a small fraction of a GPU's units an hour; it is slower and has fewer cores. What the account can hold decides how many run at once. |
| `high_mem` | no | `true` asks for Colab's High-RAM runtime (`--high-mem`), which also has more CPU cores; needs a plan that offers it. |
| `screen` | no | `true` or `false`. Default `true` on a GPU and `false` on `CPU`. With `false` the runtime installs nothing and starts no virtual screen (the job must run headless); `true` on `CPU` draws with the software Vulkan driver. |
| `max_units` | no | 0.01-20 compute units, as for `model-run` below: on Colab the runtime is stopped at this ceiling or the time cap, whichever comes first. Set it whenever the person gave a unit cap. |
| `max_rate` | no | Units per hour, with `max_units`: the run stops at once if the account's rate is higher (use it to make sure a CPU job never lands on a GPU rate). |
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
| `max_units` | yes | 0.01-20 compute units: the runtime is stopped when this much time at the observed rate has passed. |
| `max_rate` | no | Units per hour; the run stops at once if the session's rate is higher. |
| `gpu` | no | Defaults to the recipe's; must be one the recipe lists. |
| `where` | no | `colab` only. |

## Queue file

`queue.txt` on the queue branch, one job file name per line (`<id>.json`, the file itself under `jobs/`). Blank lines and `#` comments are skipped. A line `STOP` stops the service after running jobs finish. A job runs once per service host; to rerun, use a new id or ask the host's owner to clear it from `service.done`.

## Results

`runner.json`: `{"id", "setup_exit", "run_exit", "minutes", "gpu"}` (`gpu=none ...` on a CPU runtime). `BUILD.txt` (Colab only): repository, ref, commit, GPU and the `gpu=` line. `env.txt`: what the runtime had. `setup.log`, `run.log`, `progress.txt`. Everything else is the job's own `OUT_DIR`.
