---
name: studio-anim-from-video
description: Make a game animation for a non-human or rigid-block character from an AI video of that character, with video2rig (per-character joint reader plus a whole-clip fit), from start picture and move card through the reader, take scoring and bake to engine clips. Use when a creature or giant needs a move that hand keys or human mocap can't give, or when a video-to-rig clip looks wrong and you need to find which stage broke.
---

# Studio animation from video

> **Status: draft (2026-11-07).** Written from two giants (a 17-bone rigid-block puppet each) and about 25 generated clips. The [lessons log](references/lessons.md) has what was measured, with dates. Treat anything older than a few months as a hypothesis to re-test: video models change fast.

Inputs: the character's rig (or rigid blocks that can become a puppet skeleton), its final look, a move card per move, a spend cap and who must approve paid runs. Output: per move, a baked clip in the engine's format, a side-by-side preview (video on top, the real in-game character below), and one ledger row.

## The core law

**The reader learns the body, not the move. The fit reproduces what both views agree on, flaws included.** So every bad clip has one cause in one of four places, and each is fixed in a different way:

| Stage | Typical symptom | Fix it here, not later |
|---|---|---|
| Start picture and prompt | Giant turns 90 degrees into a punch, adds a guard or a stagger, arm crosses the divider | Move card, target in the side view, headroom, prompt template |
| Video | The two panels show different motions; limb colours swap; the creature drifts | Reroll or change model; `check` fails it in seconds |
| Reader | Points jump between limbs; a hidden limb reads badly; a prop hides hands | Retrain only when the body, rig, cameras or a hand-hiding prop change |
| Fit | Limbs spin or flip frame to frame while the readings look fine | The fit's first guess and limits (free, CPU) |

Find the stage before spending. The [exam](references/checks.md#exam) separates reader from fit without any video; `check` separates video from the rest.

## Pipeline

| Step | Once per | Output | Gate |
|---|---|---|---|
| 1. Puppet | character | A skeleton over the rigid parts with names video2rig recognises (Rigify-like: `upper_arm`, `forearm`, `thigh`, `shin`, sides `.L`/`.R`) | Bends at the same pivots as the game rig |
| 2. Rig export and start picture | character (and per prop) | `export_rig.py`, `render_start.py` (front and side in one frame, orthographic), `render_markers.py` colour suit | Biggest pose of every planned move fits both views with margin ([headroom](references/checks.md#headroom)) |
| 3. Reader | character, or a prop that hides hands | 3,000 random-pose renders (CPU is fine), DINOv2-small trained on a cloud GPU | Held-out error 2-4 px; exam passes |
| 4. Move card | move | Start pose, wind-up, hit, recover, end in rest; timings; what must NOT happen | Person approves the card before any video |
| 5. Video | take | Image-to-video from the colour-suit start picture, 720p, prompt from the template | Dry-run price; person's typed go and cap |
| 6. Check | take | `python -m video2rig check`: do the views tell one story | Body within 1.5% of height, else reroll, don't fit |
| 7. Read and fit | take | `run`, then a soft fit; add-on rules on for rigid blocks | Max joint turn per frame, pops, confidence ([gates](references/checks.md#take-gates)) |
| 8. Bake and preview | take | Blender Action to engine clip (per block); side-by-side film | Person watches the preview, not the numbers |
| 9. Shape | move | Trim the idle start, split at holds, mirror one-sided moves, layer upper body over procedural walks | Seams meet exactly; nothing ships until the person signs off |

Every take gets a ledger row, pass or fail ([take ledger](references/checks.md#take-ledger)).

## Defaults

- **Licence:** video2rig is AGPL-3.0. Clone it at run time at a pinned commit and call its commands. Never copy its code into a game repo or this kit, never run it as a service for others. Changes go in a separate add-on that calls its functions. The animations are yours.
- **Hardware:** reading and fitting run on the CPU (about 3 min to read a 5 s two-view clip). Rendering 3,000 training poses runs headless EEVEE on a CPU container (about 70 min; needs `libegl1 libgl1-mesa-dri`). Training needs a 12 GB card: an 8 GB laptop card overflows to a cloud GPU (an L4 took 1.35-1.8 compute units a reader).
- **Video model:** Seedance 2 was the baseline (confidence 0.60, 2 pops on a punch). Kling 2.6 read best so far (0.68, 0 pops) but its 5 s minimum leaves an idle start to trim. Wan 2.2 scrambles limb colours. Compare on one move with the same reader before switching ([lessons](references/lessons.md)).
- **Directions in the side view.** "Punch straight ahead" means at the front camera, and every model turned the giant 90 degrees to show the punch in profile. Throws worked because the prop beside the giant gave a sideways direction. Give each move a target or prop placed where the side view shows it.
- **Prop readers only when the prop hides hands.** A 5 m chunk held overhead needed a reader trained with the chunk; a small rock reader read worse than the plain one.
- **Rigid blocks show roll.** On skinned bodies a wrong forearm roll is soft; on a block it is a spun box. Turn on the add-on's `continuous_start` and `limb_plane_start`, and limit roll (not bend) on elbows and knees (`twist_deg`).
- **Fit the whole clip, then cut.** Halves fitted on their own disagreed by 4 m at a hand. Splitting a move never needs a new reader.
- **One reader reads every move.** Retrain only when the mesh, rig, start cameras or a hand-hiding prop change. A new mesh on the same rig (same parts, pivots and lengths) needs a new reader and start picture, but already baked clips carry over, because they move the parts, not the mesh.
- **Walks, runs and idles stay procedural.** Video clips layer on top (upper body, or whole body for one-shots). Make shared moves once and copy them across characters with the same rig; mirror left-hand moves.
- **Tame, then judge.** Video models overact (a stagger too big for combat, the body swinging 130 degrees into a punch). Keep a share of whole-body turn per group (hips 15%, spine 30%, chest 45%) rather than re-prompting forever, and say in the ledger that it was tamed.

## Spend

- Say the price before every paid call and get the person's typed go with a cap. Reader training is a separate go.
- Budget about 7 clips per usable move (an outside implementation of the same method published 58% of captured clips passing). After six failed takes on one move, stop and bring it back to the person: change the card, the model or drop the move.
- Free steps first: re-fitting, limits, first-guess changes, single-view reads and trims cost nothing. Exhaust them before a new video or a new reader.

## Also read

- [Checks](references/checks.md): take gates, the ledger, the exam, headroom.
- [Lessons](references/lessons.md): dated results, newest first.
- [Anymove notes](references/anymove.md): a second implementation of the same method (Apache-2.0) and what we took from it.
- [Animation](../studio-animation/SKILL.md) for runtime block rigs and procedural gaits the clips layer on; [cloudrun](../studio-cloudrun/SKILL.md) for the reader training job; [review](../studio-review/SKILL.md) before anything goes in a build.
