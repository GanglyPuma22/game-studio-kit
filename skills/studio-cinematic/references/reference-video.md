# Reference video spec (clay and pillars)

Render for a machine reader: **unambiguous, not beautiful.**

## Building the blockout

- Block from the engine's real map and characters when they exist; scale is then honest for free. Keep the movement-relevant geometry, nothing more.
- Pace at final energy and real speeds (for example a sprint at 7.2-7.4 m/s, falls near 1.6 g). A slow previs is a slow film.
- Cut on every beat; action shots 0.6-3 s. Action carries across each cut, already moving on frame 1.
- Every camera move is eased and starts on the shot's first frame. Shake only on named impacts.
- Turns lead with the head; anticipation before a move (crouch before a leap), a settle after (compress on landing).
- No dead air: trim holds, and trim both ends of the film. Output length follows the reference and dead air is billed.
- When an engine character uses its real animation, check that animation frame by frame first. If it is wrong, grade the shot pillars instead.
- Render at a fixed frame rate (e.g. 30 fps, offline, not a screen capture), 1280x720, H.264, no overlays or labels. Keep each clip under 5 MB for inline upload.

- **Frame key action large.** Small, fast figures in wide frames don't read after generation. Frame cuts, grabs and hits so the hero fills about a quarter to a third of frame height.
- **Check line clearance in 3D.** Where grapple lines or other tethers appear, check in the blockout that each line clears every body, in 3D and on screen. Generation copies clipping faithfully.

## The two twins

- **Clay:** articulated models in one flat saturated colour each, consistent through the film, on a mid-grey world, one sun with shadows.
- **Pillars (camera-only):** same camera, set, timing and placement; each character is a plain pillar of true height in its colour, with no limbs. Effects that sell contact (dust puffs, splashes) can stay.
- Render both for every shot from the same script so any chunk can switch grade.
- In an engine blockout, hide props rather than freeing them, and disable effects (wakes, particles) the model would copy as noise.

## Chunking

Models have a minimum job length (Seedance: 4 s). Render the film as chunks of 4-9 s that end on cuts. Each chunk's clip is cut from the twins per shot (pillars for one shot, clay for the next), and its prompt lists each time range with its grade and brief.

## QA gate

Before any paid run on a clip:
- [ ] Beats read in silhouette with sound off
- [ ] No pause, freeze or slow-down the brief doesn't ask for
- [ ] No linear spacing on hero moves; anticipation and settle present
- [ ] Contacts pinned in clay shots (scrub at half speed); feet above ground
- [ ] One colour per character; subject in frame and moving on frame 1
- [ ] Constant fps, honest scale, contact shadows visible
- [ ] Hero fills about 1/4 to 1/3 of frame height on every key action
- [ ] Tethers clear every body in 3D and on screen
- [ ] Ends trimmed; clip under the inline size limit
- [ ] Every shot graded (pillars / clay / first-frame / free) with a reason, and a brief for every non-clay shot
