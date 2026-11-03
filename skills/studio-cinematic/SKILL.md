---
name: studio-cinematic
description: Direct a game trailer or story cinematic made with video-generation models, from script and engine blockout through look stills, camera-only reference clips and director's briefs to chunked renders and the edit, with each paid run run through studio-video-gen.
---

# Studio cinematic

> **Status: draft.** Written during one 50-60 s trailer (Nov 2026) and updated as it goes. The [lessons log](references/lessons.md) records what was measured, with dates. Treat anything there older than a few months as a hypothesis to re-test, because these models change fast.

Inputs: the person's story idea and what the film must sell (for a game trailer, usually how playing feels), approved character concepts, the engine scene or map, a spend cap, and who must approve paid runs.

## The core law

A video model with a reference video is a **photocopier for timing and pose**. It copies the reference's camera, cuts, timing, holds and every body pose, flaws included: stiff limbs, an inverted elbow, feet sinking into the ground, a pause in a run. It does not re-ease motion. So decide, per shot, what the reference is allowed to say. Read [method](references/method.md) first.

## Pipeline

| Step | Output | Gate |
|---|---|---|
| 1. Script | Beats, length target, what each beat shows of the game | Person approves; script changes are cheapest here |
| 1b. Board / animatic | Timed boards with scratch audio | Comprehension check: a newcomer can say why each beat happens. Before any paid render |
| 2. Engine blockout | A rendered previs from the real map and characters (or primitives), one flat colour per character, cut on beats, at final speed | Person watches it; [QA gate](references/reference-video.md#qa-gate) |
| 3. Pillar twin | The same blockout with every character as a plain coloured pillar of true height: the **camera-only** reference | Same camera, cuts and timing as step 2 |
| 4. Identity pack | Per character: approved concept art + a three-quarter turnaround of the game model | Concepts are the owner's approved ones |
| 5. Look round | A few key frames per candidate look, painted from clay frames plus the identity pack, scale stated hard per still | Person shortlists **on stills**, then decides on a short **video test** of the shortlist |
| 6. Model test | One short shot on two or three models, same inputs | Person picks the model and the method |
| 7. Shot plan | Per shot: grade (pillars / clay / first-frame / free), director's brief, chunk, a look still per chunk, identity pack for everyone visible | Costed in generated seconds (chunks overlap, 4 s minimum) with `studio-video-gen estimate` |
| 8. Render | Chunks of 4-9 s, each a jobs entry | Person's typed go with a cap, per run |
| 9. Edit | Picture lock, then voices, effects and music (generated or licence-checked free tracks, hits synced to the cut), end card | Person approves the cut; nothing is published without a go |

Change the method only on evidence: run the cheapest test that answers the question (one 6 s shot), show the person a side-by-side, let them pick.

## Defaults that won (see the log)

- **Camera-only pillars + director's brief** is the default for every shot. The pillars clip fixes camera, placement, scale and cut timing; the brief describes the action; the identity pack carries who each character is. The model performs the bodies with real weight.
- Use the **full clay** only where an exact pose or contact is the point, and only after the clay's motion passes the QA gate. A flawed source animation is a reason to use pillars, not to hope.
- Keep both twins of every shot so a chunk can switch method without a re-block.
- **Shortlist looks on stills** (cheap), then **decide on a video test**. A live-action look won on stills and was rejected on video: people looked real and characters drifted from their concepts. For a game with designed characters, an animated look with close concept adherence is the safer default.
- Prompts that say "game cinematic" get the game's own render back; describe the target look itself.
- **Stills on a subscription tool first.** Use the host's built-in image tool (no per-image cost) for look rounds and per-chunk stills; a paid image API only when a specific model is needed. The video provider is for video. Each generator has one house style: four "different" directions from one tool converge, so compare tools when the look is open.
- **One paired reference per character** (concept and game-model sheet side by side in one image) when a tool caps reference images (one took at most 5).
- Seedance 2.5 (via Runway) beat Kling 4 and Aleph 2 on the same inputs; Kling first-frame was a usable second.

## Spend

Every paid call goes through [studio-video-gen](../studio-video-gen/SKILL.md) with the person's own go message quoted. Right before each paid call, re-read the person's thread for anything newer than the go: a correction that arrives after a go overrides it. Ask for a go per run with its estimate and cap ("go grab test, cap $3"). A plan doc keeps a cost ladder: stills, one-shot test, model test, film, retakes. Log every run.

References: [method](references/method.md), [reference video spec](references/reference-video.md), [prompt anatomy](references/prompts.md), [lessons log](references/lessons.md).

Return: the current cut or test clip with a side-by-side when comparing, the shot plan, spend so far against the cap, and one question for the person.
