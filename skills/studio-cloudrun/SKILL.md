---
name: studio-cloudrun
description: Run a game's capture or test job on a GPU nobody is sitting at, with `studio cloudrun` and the shell runners, either right here in a cloud agent box (free, software Vulkan, slow) or on a Colab GPU through one shared queue service on an always-on host, and bring back clips, stills and numbers.
---

# Studio cloud runs

Use this when a game needs to be drawn and recorded without a person at the controls: scripted gameplay clips for a review, stills of a scene from fixed cameras, a capture that compares two builds. It does not make the capture itself; the game owns that as a command (for example a Godot `--script` recorder driven by bots). This skill runs that command somewhere with a screen and a GPU and brings the results back.

Inputs: the game repository and branch, the game's own setup and capture commands, a time cap, and where to run. Output: the job's `OUT_DIR` copied back, with `runner.json` (exit codes, minutes, and a `gpu=` line that says whether a real GPU or a software driver drew it).

## Pick where it runs

| `where` | What it is | Use it for | Cost and approval |
|---|---|---|---|
| `here` | This machine, with `xvfb-run` and whatever Vulkan driver it has. In a cloud agent box that is lavapipe, a CPU driver. | A handful of short clips or stills, any time. A small Godot game drew about 2 frames a second at 1280x720 (Forward+, 4 cores). | Free; no approval. |
| `colab` | A Colab GPU runtime (L4 by default) started by the queue service on the always-on host. | Many clips, full resolution, long runs, anything a CPU driver would take hours over. | Spends Colab compute units; the service starts only on the person's typed go. |

Neither route gives trustworthy frame timings. A software driver is slow by nature, and on Colab the virtual screen fails to present, which stalls each frame while still drawing it correctly. Read the [runtime notes](references/runtime-notes.md) before using either for performance numbers.

## Write the job

A job is one JSON file ([template](references/job-format.md)):

```json
{
  "schema": 1,
  "id": "skybreak-polish-clips-1",
  "type": "godot-capture",
  "repo": "Owner/game",
  "ref": "claude/some-branch",
  "setup": "tools/cloud_setup.sh",
  "command": "tools/playtest_clips.sh tools/playtest-clips.json \"$OUT_DIR\" --godot ./godot",
  "where": "colab",
  "gpu": "L4",
  "max_minutes": 60,
  "results_max_mb": 200
}
```

- `setup` and `command` run from the repository root on the runtime, each one line of shell. `OUT_DIR`, `JOB_ID` and `GODOT` (when the job pins an engine download under `godot`) are set by the runner; the job's own `env` adds the rest.
- Git decides the build: the runner packs exactly the commit `ref` names. Push first, then queue.
- No credentials ever go to a runtime, and `env` refuses names that look like secrets. A command that needs a private download has to get it some other way.
- Check it before anything runs: `python <KIT>/scripts/studio.py cloudrun validate --job job.json` and `... cloudrun plan --job job.json` (prints every step the runner will take).

`studio cloudrun types` lists the job types. `godot-capture` is the first. Other Colab work that follows the same pattern (Salvage's Colab batches; audio, music and other model generation) is listed as reserved. It is not moved onto this service until its owner decides where the line between this runner and a Colab skill for model runs falls.

## Run here

```text
bash <KIT>/skills/studio-cloudrun/scripts/run_here.sh job.json <checkout at ref> <out dir>
```

The checkout must be at the job's ref (the script refuses otherwise). It needs `xvfb-run` and a Vulkan driver (`apt install xvfb ffmpeg mesa-vulkan-drivers` in a Debian or Ubuntu box).

## Queue by default, or run now in parallel

The queue is the default: it keeps a standing go bounded and leaves GPUs for other work. When the person asks for a job to run now, beside the queue and anything else on the account, run it directly on the service host:

```text
COLAB_SESSION=<unique name> bash <KIT>/skills/studio-cloudrun/scripts/colab_job.sh job.json
```

The runner signs in with `--auth=oauth2` (COLAB_AUTH to change) and keeps a private CLI state file per session; see references/runtime-notes.md.

It takes its own runtime and does not wait for the queue. It still needs the person's go, since it spends units, and it still waits (without spending) when the account holds no free GPU of that type. A running queue, Salvage batch or other session is never a reason to hold a job back: start it and let it wait for a GPU. The service can also run several queued jobs at once (`MAX_PAR` in `service.env`).

The number of GPUs at once is the Colab account's limit, not this kit's: in Oct 2026 the account held 2 L4s and refused a third. A job that can use another type (`"gpu": "T4"`) may start while both L4s are busy; whether types share one limit is not yet established.

## Run on Colab through the queue

The queue is a file on a branch of a **private** repository (`QUEUE_REPO`, branch `studio-queue`): `queue.txt` lists job files, one per line, and `jobs/<id>.json` holds them. A cloud thread adds a job by pushing both; it never touches the service host.

The service host (an always-on WSL box) runs [service.sh](scripts/service.sh) under the [systemd unit](scripts/studio-cloudrun.service). Per job it runs [colab_job.sh](scripts/colab_job.sh): pack the commit, wait for a free GPU, copy in, set up the screen ([runtime_display.sh](scripts/runtime_display.sh)), run the job ([runtime_job.sh](scripts/runtime_job.sh)), copy `OUT_DIR` back, stop the runtime (also on error and at the cap) and push the results to branch `studio-results/<id>` of the results repository. Status goes to `studio-results/queue-status`.

Rules for the service, set by the person and not by a job:

- **It starts only on a typed go** (`service.sh go`). A go covers the bounds below and nothing else. When it stops on a bound or a failed job it stays stopped, across reboots, until the next go.
- Bounds: repos in `ALLOW_REPOS`, refs in `ALLOW_REFS` (default `claude/* codex/* main`), `MAX_PAR` queued jobs at once (default 1; jobs run now, above, are not counted), `MAX_JOBS` per go (10), `MAX_HOURS` per go (16), each job's own `max_minutes` plus 20 minutes of setup.
- The host runs no job command itself: only `git archive`, `colab` and `ssh`.
- Host settings live in `~/studio-cloudrun/service.env`, never in this kit or a job.
- Other queues on the same Colab account keep working: a job waits for a free GPU (up to `GPU_WAIT_MIN`, 240) without spending anything.

## What the results do and do not show

`runner.json` says the job ran and how it exited, nothing more. Clips and stills show what a scripted or bot-driven player did; they say nothing about how the game feels in a person's hands ([acceptance](../../references/acceptance.md)). A `gpu=software` line means a CPU driver drew the frames: colours and layout match, but compare effects that depend on GPU features against a GPU run before reporting a rendering defect.

| Next need | Read |
|---|---|
| Driving the game with a harness or bots | [studio-playtest](../studio-playtest/SKILL.md), [studio-gym](../studio-gym/SKILL.md) |
| Turning clips into a review verdict | [studio-review](../studio-review/SKILL.md) |
| What went wrong on a runtime before | [runtime notes](references/runtime-notes.md) |
