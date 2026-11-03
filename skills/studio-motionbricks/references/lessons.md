# MotionBricks lessons (newest first)

## 2026-11-03, four parallel batches on a giant box rig (punch, bite, two ability kits)
- **Generations ease in and out.** Over a 0.18-0.3 s game phase that reads as a late start or a hold. Trim each segment to where the limb moves, and ease the recovery's sampling (for example u^0.7).
- **Retime with keys.** Retime piecewise with (phase u, source frame) keys so game events land on exact frames, such as a stomp's touchdown at u = 1.
- **Close gaps with a decaying residual,** not a lerp onto the clip. While a phase can hit, the game's hand or head wins exactly; the clip owns the wind-up, recovery and trunk.
- **Aimed attacks need relative blending.** The game aims anywhere (a punch down at a grounded target), so an absolute clip hand, palm or elbow pole never matches. Take the residual from the real reach end, let the fist only roll about the forearm, and push the elbow pole sideways off the reach line.
- **A very short game recovery (0.1 s):** play the drawn settle on the free arm past the gameplay phase, fading out.
- **Low targets can't come from a standing clip.** Weight the clip by the aim height known at wind-up (live head height pops), and fade every rig change the clip makes by the same weight.
- **Bulky bodies.** SOMA hangs its hands by slim hips. Offset clip hands to the rig's rest width, clamp elbows outward, and cap how far back the arms go.
- **Author key-pose hands in the chest frame.** Hands authored in the body frame missed by about a quarter of the arm once the chest bent.
- **Twist sign** differed between the pose authoring and the bake. Check it on stills.
- **Wrists.** Copying the clip's full hand turn broke the rig's hand limits. Use a roll-only or eased wrist turn relative to the forearm, and ease it in and out so it doesn't snap at the clip's ends.
- **Feet drift.** MotionBricks lets planted feet slide. Remove support-foot drift, hold a stomping foot's x/z until lift-off, and freeze it where it lands. Feed the lifted foot to the rig's planting and leave the planted one to it.
- **A held arm that is not holding.** A bite marked an arm as held, so the game owned the hand and the hips drove the pelvis into it. Mark it free.
- **Clients lack host-only flags.** Time clips from synced timers only.
- **Score before rendering.** A no-render checker pass takes about a minute; render only the final takes. Pick the compare camera per move.
- **Parallel agents on one rig file.** Give each batch its own fenced, commented block (conflicts were all "keep both"), its own scratch folder, and check that each worktree starts on the intended branch.
- **Not covered yet:** quadrupeds (SOMA is human), locomotion, and a low crouching bite.

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
