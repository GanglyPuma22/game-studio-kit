---
name: film-director
description: Direct a short animated or AI-generated film (a cinematic short, trailer or hype piece) from idea to finished cut: story and purpose, layout, flown cameras, identity sheets, shot-by-shot generation or direct render, edit and sound, with approval gates and a spend cap. Use film-camera and film-shots for the detailed steps.
---

# Film director

This pack is engine- and product-agnostic. It works for a game's cinematic short, a trailer or a social clip, from a 3D layout in any engine or Blender. Keep the `film-kit` folder together: these three skills link to each other.

Inputs: the idea and what the film is **for**, approved character designs, a 3D scene or map to lay out in, a spend cap, and who approves paid runs.

## The core law

A generator copies what its inputs say, flaws included. With a guide clip it copies camera, timing and every pose. With painted frames it copies the frames, and if two frames disagree it barely moves. So every input gets one job, the inputs must agree, and you fix the cheap stage (layout, frames) before the expensive one.

## Pipeline

| Step | Output | Gate |
|---|---|---|
| 1. Purpose and story | What the film is for, beats, length, the moments people will clip and share ([story](references/story.md)) | The person approves; changes are cheapest here |
| 2. Layout | A timed 3D previs of the whole film at final speed, from the real scene and characters | The person watches it |
| 3. Camera | Every moving camera flown by a simulated rig, fewer cuts (film-camera) | The person watches the re-flown layout with its cut list |
| 4. Identity | One sheet per character, matching its current canonical design, plus one style frame | The person approves each |
| 5. Shots | Pieces cut at key events, a spec per shot, frames painted in pairs (film-shots) | Seven-point pre-run check; the person reviews every frame |
| 6. Render | One generation per shot, or a direct render from the layout | One typed go with a cap for the batch |
| 7. Vet and fix | Verdict per shot, retakes of failures only, free cleanup | The person accepts the shots |
| 8. Edit and sound | Cut, grade, voices, effects, music (hits on the cut), end card; cutdowns for short-form | The person approves; nothing is published without a go |

Change the method only on evidence: run the cheapest test that answers the question (one 3-5 s shot), change one thing at a time, show a side-by-side, and let the person pick.

## Direct render as an option

When the layout can be rendered well directly (Blender with good lighting and materials, or a strong engine render), a shot can skip video generation. The camera, timing and poses then come through exactly, and there's no per-shot fee. Compare on one already-approved shot: same camera and timing, rendered both ways.

## Working with the person

- Make one progress page: the stitched film so far at the top, then one row per shot with status, current clip and cost.
- Send one short message per batch. Name clips "shot N, take 1/2", with no experiment names. Method detail goes in the internal log unless asked.
- Get one estimate and one typed go with a cap for a batch, not a go per test. Re-read for corrections right before every paid call: a correction after a go overrides it.
- Approved shots are frozen. Re-render only what a change touches, and say when a design change un-approves shots.

Log what each test taught, with date and cost, in [lessons](references/lessons.md), and promote a lesson into a skill only after the person has picked it.

Return: the current cut (or the test with a side-by-side), the shot table with statuses, spend against the cap, and one question.
