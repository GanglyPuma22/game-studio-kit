# Playbook: works, doesn't work, recommended

What one 50-60 s game trailer taught (Nov 2026, Seedance 2.5 through Runway, stills from a subscription image tool). Each line is backed by a test in the [lessons log](lessons.md). "Pending" means the A/B hasn't finished.

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

Audit the shared rule text too: ours said "wrist launcher" by mistake and reinforced the trope. Fallback: render without lines and composite them in the edit.

## Cuts and chunks

- Seedance drops cuts that fall near a clip edge. **No cut within 0.75 s of a chunk's start or end**; check it in the encoder that cuts the chunks, not by eye.
- Budget in generated seconds: chunks overlap and have a 4 s minimum.
- **Partial re-renders:** when a change touches part of the film, re-render the layout and regenerate only the chunks it touches, then splice. Snapshot the simulation state at each chunk start so one chunk re-renders alone.

## Blockout gotchas

- Disable the engine's physics interpolation for previs renders: it leaves a stale frame at every cut.
- Verify on-screen size with the math (distance, field of view, character height), not by eye.
- Check in 3D and on screen that every line clears every body; generation copies clipping.
- Check the real animations frame by frame before using them; a flawed clip is copied as is.

## Fixing a shot after render

- **Aleph patch** per shot between hard cuts (2 s minimum, 28 credits/s) restyles well, but it **cannot remove thin moving strands** (a stray line). Fix those upstream in the layout and re-render the chunk.

## Vetting checklist (every returned clip)

1. Track each character at 6-8 fps: same person in every frame, no swap after a cut, nobody extra.
2. Every line has a shooter, an anchor and a release; none left strung.
3. Extra limbs, merged bodies, giants with the wrong number of arms.
4. Scale: giants about six times a warden, in every frame.
5. Then a blind second pass by another model or agent that hasn't seen the brief.

## Lip sync (when a face speaks)

Lock the lines first. Quote the words and their timings in the brief, run one short Seedance test with audio on, then convert the generated speech to the game voice with speech-to-speech. Everywhere else, clips are silent and sound is built in the edit.

## IP hygiene

Keep the inspiring show's terms and names out of every prompt, and show only the project's own gear design. Prompts describe your characters, not someone else's.
