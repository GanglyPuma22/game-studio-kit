# Colab models route

Open models on a Colab GPU, run by [studio-cloudrun](../../studio-cloudrun/SKILL.md) as `model-run` jobs. Tested in October 2026 by a person listening: comparable to the paid routes for the cues tried.

| Need | Recipe | Notes |
|---|---|---|
| Sound effect, foley, short one-shot (up to 47 s) | `stable-audio-open-sfx` | 44.1 kHz stereo. Float original (peaks can exceed full scale, kept unclipped) plus a PCM16 preview at -1 dBFS peak: listen and import from the preview. Gated model: the account behind the service host must accept the licence on the model page. |
| Instrumental music bed or loop (10-240 s) | `ace-step-music` | 48 kHz stereo FLAC original. `loop_crossfade_seconds` adds an overlap-crossfade loop candidate (shorter by that many seconds) and a 24 s wrap audition. A100 only. |

Not covered: speech and character voices (separate capability, not tried), ambience beds longer than the limits above, and anything needing lyrics.

## Steps

1. Write the plan: one cue per sound, a `prompt` (or `caption` for music) that names weight, material, distance and what to leave out, and two or more seeds per cue so a weak take can be dropped.
2. Validate and print the plan: `python <KIT>/scripts/studio.py cloudrun plan --job job.json`. State the outputs, GPU, `max_units` and expected cost (see each `recipe.json` `tested`) and get the person's go.
3. Queue it or run it now (studio-cloudrun). Results arrive on `studio-results/<id>` with `receipt.json`.
4. Listen to every output against its brief and record a verdict per output (fits, wrong weight, wrong material, artefact). A file that passes the receipt checks can still fail its brief: the first test's "heavy" sword swing sounded light.
5. Prepare and import only accepted outputs with `studio audio prepare`, keeping originals and the receipt; listen in game.

## Rules

- No fallback: if a run fails, do not switch model, rerun or raise the ceiling without asking. The receipt and logs say what happened.
- Keep the model, revision, seed, prompt and settings with every imported file (the receipt has them).
- Check each model's licence for commercial use before shipping (`recipe.json` notes it).
