# Lessons log (newest first)

Each entry: date, what was tried, cost, result, what changed in the method. Add to this as tests land; promote a lesson into [method](method.md) only once the person has picked it.

## 2026-11-09 — guide A/B on a flown move: the blob guide is needed
- Test: a flown 4 s FPV move (the merged shots 7-9). Every take had the same painted first and last frames, character sheets and style frame.
  - Kling 4, frames only ($0.63): FAIL. It ignored the start frame, reached the end frame by 1.9 s, then held still. Two frames can't carry a moving camera.
  - Kling 4 + camera-only blob guide ($0.75): HALF. It started and ended on the painted frames and followed the guide's path and timing. The fault was ours: a pillar near the ground read as a person standing, so he ran on the ground instead of flying.
  - Seedance 2.5 reference mode + the same guide, frames passed as @Image1/@Image2 ($2.27): HALF. Same structure and same fault, landing close to both frames and slightly more fluid, at 3x the price.
- Now the method: camera-heavy shots get the blob guide, with **Kling 4 + guide as the default**. Seedance 2.5 isn't worth 3x for this. Make airborne characters read as airborne in the guide: the cable visible, the blob off the ground, and "always in the air" in the prompt.

## 2026-11-09 — flown cameras, fewer cuts (free)
- The person asked for camera moves flown like a real film drone instead of drawn curves. A stick-flown simulator with DJI Inspire 3 S-mode limits, a pilot speed plan and a rate-limited gimbal operator ([camera rigs](camera-rigs.md), [script](../scripts/camera_rigs/camera_rig.gd)). Finding: the drawn reveal (82 m, 33 m drop) needs at least 8.2 s for a real drone and about 10 s smoothly; the story gave it 4.2 s. A flown 4.2 s version ended about 35 m wide, and she read too small.
- The person chose one continuous flight from him on the bridge to her fight, with the film extended: the story holds 4.5 s while she waits on her roof, the flight runs in three legs anchored on him, off her roof and the cut, on one 40 deg prime. It opens on the previous camera's exact frame.
- Then the whole film: 16 of 23 shots flown by drone, FPV chase, crane/dolly or handheld rigs; three cuts in under 3 s merged into one FPV move; the eruption's five setups cut to fewer; about 37 cuts down to about 28, from eight editing rules drawn from Fury Road, John Wick and The Lion King's virtual production ([editing](editing.md)).
- First render's faults, all fixed before showing: too much FPV roll (bank gain 0.15), flown cameras drifting off the action (leash: lens within 0.35-2.5 m of the drawn one by rig, aim within 6 deg), close cameras inside walls (camera guard), the end swoop through the giant (clearance at film scale). One FPV shot lost her and stayed drawn.
- The person: "a noticeable step up" in camera and shot quality; the two rough spots flagged (a roof edge crossing the reveal, a close pass over the giant's spikes) were not noticeable to them.
- Painted first and last frames can't describe a flown path, so the model would invent its own move. Method the person agreed (07:10Z), one-shot A/B pending: a camera-only guide (grey set, characters as blobs) plus painted frames for camera-heavy shots (about $0.94 per 5 s against $0.47 for frames only), frames only for locked shots, the clay with characters as reference only, long moves split at their anchors with matched frames. Kling 4 on fal stays the model. A/B result: see the entry above.

## 2026-11-09 — the grab froze from our inputs; the shot recipe
- A grab shot barely moved. Four input faults: its two frames came from different paint sessions and showed the hand opening (the reverse of a grab); the hand was metres from her in both; the prompt said "it has not touched her yet"; the closing itself sat on a cut, so no generation was asked to show it. The layout had the same flaw, painting copied it, the model copied the paintings.
- Fix, now the method: one camera, one forward action, 3-5 s per generation; a written spec, a seven-point pre-run check and a shot card per shot ([shot recipe](shot-recipe.md)). The grab retake with the recipe passed; a split swing passed; the slash failed on a leg mismatch between its frames.
- Shots from a later session came out paler than earlier ones: grade the whole cut at the end rather than chase the look per shot.

## 2026-11-08 — single passes fail on action; shot by shot
- The person found the clay animation stiff (giant walks, arms). A 24 s camera-only single pass (Kling 4 on fal, $4.51) gave the best look and most on-model cast so far, but a duplicate character, beats out of order, and near-still holds where the untimed middle frames parked.
- Two independent reviews agreed: look and identity are solved, action isn't, and a better single pass won't solve it. Middle frames have no timestamp on these APIs; no guide carries contact; tests that changed several things at once couldn't be compared.
- Snatch test, three 3 s shots ($1.41): the in-fist shot passed for the first time (one setup, frames differing only in her arms); the swing held between two actions; the hand shot failed (first and last frames too alike). Rule: the frames differ by exactly one clear action.

## 2026-11-07 — identity from one sheet per character
- A whole-film take ($12.36) disappointed: one giant's look changed every shot. Its inputs disagreed (concept art blue with a horseshoe-magnet crown, boards blue without it, the prompt "orange, never blue"), and the model picked one source per shot. Fix: one character sheet per character, the prompt's words written from it, the same refs in every shot, no contradicting concept art. Test ($1.72): on-model in all three takes.
- A sheet showing four bodies produced a second copy of the giant: one body per sheet, and "only one X" in the prompt. A style reference clip had about no effect: drop it. The person rejected a sheet painted away from the game model; sheets take shape from in-game turnarounds and the look from the approved concept.
- Kling 4 hugs the painted frames; Seedance 2.5 follows the brief but drifts from the frames.
- Working rules after days of experiments: one model, no experiment names in anything the person sees, one progress page, at most two takes per shot, one budget go for the batch.

## 2026-11-06 — stray-line cleanup approved; warps; pinned hands; order of work
- Free local cleanup is the approved way to remove stray lines: hand-keyed masks per shot plus a fill that copies the real background from nearby frames of the same shot (median, never across a cut). On a motion-blurred bank shot 78-94% of hidden pixels came from real frames; the old neighbour-average fill had smeared busy texture. Detail: [cleanup](cleanup.md).
- The person found two leftovers on a still. Both were mask misses, not fill errors: a line end that bowed away from the straight fit, and the soft blurred edge of the line at the frame edge. Rule: fit curves, cover the blur, zoom-check line ends and edges on every patched frame, rescan the shot after each fix.
- Tested on two more kinds of stray. A line left on after a cut over a slow camera came out clean from frames later in the shot. A dark line riding a giant's hand over plain snow (moving camera, no clean frame) came out better with the neighbour average, because the nearby-frame fill found under 50% real pixels.
- Limit: a line that moves with a character over detailed scenery for the whole shot left a faint ghost (0.5 s, visible at 0.5x). The person chose a re-render that cuts on the release instead.
- Warps: the person caught straight planks bent behind a removed line. Per-pixel optical flow alignment caused it; one global camera move per frame fixed the planks but left a stepped band on a moving giant's face. Small rigid patches (shift only) with a flow fallback for moving bodies fixed both.
- A second hand appeared from nowhere during a grab, 3 s in. The re-render brief now pins it: only the right hand grabs, the left arm stays down at its side, no other hand appears. Extra limbs can't be cleaned; pin limbs at every contact beat.
- ProPainter (video inpainting) is licensed for non-commercial use only: check every model's licence before running it on a commercial trailer.
- Order of work (person): qualify a few complicated chunks first while the method is still an experiment, then render in film order so finished segments build up; each chunk fully qualified before it counts. Every paid run gets a dry run and a typed go capped at the dry-run price.

## 2026-11-05 — cables: stop drawing them, cut on release
- Drawn cables (paint out the model's, draw a thin one from the hip) fixed the attachment point but not the poses (a fist left raised around nothing), smudged blurred frames, and looked worse to the person. Rejected: keep the model's own cables.
- Work with the model: name the hip as the attachment point, allow one hand to steady the cable, and stage every release on a cut. Of 8 releases in the film, 2 already sat on a cut, 3 were within 0.5 s (nudged), 3 needed a new short landing shot.
- Test (270 credits): cuts, identity and the hip cable all held, but the model carried the cable straight through the new cut into the landing. The person accepted cables staying hooked on through a landing; only strays get removed.
- An image-edit model (Krea, a few free frames) removed a cable from a hand cleanly but redrew it from the shoulder, moved the arms and missed a stray: single-frame touch-ups only, not shots.
- A layout helper plane read as set: a character climbed it like ice. Hide helper geometry.
- Large PNG references hit HTTP 413 on the provider (about 9 MB request): send stills as JPEG.

## 2026-11-04 08:25 — markers v2 wins; thin props
- Camera-only markers with the v2 rules beat clay v2 on chunk 6: identity held, giant detail kept, smoother motion, no stray strands. Markers are the default again; clay for exact-pose shots.
- Grapple cables: with no line in the layout the model invented web lines from the wrists. Fix in three layers: draw the line in the layout; a dedicated prop reference sheet in its own image slot ("use only for the device and cable"); route each line by start and end in the brief with explicit negatives. Our shared rule text said "wrist launcher" by mistake and reinforced the trope: audit shared text. Fallback: render without lines and composite them in the edit.

## 2026-11-04 — full refresh after the v5 chunks
- Layout A/B on chunk 6: camera-only markers gave smoother motion, held positions and the final framing and kept giant detail, but swapped the two wardens' identities after cuts. Clay gave better landings and flight, stiffer motion, simpler giants. Clay with live lines plus the v2 rules fixed identity (chunk 6 v2). Markers + v2 rules: see 08:25.
- v2 rules: one character per shot after a cut, framed large; the brief names who is and isn't in each shot; signature traits per character; distinct proxy colours (Vaulter moved to orange); exact limb counts; lines exist only while attached and the shooter is on screen, release is its own beat.
- Seedance dropped cuts near clip edges: no cut within 0.75 s of a chunk start or end, enforced in the chunk encoder.
- Blockout: disable physics interpolation (stale frame at cuts); verify on-screen size by the math.
- Aleph per-shot patch between hard cuts (2 s minimum, 28 credits/s) restyles well but cannot remove thin moving strands: fix them upstream.
- Vetting checklist: track each character at 6-8 fps, every line has a shooter, anchor and release, extra limbs or merges, scale, then a blind second pass by another model.
- Lip sync plan: lock lines, quote words and timings in the brief, Seedance audio-on test, then speech-to-speech into the game voice.
- Partial re-renders: regenerate only the chunks a change touches and splice; snapshot sim state at chunk starts.
- IP: keep the source show's terms out of prompts; show only the project's own gear design.
- Look stills crop to 2.4:1.

## 2026-11-03 17:20 — first real chunk; framing and line clearance
- First real film chunk rendered: 6 s, 270 credits, Seedance 2.5 reference mode, stylized 3D feature look (which beat live-action on character adherence).
- Seedance reference mode keeps the layout's set and blocking very well, but small fast figures in wide frames don't read. Frame key action (cuts, grabs) so the hero fills about a quarter to a third of frame height.
- Run a geometry check in the blockout that grapple lines clear the giant's body in 3D and on screen; generation copies clipping faithfully.

## 2026-11-03 07:40 — image tools, look B rejected on video
- Person's rule: stills through the host's built-in image tool (subscription, no per-image cost); a paid image API only when a specific model is needed; the video provider for video only.
- That tool takes at most 5 reference images per job: use one paired reference per character (concept and game-model sheet side by side).
- On the same 12 prompts the built-in tool (no model name reported) was far more polished and on-model than Gemini Nano Banana via OpenRouter ($0.615), but its four "different" directions converged on one glossy stylized-3D look. Expect one house style per generator.
- Both generators shrank giants in lineups and wide frames (about 2x warden height instead of 6x): state scale hard in every still.
- Look B (live-action film) rejected after a video test: real-looking people and character drift. Person wants an animated look with close concept adherence. Judge looks on video tests, not stills alone.
- A runner acted on a go after a correction had arrived: $0.615 spent on the wrong run. Re-check for newer instructions right before every paid call.

## 2026-11-03 06:00 — per-chunk look stills, full cast refs, boards first
- Grab v2 passed moderation (Seedance 2.5, 270 credits, 214 s, plus a $0.047 still) with a closed-fist brief: trapped to the shoulders, straining, "held firm, menacing, not hurting her". The text was never the problem; the restraint image was.
- A borrowed look still drags its setting into the clip: the grab rendered under the charge shot's bridge. Now each chunk gets its own look still, painted from its own layout frame with nobody held, cropped to 2.5:1 or narrower (the image model returned 3:1, which Seedance rejects). The prompt adds "The setting, buildings and landmarks come from video 1."
- Every character visible in a chunk needs reference images, even for half a second: a lead seen only in the last 0.8 s came out as a generic man.
- From an outside script critique: make a timed board or animatic with scratch audio before any paid render, and check comprehension (can a newcomer say why each beat happens?). Block contact points, line endpoints and release frames as proxies wherever contact matters; pillars alone can't carry them. Budget in generated seconds (chunks overlap and have a 4 s minimum), not film runtime.

## 2026-11-03 05:10 — grab as pillars passed; music plan
- Grab chunk as pillars: passed on the 3rd try (Seedance 2.5 video-to-video reference mode, 6 s, 270 credits, 229 s render). The two blocks before it (`INPUT_PREPROCESSING.SAFETY.THIRD_PARTY`, 0 credits) came from a reference image: a painted look still of a giant hand holding a woman. Softening the text did nothing; swapping that still for a neutral look still fixed it. Rule: never pass a still of a giant holding or restraining a person as a reference. The prompt can still describe the action.
- Person approved back-to-back dialogue lines between the two leads.
- Music: generated (ElevenLabs first, Fish Audio possible) or free commercial-use tracks with each licence checked and recorded; no hand composing. Music comes after picture lock, with hit points synced to the cut.

## 2026-11-03 — moderation, audio, tethered action
- Seedance's provider moderation (`INPUT_PREPROCESSING.SAFETY.THIRD_PARTY`, 0 credits charged) blocked a grab shot twice. Softening the text didn't help; the likely trigger is a reference image (a painted giant hand gripping a woman). Keep restraint-like images out of the references, and give each block at most one diagnostic retry.
- Render clips with audio off. Build every voice, effect and the music in the edit, so voices stay consistent across chunks; reuse the game's recorded lines where they fit.
- Tethered (grapple-line) action briefs: arcs, not zips; line tension shown in the body; legs trail, then snap in; the camera lags, then catches up; one clear pose before each hit. Leave out smears, animating on twos and frame stutters, which the models render badly.

## 2026-11-03 — script v2, grab as pillars (pending)
- Person's review of the 34 s v4 clay: the grab used the game's real grab animation, whose elbow inverts so the held character looks sucked into the hand; the landing and run after it had sunken, sliding feet. Both would be copied. Decision: grade those shots pillars, and test the grab chunk as pillars (~270 credits) before the film.
- Story: the trailer never showed the grapple lines, the game's signature verb; the wounded giant fled and never returned; 34 s was short of the 45-60 s goal. Script v2 (~55 s) brings the giant back for a 2v1 built on lines and kit moves, with a callback to the opening and an end card.
- Person: "the looser we give the structure, the more the model can fill in with its training on real film". Pillars are now the default for every shot; clay twins kept for per-chunk choice.

## 2026-11-03 — camera-only pillars test (270 credits, $2.70)
- Same camera, set and timing as the strict clay, characters as plain pillars of true height, plus a director's brief: kept the strict clay's camera and the free run's motion. Person: clear winner. Opening frames on blurry running legs read as an action camera, which they liked.
- Perspective made near pillars look as tall as the far giant pillar; the prompt must state true scale.

## 2026-11-03 — freedom test on the charge shot (541 credits)
- Seedance text-to-video from refs only, and Kling 4 from a first frame: both fluid. Seedance with the clay as a loose reference: weakest.
- Strict clay had the better camera, free had the better bodies. Person picked "mix per shot", which led to the pillars test.

## 2026-11-03 — look video test, look B (~530 credits)
- Seedance 2.5 best; Kling 4 good; Aleph 2 left clay mannequins in the frame.
- Strict clay was copied one to one, including a 1 s pause in the run.

## 2026-11-02/03 — look round (OpenRouter image model, $0.81)
- Four looks painted from clay key frames plus concept + turnaround per character: all kept the characters recognizable. Giants came out too small: state scale.
- Person picked a live-action film look over painterly, stop-motion and gritty, and asked for a look clearly different from the game's own. (Later rejected on video; see 07:40.)

## 2026-11-02 — first model tests (Runway and OpenRouter)
- Prompts asking for a "stylized 3D, mobile-game cinematic" look got the game's look back. The person disliked it.
- Wan 3.0 via OpenRouter: weak from first frames; with a video reference (HTTPS only) it copied the blockout. Not used for the film.
- Seedance has an 80-credit minimum per job and a 4 s minimum length; inline data URIs under 5 MB avoid hosting.

## 2026-11-02 — engine blockout
- Blockout script in the engine, rendered headless at fixed 30 fps (1500 frames at 720p took about 40 min on CPU). Warden origin is the capsule centre: place feet by offset. Use the giant's real grab code rather than faking it. Hide boats instead of freeing them and disable their wakes.
- v3 (50 s, 13 shots) approved for story; v4 trimmed every hold to 34 s and added the pillar twin.
