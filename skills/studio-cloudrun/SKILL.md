---
name: studio-cloudrun
description: Run a job on a GPU nobody is sitting at, with `studio cloudrun` and the shell runners. That covers a game's capture or test job (here in a cloud agent box, or on Colab) and model runs from the kit's recipes (music with ACE-Step, sound effects with Stable Audio Open, experimental speech and voice casting) on a Colab GPU or in a free notebook the person watches, through one shared queue on an always-on host. Results come back as clips, stills, numbers or audio with receipts.
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

`studio cloudrun types` lists the job types and the model recipes. Salvage's Colab batches are listed as reserved: they stay on Salvage's own queue.

## Model runs (music, sound effects)

A `model-run` job names a recipe shipped in [recipes/](recipes) and a plan; it has no repository, setup or command of its own:

```json
{
  "schema": 1, "id": "skybreak-swings-2", "type": "model-run",
  "recipe": "stable-audio-open-sfx", "gpu": "L4",
  "plan": {"steps": 100, "guidance": 7, "seconds": 5,
           "cues": [{"id": "heavy-sword-swing", "prompt": "...", "seeds": [2311, 2312]}]},
  "max_minutes": 15, "max_units": 0.5, "max_rate": 3, "results_max_mb": 60
}
```

| Recipe | Makes | GPU | Tested (Oct 2026) |
|---|---|---|---|
| `stable-audio-open-sfx` | Sound effects up to 47 s, 44.1 kHz stereo: float original plus PCM16 preview per seed | L4 | 14 s per 5 s variant after about 80 s setup |
| `ace-step-music` | Instrumental music 10-240 s, 48 kHz stereo FLAC, optional overlap-crossfade loop candidate and wrap audition | A100 | 97 s per 180 s track after about 6 min setup |

- **Spend:** `max_units` is required. After the GPU is granted the runner reads the hourly rate, refuses an unknown rate or one above `max_rate`, and caps the runtime's life at whichever comes first: `max_minutes` + 20 or the unit ceiling. A job is a whole batch, so the model loads once per job.
- **Gated weights** (Stable Audio Open): the host's Hugging Face login turns into short-lived links for the exact files at the pinned revision ([stage_hf.py](scripts/stage_hf.py)); the runtime downloads them and checks each SHA-256. The token never leaves the host. The account must have accepted the model's licence on its page.
- **Results:** `receipt.json` lists every output with its hash, rate, channels, frames, peak and RMS, and the run fails if any planned output is missing, silent or not finite. A valid file is not a fitting one: in the first test a "heavy" swing came out light. Every batch gets a listening verdict per output before anything is imported ([studio-audio](../studio-audio/SKILL.md) owns preparation, import and listening).
- **No fallback:** a failed run never switches model, reruns or widens spend by itself. Look at the receipt and logs, then ask.
- Each recipe's `recipe.json` names its model, pinned revisions, licence note and what was tested. Check the licence for commercial use before outputs ship in a game.

## Speech and voice casting (experimental)

Four recipes read a game's exact lines in one character's voice, or design that voice from a description: `casting-qwen3-voicedesign`, `speech-chatterbox-en`, `speech-qwen3-base`, `speech-cosyvoice3`. They are pinned file by file and checked offline; none has been run by the kit yet. Which to use, and the rights rules, are in studio-audio's [open voices](../studio-audio/references/open-voices.md) and [character voices](../studio-audio/references/character-voices.md).

- **Inputs:** a speech job lists its reference under `inputs` (path, SHA-256, `private`). Validate with `--inputs FOLDER`; the runner packs only the listed files, sends them to the runtime only, and fails the job, pushing nothing, if any result is a byte copy of a private input.
- **One ceiling for a batch of jobs:** `budget: {"group": "...", "units": N}`. The service keeps a ledger per group, refuses a job once the group has spent N, caps each runtime at what is left and bills the runtime's whole life (setup included). Jobs in one group must name the same total.
- **Free route:** `"where": "attended"` with `"max_units": 0` runs in [notebooks/speech-audition.ipynb](notebooks/speech-audition.ipynb) on the person's own Colab runtime through [attended.sh](scripts/attended.sh). Nothing is priced or paid for; the service refuses these jobs. Free runtimes can disconnect: keep attended jobs short.

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
