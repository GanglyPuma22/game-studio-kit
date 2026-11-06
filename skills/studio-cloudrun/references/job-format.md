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
| `command` | yes | One line of shell run from the repository root. Write results under `$OUT_DIR`. `$STUDIO_COMMIT` holds the full commit id (the copy has no `.git`). For live progress, append lines to `$STUDIO_PROGRESS`, such as `render 140/3000`: an `N/M` or `N of M` gives the status an ETA. |
| `where` | no | `colab` (default) or `here`. |
| `gpu` | no | `L4` (default), `T4`, `A100`, or `CPU` for a runtime with no accelerator (`colab new` with no `--gpu`). Use `CPU` for work that never draws on a GPU: headless sims, balance benches, soaks. It costs a small fraction of a GPU's units an hour; it is slower and has fewer cores. What the account can hold decides how many run at once. |
| `high_mem` | no | `true` asks for Colab's High-RAM runtime (`--high-mem`), which also has more CPU cores; needs a plan that offers it. |
| `screen` | no | `true` or `false`. Default `true` on a GPU and `false` on `CPU`. With `false` the runtime installs nothing and starts no virtual screen (the job must run headless); `true` on `CPU` draws with the software Vulkan driver. |
| `max_units` | no | 0.01-20 compute units, as for `model-run` below: on Colab the runtime is stopped at this ceiling or the time cap, whichever comes first. Set it whenever the person gave a unit cap. |
| `max_rate` | no | Units per hour, with `max_units`: the run stops at once if the account's rate is higher (use it to make sure a CPU job never lands on a GPU rate). |
| `gpu_idle_minutes` | no | 0-240 (default 5; a recipe may set its own). On a GPU, the run stops early (exit 6) when the GPU reads 0 % for this long while `command` runs: it is paying GPU rates for CPU work. `0` turns the check off. Never applies to `CPU`. |
| `max_minutes` | yes | 1-240. Setup and command together; the runner adds 20 minutes for the runtime to start and copy in. |
| `results_max_mb` | no | 1-500 (default 200). Past it, only files under 10 MB come back. Files over 10 MB never go to a results branch. |
| `godot` | no | `{"url": "https://...zip", "sha256": "<64 hex>"}`: the runner downloads the engine, checks it and sets `GODOT`. A game that fetches its own engine in `setup` leaves this out. |
| `env` | no | `{"NAME": "value"}`, upper-case names, one-line values. Not `OUT_DIR`, `GODOT`, `JOB_ID`, `STUDIO_COMMIT`, `STUDIO_PROGRESS`, `DISPLAY`, and nothing that looks like a token, secret, password or key. |

## model-run jobs

`model-run` replaces `repo`, `ref`, `setup`, `command`, `godot` and `env` (all refused) with:

| Key | Required | Rule |
|---|---|---|
| `recipe` | yes | A folder under `skills/studio-cloudrun/recipes` with a `recipe.json`. |
| `plan` | yes | `{"cues": [...]}` plus recipe settings. Each cue: unique `id`, the recipe's text field (`prompt` or `caption`), `seeds` (distinct whole numbers, one output each), `seconds` (or a plan-wide `seconds`) within the recipe's limits. Total outputs within the recipe's `max_outputs`. |
| `max_units` | yes | 0.01-20 compute units: the runtime is stopped when this much time at the observed rate has passed. |
| `max_rate` | no | Units per hour; the run stops at once if the session's rate is higher. |
| `gpu` | no | Defaults to the recipe's; must be one the recipe lists. |
| `gpu_idle_minutes` | no | As above; defaults to the recipe's (`ace-step-music` 10, for its weight download and load). |
| `where` | no | `colab` only. |

## Queue file

`queue.txt` on the queue branch, one job file name per line (`<id>.json`, the file itself under `jobs/`). Blank lines and `#` comments are skipped. A line `STOP` stops the service after running jobs finish. A job runs once per service host; to rerun, use a new id or ask the host's owner to clear it from `service.done`.

## Results

`runner.json`: `{"id", "setup_exit", "run_exit", "minutes", "gpu"}` (`gpu=none ...` on a CPU runtime). `BUILD.txt` (Colab only): repository, ref, commit, GPU and the `gpu=` line. `env.txt`: what the runtime had. `setup.log`, `run.log`, `progress.txt`, `job-progress.txt` (the job's own progress lines), `gpu.csv` (GPU %, MiB every 10 s, on a GPU), `status.json` (the last live status; in the local results folder only, the results branch leaves it out because `studio-status/<id>` carries the final one). Everything else is the job's own `OUT_DIR`.

## Live status

While a job runs on Colab, the service host keeps `~/studio-cloudrun/status/<id>.json`, updated every minute: `state` (running, done, failed), `stage` (packing, waiting-gpu, starting, copying, preparing, setup, run, results, done, or lost), `step` and `eta_min` from `$STUDIO_PROGRESS`, `last_line` of the log, `gpu_util` (highest % over the last minute) and `gpu_mem_mb`, `rate`, `units_spent` (own rate times runtime time) against `max_units`, `elapsed_min` and `note`. Read it on the host with `service.sh status`, `python <KIT>/scripts/studio.py cloudrun status` or `live_status.py show`; a running status not updated for 3 minutes is flagged STALE (the host runner died). With `RESULTS_REPO` set it is also pushed every 5 minutes to branch `studio-status/<id>` (`STATUS.json`, `STATUS.txt`, `driver-tail.log`), so a cloud thread can read it without reaching the host.

Exit codes of `colab_job.sh`: 0 done; 1 failed; 2 invalid job; 3 results not delivered; 4 results do not match the runtime's list; 5 runtime lost (the runtime has no job on it, the session is gone, or it stopped answering for 5 minutes); 6 stopped for an idle GPU; 7 refused because the same job id or session name is already running on this host, or a Colab session with that name already exists.
