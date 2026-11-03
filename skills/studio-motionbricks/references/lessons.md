# MotionBricks lessons (newest first)

## 2026-11-03, first production use (a giant grab on a box rig; a humanoid hard landing)
Each item cost real time once.

- **Sample clips are evaluation-only.** The first grab seeded its rest pose and context from a sample idle BVH and had to be re-made from a CC0 idle. Smart Primitive documents point at the same clips, so their target poses are off-limits too. Check sources before generating, not before merging.
- **CPU Warp arrays are views.** `out.poses.numpy()` on CPU shares memory with the next generation, so every frame came out as the rest pose. `.copy()` each output.
- **Target frames are not waypoints.** Two or more target frames only set arrival speed. Chain generations for a path.
- **0.8 s minimum per generation.** Short beats (a 0.2 s reach, an absorb) need a longer generation that is left early, or a piecewise retime to the game's phase lengths after baking.
- **Fast or falling contexts overshoot the lean.** Landing takes pitched the torso 65-130°, some into a dive. A 24-take sweep over fall speed, run speed, tokens and target distance took under a minute; ranking by peak lean found a clean absorb-and-push-off.
- **The rest-alignment swing goes from the receiving rig's direction to the source's.** It was reversed at first. With near-T-pose rests the error looked plausible in stills but was double the rest difference.
- **Shared vectors got mutated.** `np.asarray` returned the caller's direction vector and in-place edits leaned the whole body. Copy with `np.array`.
- **Check the palm sign on the rest pose.** For the right hand, palm = cross(index - pinky, fingers). The first sign was flipped, so every "palm down" pose faced up. The idle palm should face the thigh.
- **A formula neck nod read wrong.** Leave the head to the trunk bend unless stills show a need.
- **Driving every bone can break props.** A landing clip that drove the arms swung held blades into the floor. Filtering the arms out, so they keep the run, fixed it.
- **Godot sampling returned the rest pose.** In a `SceneTree` script, wait one `process_frame` after adding the scene. Then seek, `advance(0)`, and `force_update_all_bone_transforms()` before reading bone poses.
- **Camera side matters.** The first compare camera hid the very arm being fixed. Choose the camera from the moving limb.
- **Look and gameplay can be tangled.** The held character's position is server state, not animation. Moving it went to the owner as a decision, and the owner chose a chest-height hold.
- **What worked:** a human figure with palm arrows for key poses, chained generations, rig-free baking, a phase-sampled box rig, per-body fitting at load, and off-vs-on renders behind a cosmetic setting. The owner approved the grab on the first in-game render.
