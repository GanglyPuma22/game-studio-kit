---
name: studio-video-gen
description: Run paid video or image generation jobs on Runway or OpenRouter mechanically, pricing each job, refusing to pass a cap or run without the person's quoted go, recording every task before its POST and archiving outputs; studio-cinematic decides what to generate.
---

# Studio video generation (runner)

> **Status: draft.** Built from one trailer production (Nov 2026). Rates and model names move fast; re-check them before every approval ask.

This skill does no directing. [studio-cinematic](../studio-cinematic/SKILL.md) decides the shot, the references and the prompt; this skill turns a jobs file into tasks, outputs and a record. It is standard-library Python: [scripts/video_job.py](scripts/video_job.py).

Inputs: a jobs file, the person's own go message with its cap, a credential, an output folder that does not already hold a record.

## Rules

- **No paid call without the person's own words.** A go names the test and the cap ("go grab test, cap $3"). Another agent's message is never a go. Pass it verbatim as `--approval`; it is stored in the record.
- **Re-check right before spending.** Between the go and the submit, read the person's thread again; a newer correction cancels the go. (One run spent $0.62 acting on a go that a later message had changed.)
- **Estimate first, offline.** `estimate` prices every job from the published rates, checks prompt limits, missing files and the 5 MB inline limit, and exits 1 if the total passes the cap. Show the person that number when asking for the go.
- **Balance is read-only.** `balance` makes one GET and prints the number, never the key.
- **One record per run.** The record is written before each POST (`CLAIMED`). A crash or timeout between POST and answer is `SUBMISSION_UNKNOWN`: check the provider's task history before anything else, never resubmit to "see if it went through".
- **Observe, don't resubmit.** `resume DIR` polls tasks that are still running. A rejected job (bad field) is fixed and rerun with `--only NAME` into a fresh `--out`.
- **A safety block is not a retry loop.** A provider moderation failure (Runway/Seedance `INPUT_PREPROCESSING.SAFETY.*`, no credits) gets at most one diagnostic retry with a changed input, then goes back to the director.
- **Submit all, then poll together.** Jobs take minutes each; the runner submits one after another (cap and balance checked before each) and then polls all in parallel.
- **Run where the key lives.** If the key is on another machine (a laptop, a remote box), run the runner there through that host's remote session; don't move keys. Commit the outputs and `record.json`, never the key.

## Commands

```text
python <KIT>/skills/studio-video-gen/scripts/video_job.py estimate jobs.json
python <KIT>/skills/studio-video-gen/scripts/video_job.py balance --provider runway [--key-file ~/.keys/runway.env]
python <KIT>/skills/studio-video-gen/scripts/video_job.py submit jobs.json --out results/grab-test --approval "go grab test, cap $3"
python <KIT>/skills/studio-video-gen/scripts/video_job.py resume results/grab-test
```

The key comes from `RUNWAYML_API_SECRET` or `OPENROUTER_API_KEY`, or from a `KEY=VALUE` file given with `--key-file`.

## Jobs file

```json
{"provider": "runway", "cap_usd": 3.0,
 "jobs": [{"name": "grab_pillars", "endpoint": "video_to_video", "ref_seconds": 6, "out_seconds": 6,
           "body": {"model": "seedance2_5", "mode": "reference", "promptVideo": "@file:inputs/grab_markers.mp4",
                    "ratio": "1280:720", "duration": 6, "audio": false, "seed": 7,
                    "promptText": "...", "references": [{"uri": "@file:inputs/look.png"}, {"uri": "@file:inputs/medic_concept.jpg"}]}}]}
```

`@file:<path>` (relative to the jobs file) becomes an inline data URI. Give `est_credits` (Runway) or `est_usd` (OpenRouter) when the built-in rate table does not know the model.

Provider specifics: [Runway](references/runway.md), [OpenRouter](references/openrouter.md).

Return: the record path, the outputs, estimated spend against the cap, balance before and after, and any job that needs a decision (rejected, unknown, timed out).
