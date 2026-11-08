# Anymove notes

[Anymove](https://github.com/patch-gg/anymove) (Apache-2.0, read at c3cb22c on 2026-11-07) implements the same method as [video2rig](https://github.com/canitcode/video2rig) (AGPL-3.0): a two-view start picture, a per-character DINOv2 joint reader trained on random-pose renders, a whole-clip fit. Its README credits the method to video2rig's author.

## Taken into this skill
- Take gates and a ledger with a pass rate ([checks](checks.md)). Theirs: view agreement 0.8 or more, front 3 px, side 8.5 px, on confident readings; 58% of 335 captured clips passed; about 7 clips per usable move.
- A stop rule: six failed seeds on one move means the move may be one the method can't do. Drop or flag it.
- The exam: a known motion rendered and read back, scored in cm.
- A prompt built from the character's config plus one action sentence that starts and ends in the rest pose, with a check that prompts still match the config.
- Headroom for the biggest pose in the layout.
- Per-axis joint limits (x bend, y twist, z swing), with mirrored z ranges for left and right.

## Worth trying later
- Holding planted feet still in a second fit (they report 1 to 2 cm slide left).
- A video-model LoRA trained on clean captures re-rendered in both views, to keep the panels in step and colours fixed (MiniMax H3 on fal, about $12; colour swaps 2 of 5 to 0 of 5 on their wolf). Needs 15 to 20 clean captures first; check the model's community licence.
- MiniMax H3 Max as a video model (their best for view sync; about $0.26 a 5 s clip; untested by us).

## Not useful for rigid-block giants
- Mesh generation, automatic skinning and seam merging: we bring our own parts.
- GLB packs, loops and root motion: walks and runs are procedural in our game.
- Switching tools: Anymove has no props, no hidden-joint training and no one-view reading, and its fit's first guess flips the same way video2rig's did before our fix.

Because Anymove is Apache-2.0, its code can be adapted into our repos with attribution. video2rig's cannot.
