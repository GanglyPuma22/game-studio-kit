# Playbook: works, doesn't work, recommended

What one 60-75 s game trailer taught (Nov 2026, Seedance 2.5 through Runway, stills from a subscription image tool). Each line is backed by a test in the [lessons log](lessons.md). "Pending" means the A/B hasn't finished.

## Look stills

| Works | Doesn't work | Recommended |
|---|---|---|
| One look still per chunk, painted from that chunk's own layout frame | A still borrowed from another chunk: it drags its setting into the clip | Paint per chunk; add "the setting, buildings and landmarks come from video 1" |
| The host's subscription image tool (no per-image cost) for stills | Expecting four distinct looks from one generator: they converge on its house style | Paid image API only when a specific model is needed; compare tools while the look is open |
| One paired reference per character (concept and game sheet side by side) under a 5-image cap | Separate concept and sheet images, which blow the cap | Pair the references; crop stills to 2.4:1 or narrower (Seedance rejects wider than about 2.5:1) |
| Neutral stills | A still of a giant holding or restraining a person: provider moderation blocks it (0 credits), whatever the text says | The text may describe a grab; the image must not show one |
| A stylized 3D feature look | Live-action: real-looking people, characters drift from their concepts | Shortlist on stills, decide on a short video test |

## Layout mode (what video 1 shows)

| Mode | Works | Doesn't work |
|---|---|---|
| **Camera-only markers** (pillars) | Smoother motion; holds positions and final framing; keeps giant detail | Swapped identities after cuts (one warden became the other) |
| **Clay** (posed figures) | Better landings and flight | Stiffer motion; simplifies the giants |
| **Clay + live lines + v2 rules** | Fixed identity on a chunk that had swapped (chunk 6 v2) | Stiffer than markers |
| **Markers + v2 rules** | Beat clay v2 on the same chunk: identity held, giant detail kept, smoother motion, no stray strands | |

Recommended: **camera-only markers with the v2 rules** as the default; clay only for shots where an exact pose is the point. Keep both twins of every shot.

## v2 rules (put in every brief)

- **One character per shot after a cut**, framed large (the hero fills about a quarter to a third of frame height).
- The brief **names who is and who isn't** in each shot ("This shot shows only the Medic. The Vaulter is not in this shot.").
- **Signature traits** per character, the same sentence every time (hood colour, mantle, weapon, hair, prop).
- **Distinct proxy colours** in the layout (no two characters in near colours; we moved the Vaulter from white to orange).
- **Exact limb counts** ("giants have exactly two arms and two hands").
- **Lines exist only while attached and while the shooter is on screen**: each runs from the shooter's launcher to one anchor; the release is its own beat; no line is ever left strung between two places.

## Thin props (cables, lines)

If the layout shows no line, the model invents the familiar trope (for grapple lines: web lines shooting from the wrists). Three layers fix it:
1. Draw the line in the layout, only while attached.
2. Give the device and cable a dedicated prop reference sheet in its own image slot, with a role line: "use only for the device and cable".
3. Route each line in the brief by its start and end, with explicit negatives.

Audit the shared rule text too: ours said "wrist launcher" by mistake and reinforced the trope.

Then work with what the model wants to do, not against it:
- **Name the attachment point** (the hip launcher, not "the hand"), and allow one hand to steady the line as long as the line clearly runs back to that point. Fighting the hand grip in every render costs retakes.
- **Cut on every release.** Stage each let-go on a cut so the model never draws a detach; that is where lingering lines and strays happen. Count the releases against the existing cuts first: most land on or near a cut and need only a nudge of a few frames.
- **The model may still carry a line through the cut** into the next shot. A line still hooked on through a landing reads as physical; accept it and remove only the wrong lines in [cleanup](cleanup.md).
- **Don't draw the props yourself.** A drawn overlay cable was tried and rejected: it looked worse than the model's, lingered, and couldn't fix the poses around it.

## Hands and limbs at contact

Models add limbs at contact moments (a grab, a catch, a hand-off): a second hand appeared from nowhere and grabbed instead of the giant's own arm. Pin it in the brief for every contact beat:
- which hand does the action ("only the giant's right hand does the grab");
- where every other limb is ("its left arm stays down at its side");
- an explicit negative ("no other hand or arm appears in the shot").

An extra limb can't be cleaned out after render; it's a re-render with the pinned brief.

## Cuts and chunks

- Seedance drops cuts that fall near a clip edge. **No cut within 0.75 s of a chunk's start or end**; check it in the encoder that cuts the chunks, not by eye.
- Budget in generated seconds: chunks overlap and have a 4 s minimum.
- **Partial re-renders:** when a change touches part of the film, re-render the layout and regenerate only the chunks it touches, then splice. Snapshot the simulation state at each chunk start so one chunk re-renders alone.

## Production order

1. **Qualify the hard chunks first**, out of order: the ones with the riskiest mechanics (thin props, grabs, several characters, cuts near releases). This is the experiment phase; the method is still allowed to change.
2. **Then render in film order**, so finished segments build up and the edit can be watched as it grows.
3. A chunk counts as done only when it is **fully qualified**: rendered, vetted, cleaned, checked zoomed in, and accepted by the person. Don't batch the rest of the film until the hard chunks pass.
4. **Every paid run is a dry run first.** The dry run prints every prompt, checks the inputs and file sizes, and prices the job. Ask for a typed go per chunk ("go chunk 2") with the dry-run price as the hard cap, one attempt, no automatic retries.

## Blockout gotchas

- Disable the engine's physics interpolation for previs renders: it leaves a stale frame at every cut.
- Verify on-screen size with the math (distance, field of view, character height), not by eye.
- Check in 3D and on screen that every line clears every body; generation copies clipping.
- Check the real animations frame by frame before using them; a flawed clip is copied as is.
- Every surface in the layout is set to the model. A helper plane or marker surface gets climbed or stood on (a character climbed a layout plane as if it were ice): hide helper geometry, or make sure it matches real set.

## Fixing a shot after render

- **Stray lines: remove them locally for free** with masks plus a nearby-frame fill; see [cleanup](cleanup.md). The person approved this method after side-by-sides. Check every patched frame zoomed in.
- **Re-render instead** when the defect is anatomy or pose (an extra hand, a fist closed around nothing) or a line rides a moving character over detailed scenery for the whole shot (no clean frame to borrow from).
- **Aleph patch** per shot between hard cuts (2 s minimum, 28 credits/s) restyles well, but it **cannot remove thin moving strands**. An image-edit model frame by frame redraws props in the wrong place and moves arms: single stills only.

## Vetting checklist (every returned clip)

1. Track each character at 6-8 fps: same person in every frame, no swap after a cut, nobody extra.
2. Every line has a shooter, an anchor and a release; none left strung.
3. Extra limbs, merged bodies, giants with the wrong number of arms; look hardest at every contact moment (grabs, catches).
4. Scale: giants about six times a warden, in every frame.
5. Then a blind second pass by another model or agent that hasn't seen the brief.
6. After any cleanup: zoom-check the patched frames (line ends, soft edges, straight structure the line crossed) and compare before and after at 1x and 0.5x.

## Lip sync (when a face speaks)

Lock the lines first. Quote the words and their timings in the brief, run one short Seedance test with audio on, then convert the generated speech to the game voice with speech-to-speech. Everywhere else, clips are silent and sound is built in the edit.

## IP hygiene

Keep the inspiring show's terms and names out of every prompt, and show only the project's own gear design. Prompts describe your characters, not someone else's.
