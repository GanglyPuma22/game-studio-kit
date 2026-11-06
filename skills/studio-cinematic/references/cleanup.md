# Cleanup after render: removing stray lines and small defects

What one trailer taught about fixing rendered clips locally, for free (Nov 2026). Removal only: nothing is drawn or repainted by hand. The method is open-source computer vision (OpenCV), no paid model.

## Prevent first, clean second

Cleanup is the safety net, not the plan. Most defects are cheaper to stop in the layout and brief:

- **Cut on the release.** A thin prop (cable, rope, beam of light) causes most strays when the model has to show it letting go. Stage each release on a cut, so the model never draws a detach. In one 73 s film that took 3 new cuts and a few frame nudges, not a restructure.
- **Expect the prop to carry across the cut anyway.** The model may keep a cable hooked through the cut into the next shot (a landing). A prop still attached while the character lands looks physical; the person accepted it. Remove only the lines that are wrong (strays, a second line, a line from the wrong body part).
- **Pin hands and limbs in the brief** at every contact moment (see [playbook](playbook.md#hands-and-limbs-at-contact)). Extra limbs can't be cleaned; they need a re-render.

Re-render instead of cleaning when the defect is anatomy or pose (an extra hand, a merged body, a fist left closed around nothing), or when a line moves with a character over detailed scenery for the whole shot (see Limits).

## What didn't work

| Tried | Result |
|---|---|
| Drawing our own cable over the render | Looked ugly, lingered after release, and couldn't fix the poses that go with a cable. The person ruled it out |
| Averaging the pixels around the line (OpenCV Telea inpaint) everywhere | Visible smears across busy, motion-blurred texture (manes, cliffs). Still the right fill on plain backgrounds |
| An image-edit model frame by frame | Redrew the prop from the wrong attachment point, moved the arms, missed a stray; fine for one still, not for a shot |
| A video restyle patch over the shot (Aleph 2) | Restyles well, cannot remove a thin moving strand |
| Optical flow to align neighbouring frames pixel by pixel | Bent straight things behind the line (planks, rails, roof edges); see Warps |

Before using any video-inpainting model, **check its licence for commercial use**. The best-known one (ProPainter) is non-commercial only.

## The method

### 1. Masks (where the line is)

- Key each line by hand on a few frames per shot: a rough segment or search band. Fully automatic detection mistook hair, manes and roof edges for lines; with a band, a ridge detector (top-hat or colour-specific ridge map, then a Hough or curve fit) finds and tracks the line on its own. Budget about a minute of keying per shot.
- Use a ridge map that matches the line's colour (bright, dark, green, blue).
- Fit a gentle curve, not a straight line: line ends bow away from a straight fit, and the bowed end is where leftovers hide.
- Smooth the fit over about 3 frames so the mask doesn't jump, and list frames with weak support for a manual look.
- Cover the soft, wider glow of a motion-blurred line, especially at the frame edge, but keep the mask tight elsewhere: a loose mask swallows nearby shadows and edges you want to keep.
- Mask only the strays. Leave every correct line alone.

### 2. Fill (what goes behind the line)

Never borrow pixels across a cut. A donor frame often has the same stray in it: exclude each donor's own masked pixels from the median and from patch matching (reject a patch whose source overlaps the donor's mask). Where no valid sample remains for a pixel, use the next fill down the table (flow fallback, then neighbour average), and list those frames for a manual look.

| Case | Fill | Why |
|---|---|---|
| Line moves against the background, or the shot has frames with no line | **Nearby-frame fill**: take the median of the same spot in the frames either side plus the nearest clean frames of the same shot | 78-94% of hidden pixels came from real frames; detail stays sharp |
| Straight structure behind the line (planks, rails, edges), locked or slow camera | Nearby-frame fill with **small rigid patches**: split the hole into windows along the line, find each window's surroundings in the other frame by a pure shift (template match that ignores the hole), copy across, median of the best matches, tent-weight the overlaps | A shift can't bend anything, so straight things stay straight |
| Moving character behind the line, where no shift matches | Fall back to the flow-aligned fill for those pixels only | Patches fail on non-rigid motion |
| Line moves with the camera over a plain background (sky, snow), no clean frame | Neighbour average (Telea) | The nearby-frame fill found under about 50% real pixels and dragged in specks; on plain ground the average is invisible |

Feather the mask edge (a small blur) when blending the fill back in.

### 3. Warps

Two artifacts come from how frames are aligned:
- **Bent straight lines**: per-pixel optical flow is slightly wrong right next to the removed line, and bends planks and rails. The person caught it on a still.
- **Stepped bands**: one global camera-move alignment per frame keeps planks straight but leaves a step across anything that moves on its own (a giant's face).

Small rigid patches with a flow fallback fixed both.

### 4. QA before showing the person

- Zoom-check every patched frame: both ends of each line, its soft edges, the frame edge, and any straight structure the line crossed.
- Run a leftover scan: look for faint ridges of the line's colour just outside the mask.
- Compare before and after side by side at 1x and 0.5x, plus a still sheet of the worst frames.
- Leftovers came from the masks, not the fill. When the person finds one, fix the mask, then rescan the whole shot for the same miss.

## Limits

A line that moves with a moving character over detailed scenery for the whole shot has no clean frame to borrow from. The fill leaves a faint see-through ghost (visible at 0.5x). Fix that chunk in the re-render: cut on the release, so the line is never there.

## Tooling

Keep the method spec-driven: one small spec per shot (hand keys, colour, frame range, cuts) and generic scripts for masks, fills and the before/after. The recipe above is enough to build it with OpenCV and NumPy in a few hundred lines. For provenance only: the first project's version lives in the Skybreak repo under `tools/cine/strays/`; reuse it if you have access, otherwise build from this page.
