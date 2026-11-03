# MotionBricks method

## What the model does
MotionBricks (github.com/NVlabs/motionbricks) generates motion on the SOMA skeleton: 30 body joints, 77 with fingers, Y up, metres, facing +Z. One generation takes:
- 4 context poses: the last frames already played
- 1-4 target poses

It outputs 6-16 tokens of 4 frames each at 30 Hz, so 0.8-2.1 s, and endpoint correction lands exactly on the target. Several target frames set the arrival velocity window. They are not waypoints. To pass through several poses, chain generations, each starting from the last 4 frames of the one before.

## Setup on a CPU box
```sh
GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/NVlabs/motionbricks.git mb
cd mb   # fetch only the LFS files you need; some git proxies refuse LFS
for f in motionbricks/assets/onnx/soma/mmm_v6_soma_fp32.onnx \
         motionbricks/assets/human/soma_base_skel_minimal_no_root.usd; do
  curl -sSfL -o "$f" "https://media.githubusercontent.com/media/NVlabs/motionbricks/main/$f"; done
uv venv -p 3.12 ../venv
VIRTUAL_ENV=../venv uv pip install "warp-lang>=1.17" numpy scipy usd-core onnxruntime trimesh matplotlib
```
Import `mb_cpu` before any `motionbricks` module, then use `MotionBricksSOMAEngine(SOMA_N1_FP32_ONNX_PATH)` as the repository's examples do. Run Python with `-I` and keep your scripts outside the clone. A GPU or TensorRT install is only needed for NVIDIA's interactive tools.

## Pipeline
1. **Source poses.**
   - Author them on SOMA's rest pose (`skeleton.reference_local_transforms`) with `soma_pose.py`.
   - Or move a CC0/owned clip onto SOMA: export the game skeleton and clips with `dump_skeleton.gd`, then call `RigMap.to_soma(frame)`.
   - Never start from the repository's sample clips (evaluation-only).
2. **Key poses.** Use 3-6 per move: rest, anticipation, contact, follow-through, settle.
   - For each pose, set the body controls: hip drop/back, pelvis pitch, spine and chest bend, chest twist.
   - Place each hand with two-bone IK and an explicit elbow direction.
   - Aim the hand (fingers and palm) and curl the fingers.
   - Keep the planted feet where they stood.
   - Render stills from the side and from three-quarter front before generating.
3. **Generate.** Chain one generation per key pose and record the token range for each. To steer through a pose without stopping there, leave that generation a few frames early (a guide pose). Keep every take; generating is cheap.
4. **Rank and look.** Compute simple numbers per take, such as torso lean, crouch depth, touchdown frame and hand-to-target distance at contact. Sweep the inputs that matter (context speed, token range, target distance). Watch the stick-figure videos of the best two or three takes.
5. **Bake rig-free.** Store what the game rig can apply without knowing SOMA:
   - **Block/box rigs:** per frame, hip shift (a share of hip height), trunk bends and twist, hand from shoulder (a share of arm length), elbow direction, palm normal and finger direction, all in the chest's rest frame. The rig samples by gameplay phase. Clamp hand turns, and blend from the gameplay hand position into the clip hand position near contact, so the hit point stays where the server says.
   - **Skinned rigs:** per bone, the world turn away from SOMA's rest (a quaternion), plus SOMA's rest bone direction and the hips offset in leg lengths. At load the engine aligns each body's rest bone direction with SOMA's, so one clip drives every body that shares bone names.
   - Remove forward travel from the hips with a smoothed path (Gaussian, about 0.4 s); the game moves the body. Start each clip where the gameplay event starts (touchdown for a landing).
6. **Integrate.** Add a cosmetic setting, off by default. On skinned rigs, play the clip through a one-shot over the locomotion with a bone filter, and drive only the bones the move is about. Render the move in game with the setting off and on, then put the two side by side.

## Pose transfer between rigs
For each mapped bone with a child:
- `align = arc(receiving_rest_dir -> source_rest_dir)`
- `delta = source_world * source_rest_world⁻¹`
- `receiving_world = delta * align * receiving_rest_world`

For an unmapped child, use `parent_world * rest_local`. For the hips, use the source hips offset scaled by the leg-length ratio. This works whichever rest pose each rig uses (T or A). Getting the direction of `align` wrong doubles the rest difference (we saw 40° on the hips).

## Review loop
1. Key-pose stills (a human figure, with palm arrows).
2. A stick-figure video of the chained generation.
3. The in-game off-vs-on render, as video plus a contact sheet.

Show the owner the third, and say which setting turns it on. Keep a short evidence note per move: inputs and their licences, token ranges, the chosen take and why, and the files.
