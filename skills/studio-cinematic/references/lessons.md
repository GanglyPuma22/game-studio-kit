# Lessons log (newest first)

Each entry: date, what was tried, cost, result, what changed in the method. Add to this as tests land; promote a lesson into [method](method.md) only once the person has picked it.

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
- Person picked a live-action film look over painterly, stop-motion and gritty, and asked for a look clearly different from the game's own.

## 2026-11-02 — first model tests (Runway and OpenRouter)
- Prompts asking for a "stylized 3D, mobile-game cinematic" look got the game's look back. The person disliked it.
- Wan 3.0 via OpenRouter: weak from first frames; with a video reference (HTTPS only) it copied the blockout. Not used for the film.
- Seedance has an 80-credit minimum per job and a 4 s minimum length; inline data URIs under 5 MB avoid hosting.

## 2026-11-02 — engine blockout
- Blockout script in the engine, rendered headless at fixed 30 fps (1500 frames at 720p took about 40 min on CPU). Warden origin is the capsule centre: place feet by offset. Use the giant's real grab code rather than faking it. Hide boats instead of freeing them and disable their wakes.
- v3 (50 s, 13 shots) approved for story; v4 trimmed every hold to 34 s and added the pillar twin.
