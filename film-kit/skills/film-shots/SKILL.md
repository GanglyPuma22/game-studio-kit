---
name: film-shots
description: Turn a laid-out film into AI-generated video shot by shot: one camera and one action per 3-5 s generation, painted first and last frames, one sheet per character, a camera-only guide for camera-heavy shots, a written spec and pre-run check before every paid run, then vetting, retakes and the edit.
---

# Film shots

Video models plan one continuous scene and honour one or two actions per shot. Long multi-shot passes reorder, merge and drop beats, and untimed middle frames make the model park on them. So the paid unit is **one shot**: one camera setup, 3-5 s, one action that runs forward from its first frame to its last. Read the [shot recipe](references/shot-recipe.md) first.

Inputs: a timed layout of the film with its cameras (see film-camera), the shot list, one approved sheet per character, one approved style frame, a provider account, a spend cap, and who approves paid runs.

## Steps

1. **Cut the film into pieces at key events**, so every key moment is a join frame. Long moves split at their anchors, with matched frames at the joins.
2. **Write a spec per shot** before building it: camera, the one action, what the first and last frames show, who is on screen, guide clip or none and why, and the pass line.
3. **Fix the layout until it shows the action**, then **paint both frames in one session** from it, the last painted from the first.
4. **Choose the inputs** per [inputs](references/inputs.md): frames plus a camera-only blob guide for camera-heavy shots, frames only for locked shots, sheets and the style frame always.
5. **Write the prompt from the spec** using the fixed blocks.
6. **Pre-run check**: the seven points in the recipe, read by a second reviewer from the spec and frames alone.
7. **Put all frames in front of the person**, then ask for **one typed go with a cap** for the batch. Re-read for newer instructions right before every paid call.
8. **Run each shot once and vet it** ([vetting](references/vetting.md)). Retake only the failures, at most two takes, one named input changed each time.
9. **Edit**: trim the handles, cut, match colour per shot, grade once, then sound.

## Defaults (Nov 2026; re-test when models change)

- Kling 4 (via fal, 720p) with first and last frames, plus a guide clip on camera-heavy shots. Seedance 2.5 matched it at 3x the price.
- Clips are silent; sound is built in the edit.
- Keep a shot card per shot beside its job file, so every result traces back to its exact inputs.
- What the person sees: "shot N, take 1/2", one progress page, one short message per batch, no experiment names.

Return: the cut so far, a status row per shot (frames, check, take, verdict, cost), spend against the cap, and one question for the person.
