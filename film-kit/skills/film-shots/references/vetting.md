# Vetting and fixing returned clips

## Check every clip (before it goes in the cut)

1. Watch at 6-8 fps against the shot's pass line, written before the run.
2. Track each character: the same person in every frame, nobody extra, no swap.
3. The one action happens, in order, with no frozen hold where a painted frame parked.
4. Limbs: extra hands or arms, merged bodies, wrong counts; look hardest at every contact moment.
5. Scale holds in every frame.
6. Thin props: every line has a shooter, an anchor and a release; none left strung.
7. Then a blind second pass by another reviewer who hasn't seen the brief.

Write the verdict on the shot card (pass, half or fail) and whether the fault was an input or a model limit. Retake only failing shots, at most two takes, one named input changed per retake.

## Review frames with the person before paying

Put every shot's first and last frame on one page where the person can circle problems and leave a note per frame, and read their marks back before painting fixes. Then ask for one go with a cap for the whole batch. It is cheaper to repaint a frame than to regenerate a shot.

## Fixing after render

- **Stray lines:** remove locally and for free: hand-keyed masks per shot, fill from nearby frames of the same shot (median, never across a cut), small rigid patches over straight structure (per-pixel flow bends planks), flow fallback for moving bodies. Zoom-check every patched frame (line ends, soft blurred edges) and compare before and after at 1x and 0.5x.
- **Re-render instead** for anatomy or pose errors, or a line that rides a moving character over detailed scenery for the whole shot (no clean frame to borrow).
- An image-edit model is for single stills only: frame by frame it redraws props in the wrong place.
- Check every model's licence before running it on commercial work (some video inpainting models are non-commercial only).

## Edit

Trim handles, cut on the [editing rules](../../film-camera/references/editing.md), per-shot colour match, then one grade over the whole film; later shots often come out paler, and grading is cheaper than regenerating.
