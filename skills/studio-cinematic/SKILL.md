---
name: studio-cinematic
description: Direct a game trailer or story cinematic made with video-generation models, from script and engine blockout with cameras flown by simulated real rigs, through character sheets and painted first and last frames, to shot-by-shot renders and an edit with fewer cuts, with each paid run run through studio-video-gen.
---

# Studio cinematic

> **Status: draft, v2 (Nov 9 2026).** Written during one 60-85 s trailer and updated as it goes. v2 adds [flown camera rigs](references/camera-rigs.md), [editing rules](references/editing.md) and the [shot recipe](references/shot-recipe.md), which replaced chunked renders. The [lessons log](references/lessons.md) records what was measured, with dates. Treat anything there older than a few months as a hypothesis to re-test, because these models change fast. The [playbook](references/playbook.md) and [method](references/method.md) hold the earlier chunk-era findings; where they disagree with v2, v2 wins.

Inputs: the person's story idea and what the film must sell (for a game trailer, usually how playing feels), approved character concepts, the engine scene or map, a spend cap, and who must approve paid runs.

## The core law

A video model copies what its inputs say, flaws included. With a reference video it is a **photocopier for timing and pose**: camera, cuts, holds, stiff limbs, sinking feet. With painted frames it is a photocopier for the frames: if the two frames disagree, or show the reverse of the action, the model compromises by barely moving. So every input gets one job, and the inputs must agree. Most failed shots were input faults, not model limits.

## Pipeline

| Step | Output | Gate |
|---|---|---|
| 1. Script | Beats, length target, what each beat shows of the game | Person approves; script changes are cheapest here |
| 1b. Board / animatic | Timed boards with scratch audio | Comprehension check: a newcomer can say why each beat happens. Before any paid render |
| 2. Engine blockout | A rendered clay previs from the real map and characters, one flat colour per character, at final speed | Person watches it; [QA gate](references/reference-video.md#qa-gate) |
| 3. Camera pass | Every moving camera flown by a simulated rig (film drone, FPV chase, crane/dolly, handheld) within real limits; the fastest-cut runs merged into single moves; close cameras guarded out of walls. [Camera rigs](references/camera-rigs.md), [editing](references/editing.md) | Person watches the whole re-flown clay film with its cut list. Free |
| 4. Identity | One character sheet per character (shape from the game, look from the approved concept), the prompt's words written from it; one approved style master frame | Person approves each sheet; no contradicting concept art left in the references |
| 5. Shot list | Per shot: one camera, one action, 3-5 s, its spec and pass line ([shot recipe](references/shot-recipe.md)); long moves split at their anchors with matched frames | Costed per shot |
| 6. Frames | First and last frame per shot, painted together in one session from that shot's layout frames | The seven-point pre-run check passes |
| 7. Render | One generation per shot, once | The person's typed go with a cap for the batch; at most two takes per shot |
| 8. Vet and clean | QA at 6-8 fps against the pass line, shot card verdict; free local stray removal ([cleanup](references/cleanup.md)) or a retake | Retake only failing shots, one named input changed |
| 9. Edit | Trim handles, cut on the editing rules, per-shot colour match then one grade, then voices, effects and music (hits synced to the cut), end card | Person approves the cut; nothing is published without a go |

Change the method only on evidence: run the cheapest test that answers the question (one 3-5 s shot), change one thing, show the person a side-by-side, let them pick.

## Defaults

- **Fly, don't draw.** Every moving camera is flown by a rig ([camera rigs](references/camera-rigs.md)). Check a move's least flying time against the story time before drawing it; hold the story or shorten the move, never speed it up. Anchor long moves on story beats. One prime lens per move.
- **Cut less** ([editing](references/editing.md)): one beat per shot, move instead of cutting, same frame spot across a cut, cut on motion, wide before close.
- **One shot, one action** ([shot recipe](references/shot-recipe.md)): one camera, 3-5 s with handles, contact inside a shot or exactly on a cut, a spec and a pre-run check before every paid shot, a shot card after.
- **Identity from sheets.** One sheet per character, the same refs in every shot, prompt words written from the sheet. Inputs that disagree (a blue board, an orange prompt, a concept with an extra prop) make the model pick a different source per shot.
- **The clay pass stages, it doesn't drive.** Paint keyframes from it; don't send clay with characters to the model unless an exact pose is the point and its animation passed QA. Camera-heavy shots send a camera-only blob guide with the frames; locked shots send frames only ([camera rigs](references/camera-rigs.md#before-the-paid-renders); A/B pending).
- **Thin props** (cables): name the attachment point, route each line by start and end, give the prop its own reference sheet, **cut on every release**; never draw the props over the render yourself ([playbook](references/playbook.md#thin-props-cables-lines)).
- **Pin hands and limbs** at every contact beat: which hand acts, where the others are, "no other hand appears".
- **Never put a restraint image in the references** (a still of a giant holding a person): provider moderation blocks the job whatever the text says.
- **Cleanup** stray lines locally and for free ([cleanup](references/cleanup.md)); re-render for anatomy errors.
- **Look:** a stylized 3D feature look beat live-action on character adherence; judge looks on a video test, not stills alone. Prompts describe the target look; "game cinematic" gets the game's own render back. Keep the inspiring show's terms out of prompts.

## Spend

Every paid call goes through [studio-video-gen](../studio-video-gen/SKILL.md) with the person's own go message quoted. Right before each paid call, re-read the person's thread for anything newer than the go: a correction that arrives after a go overrides it. Ask for one go with an estimate and cap for a batch of shots ("go shots 4-6, cap $3"), not a go per test. A plan doc keeps a cost ladder: stills, one-shot test, model test, film, retakes. Log every run. (The first film's Kling 4 runs on fal went through the project's own runner; fal is not yet in studio-video-gen.)

References: [camera rigs](references/camera-rigs.md) (with [scripts/camera_rigs/](scripts/camera_rigs/)), [editing](references/editing.md), [shot recipe](references/shot-recipe.md), [cleanup](references/cleanup.md), [reference video spec](references/reference-video.md), [prompt anatomy](references/prompts.md), [lessons log](references/lessons.md); chunk-era: [playbook](references/playbook.md), [method](references/method.md).

Return: the current cut or test clip with a side-by-side when comparing, the shot list with each shot's status, spend so far against the cap, and one question for the person. Keep experiment names and method detail out of what the person sees: clips are "shot N, take 1/2".
