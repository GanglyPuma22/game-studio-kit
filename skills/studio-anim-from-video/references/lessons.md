# Lessons log (newest first)

Each entry: date, what was tried, cost, result, what changed in the method. Two rigid-block giants: "Lodestone" (17-bone puppet, 22 blocks) and "Glacier" (same rig, about 10 m in the puppet's units). Promote a lesson into SKILL.md only once the person has agreed with it.

## 2026-11-07 — Anymove compared
- Anymove (Apache-2.0) is a second implementation of the same method, credited to video2rig's author. It adds no new stage, but better process: a take table with fixed gates and a published 58% pass rate, about 7 clips per usable move, an exam in centimetres, per-axis joint limits, planted-foot holding, a prompt template from the character's config, and a stop rule after six failed seeds. It has no props, no hidden-joint training and no one-view mode, so it would not have read the Glacier heave. Its fit's first guess has the same per-frame flip as video2rig's. Detail: [anymove](anymove.md).

## 2026-11-07 — the fit's first guess, not the reader, spun the arms
- A reader retrained with two extra points on each upper arm, forearm, thigh and shin (55 points instead of 39; 3,000 renders on CPU, 1.7 cloud units) cut the worst forearm jump from 98 to 12 degrees a frame, but the shoulder took the roll (85 degrees in a frame). Six roll-limit settings changed nothing.
- Cause: video2rig's starting guess points each bone at its read joint by the shortest turn from the start pose, frame by frame. For an arm overhead (about half a turn from hanging) that shortest turn swings round a different way between frames, and the fit settles on each side of the jump.
- Fix (free, CPU, in the add-on): `continuous_start` (each frame's guess follows the previous frame's) and `limb_plane_start` (elbows and knees bend in the plane of the three read joints). With the old reader, every heave joint stays under 22 degrees a frame (was 231), despike finds nothing, the throw matches the video better. Cost: the grab at 2 to 3.5 s sits a few px further from the video. The roll reader was not needed.
- Lesson: an exam with an overhead pose would have shown this before the cloud run.

## 2026-11-07 — reading one panel
- Kling 4's punch looked best, but for about a second its two panels showed two different giants (a mirror image punching with the other hand). Reading the front panel alone (side confidence set to 0) gave a smooth clip (19 degrees max a frame, 0 pops), with depth guessed: a deep crouch that may not be real. A fallback for good-looking clips whose views disagree, not a default.

## 2026-11-07 — punches turn the giant; prompts and keyframes
- FLUX 3 Max, Kling 2.6 and Kling 4 all turned the giant about 90 degrees into a "punch straight ahead" (at the front camera). Throws had not done this: the prop beside the giant gave a sideways direction. Next test proposed, not run: a target pillar in front of the giant, visible in the side view.
- FLUX's high-reasoning prompt expansion added a boxer's guard at the start; another take added a stagger at the end. Hand-written prompts drift between attempts: use a template and a move card that bans extras.
- Hand-posed wind-up and hit keyframes as extra frames for the video model were dropped: the leg poses looked awkward to the person.
- Kling 2.6 makes 5 or 10 s clips; a punch needs about 2, so the giant stood idle for 1.8 s first. Trim at bake, free.
- Scores, same Lodestone reader: Seedance 2 conf 0.60 / 2 pops; FLUX take 2 0.58 / 8 pops; Kling 2.6 take 1 0.68 / 0 pops (best); Kling 2.6 take 2 failed (limbs 4.0%). Glacier punch on FLUX: 0.75 and 0.69, 0 pops.

## 2026-11-07 — split at the hold
- Pick-up and throw had to be separate game moves. Cutting the video first and reading each half alone made the halves disagree by up to 4 m at a hand. Cut the whole-clip fit at its stillest frame near the hold, ease both halves into one shared still pose. No retraining.
- A post-fix (`tame_twist.py`: smooth roll, soft cap 15 degrees elbows, 10 knees) cut the worst elbow roll from 98 to 13 degrees. The person did not want post-fixes as a required step: clean output from the pipeline, with post-fixes kept as checks. That led to the first-guess fix above.

## 2026-11-06 — props
- Glacier heave (8 s, Seedance 2): the throw warped the elbows. The reader had been trained without the prop. A reader trained with the chunk in its hands (1.35 units) fixed most of it; the forearm hidden by the chunk stayed rough.
- A rock reader for the small aimed throw read worse than the plain reader (a 127 degree forearm flip against 29). Props that hide little don't need their own reader.
- Start pictures: the prop placed beside the giant at a measured spot (`add_prop.py`), giant facing +Y, side view facing left. The person loved both Seedance looks; the in-game version must match the video closely.

## 2026-11-05 — video model A/B on one punch
- Same Lodestone reader, one punch prompt: Seedance 2 conf 0.60, 2 pops; Seedance 2 mini 0.51, 59 pops; Wan 2.2 (run on a cloud GPU) scrambled the painted limbs; LTX-2 gave no clip. Seedance swung the whole body about 130 degrees into the punch: keep a share of the turn per group at bake (hips 15%, spine 30%, chest 45%).

## 2026-11-04 — first clip
- Lodestone stagger, one Seedance 2 clip. Reader: 3,000 renders, 9,864 steps on an L4 (1.64 units), held-out 2.7 px front, 3.2 px side. `check` body 1.1% (pass), limbs 4.7% (warn). Soft fit `--set w_floor=5 --set w_vel=6 --set w_acc=0.01`, then despike (pops at the hit). The person loved it, but it was too exaggerated for combat. Video models overact; plan to tame.
- Giants have no skeleton: the puppet is built from the game rig's blocks with Rigify-like bone names so video2rig finds sides, knees and elbows; the bake maps bones back to blocks.
