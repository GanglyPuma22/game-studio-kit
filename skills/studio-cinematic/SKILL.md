---
name: studio-cinematic
description: Direct a game trailer or story cinematic made with video-generation models, from script and engine blockout through look stills, camera-only reference clips and director's briefs to chunked renders and the edit, with each paid run run through studio-video-gen.
---

# Studio cinematic

> **Status: draft.** Written during one 60-75 s trailer (Nov 2026) and updated as it goes. The [lessons log](references/lessons.md) records what was measured, with dates. Treat anything there older than a few months as a hypothesis to re-test, because these models change fast.

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
| 8. Render | Chunks of 4-9 s, each a jobs entry. Hard chunks first, then film order | Dry run priced; person's typed go per chunk, capped at the dry-run price |
| 8b. Vet and clean | [Vetting checklist](references/playbook.md#vetting-checklist-every-returned-clip), then free local stray removal ([cleanup](references/cleanup.md)) or a re-render | Every patched frame zoom-checked; before/after at 1x and 0.5x; person accepts the chunk |
| 9. Edit | Picture lock, then voices, effects and music (generated or licence-checked free tracks, hits synced to the cut), end card | Person approves the cut; nothing is published without a go |

Change the method only on evidence: run the cheapest test that answers the question (one 6 s shot), show the person a side-by-side, let them pick.

## Defaults (see the [playbook](references/playbook.md))

- **Layout:** camera-only markers with the v2 rules is the default (it beat clay v2: identity held, giant detail kept, smoother motion, no stray strands). Clay only for exact-pose shots. Keep a clay and a markers twin of every shot.
- **Thin props** (cables): draw them in the layout, give the prop its own reference sheet, route each line by start and end in the brief with negatives; otherwise the model invents the familiar trope. Name the attachment point, allow a steadying hand, and **cut on every release**. Never draw the props over the render yourself.
- **Pin hands and limbs** at every contact beat: which hand acts, where the others are, "no other hand appears". Extra limbs need a re-render.
- **Cleanup:** remove stray lines locally and for free (hand-keyed masks, fill from nearby frames of the same shot, rigid patches over straight structure); see [cleanup](references/cleanup.md). Re-render instead for anatomy errors, or for a line over detailed scenery with no clean frame behind it (over plain sky or snow, the neighbour average works).
- **Order:** qualify the hard chunks first, then render in film order so finished segments build up; a chunk is done only when fully qualified.
- **v2 rules in every brief:** one character per shot after a cut, framed large; name who is and isn't in the shot; the same signature traits sentence per character; distinct proxy colours; exact limb counts; lines only while attached and the shooter is on screen, with the release as its own beat.
- **No cut within 0.75 s of a chunk edge**; Seedance drops them.
- **Use pillars, not the clay, where the source animation is flawed.** The model copies it.
- **Looks:** one still per chunk from its own layout frame, made on the host's subscription image tool, with paired references per character, cropped to 2.4:1. Shortlist on stills, decide on a video test. A stylized 3D feature look beat live-action on character adherence. Never put a restraint image in the references.
- **Model:** Seedance 2.5 (via Runway) beat Kling 4 and Aleph 2; Aleph only patches a single shot between cuts.
- **Vet every clip** with the [checklist](references/playbook.md#vetting-checklist-every-returned-clip) before it goes in the cut. **Re-render only the chunks a change touches.**
- Prompts describe the target look; "game cinematic" gets the game's own render back. Keep the inspiring show's terms out of prompts.

## Spend

Every paid call goes through [studio-video-gen](../studio-video-gen/SKILL.md) with the person's own go message quoted. Right before each paid call, re-read the person's thread for anything newer than the go: a correction that arrives after a go overrides it. Ask for a go per run with its estimate and cap ("go grab test, cap $3"). A plan doc keeps a cost ladder: stills, one-shot test, model test, film, retakes. Log every run.

References: [playbook](references/playbook.md), [method](references/method.md), [cleanup](references/cleanup.md), [reference video spec](references/reference-video.md), [prompt anatomy](references/prompts.md), [lessons log](references/lessons.md).

Return: the current cut or test clip with a side-by-side when comparing, the shot plan, spend so far against the cap, and one question for the person.
