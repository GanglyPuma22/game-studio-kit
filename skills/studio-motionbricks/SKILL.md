---
name: studio-motionbricks
description: Make or rework humanoid-ish game animation by authoring a few key poses, letting NVIDIA MotionBricks fill the motion between them on CPU, and baking the result into a rig-free clip the engine fits to each body, with licence checks, take ranking and in-game off/on review.
---

# Studio MotionBricks

Use this skill when a move looks wrong between its poses (an elbow that flips, a palm facing the wrong way, a body that teleports) and a believable human in-between would fix it. Typical work: a grab, a punch, a hard landing into a run, or a recovery. It works for humanoid characters and for box/blockout rigs whose limbs read like a human's. It does not cover quadrupeds; MotionBricks ships a human (SOMA) model and a humanoid robot model only.

Inputs: the move's gameplay phases and their timings, the target rig (bone names, rest pose, or the block rig's terms), CC0 or owned source poses, and where the review will happen. Outputs:
- the key poses as code
- the generated frames
- a baked rig-free clip the game reads, behind an off/on setting
- off-vs-on renders from the game

Read [method](references/method.md) before the first generation. It has setup, the pipeline and the review loop. Then read [lessons](references/lessons.md), the friction log, so you don't repeat it.

## Rules
- **Licences first.** The code is Apache-2.0. The model is under the NVIDIA Open Model Agreement (commercial use allowed; NVIDIA claims no ownership of outputs). The repository's `assets/motions/` clips are under an evaluation-only licence, and its Smart Primitive documents point at those clips. Neither may seed anything that ships. Use poses you author, or CC0/owned clips moved onto SOMA with [rig_map.py](scripts/rig_map.py). Record each input's source in the clip file.
- **Gameplay stays the game's.** The baked clip changes the look only. Sample it by the server's own phase timer, and keep hit volumes, reach and timings where they were. If a look change needs gameplay state to move (for example, where a held character sits), put that to the owner as a decision.
- **Ship behind a setting.** Add a local, cosmetic, off-by-default setting (no network bytes) until the owner has seen the in-game off-vs-on render.
- **Look before you claim.** Check stills of the key poses, a stick-figure video of the generation, and the in-game render. Numbers such as lean, crouch depth and touchdown frame rank takes; they don't approve one.

## Helpers
- [mb_cpu.py](scripts/mb_cpu.py) runs MotionBricks without a GPU. It replaces TensorRT with ONNX Runtime and runs Warp on CPU, at about 60 ms per generation on 4 cores.
- [soma_pose.py](scripts/soma_pose.py) authors poses: forward kinematics, world-axis turns, two-bone IK with an explicit elbow/knee direction, hand aim (fingers + palm), and finger curl.
- [rig_map.py](scripts/rig_map.py) moves poses between SOMA and a game skeleton, both ways (rest-direction swing, then world turn from rest).
- [dump_skeleton.gd](scripts/dump_skeleton.gd) exports a Godot model's rest pose and clips as world-space bone frames.
- [render.py](scripts/render.py) draws two-view stick-figure stills and videos with a palm arrow.
- [retime.py](scripts/retime.py) retimes generated segments piecewise to gameplay phase lengths.

Hand the in-game integration to [Godot](../studio-godot/SKILL.md), and the verdict to [review](../studio-review/SKILL.md). For box-first rigs, also read [studio-animation](../studio-animation/SKILL.md)'s runtime block rig references: the baked clip replaces a hand-posed move, while the rig's planting, checker and hitbox rules still apply.
