# Method: what each input is allowed to say

A generation job has four inputs. Give each exactly one job, and say so in the prompt.

| Input | Its only job | Never use it for |
|---|---|---|
| Reference video (pillars or clay) | Camera path, lens feel, cuts and their timing, where each character is, scale | Look, identity. Body motion only when the shot is graded clay |
| Look still (picked look, painted per chunk from that chunk's own layout frame) | Light, lens, texture, grade | Composition, setting or identity. A still borrowed from another shot drags its setting in |
| Identity pack (concept + three-quarter turnaround per character) | Who each character is: silhouette, palette, costume, props | Look (say "render in the target look, not the references' drawing style") |
| Text (director's brief) | What happens: the action, its energy, what must never happen | Repeating what the video already fixes |

## Shot grades

| Grade | Reference clip | The model does | Use when |
|---|---|---|---|
| **pillars** (markers) | Camera-only twin: plain coloured pillars of true height, plus small proxies for contact points, line endpoints and release frames where contact matters | Performs all bodies from the brief inside the copied camera | Almost always. Runs, fights, swings, grabs whose animation is not perfect |
| **clay** | Articulated blockout, one flat colour per character | Re-surfaces the posed bodies | An exact pose or contact is the point and the clay's motion has passed QA |
| **first-frame** | A painted still as frame 1 (plus optionally pillars for camera) | Performs from that composition | A composition must be exact (a scale shot, a close-up) |
| **free** | None (identity pack + look still + brief) | Everything | A blink-length impact or a shot the blockout can't stage |

A chunk can mix grades per shot: the prompt states each time range and its grade.

## Why pillars beat strict clay on one shot (measured on a 6 s charge shot)

Later, on multi-character chunks with cuts, markers swapped identities; clay with live lines and the v2 rules fixed it. See the [playbook](playbook.md#layout-mode-what-video-1-shows).


- **Strict clay:** best camera, but the output copied a 1 s pause in the run, the stiff gait and the game look.
- **Free (no video):** fluid bodies, but the camera was the model's and the composition drifted.
- **Loose clay** (clay with "follow loosely" text): the weakest of all; the model half-copies.
- **Pillars + brief:** kept the strict clay's camera move (the low push-in, the tilt up at the end) and the free run's motion: everyone kept running, the giant swung mid-stride. The person called it the clear winner, including a blurry-to-focus opening on running legs that read like an action camera.

The looser the structure, the more the model draws on real film footage it has learned. Fill only the gaps the model can't: camera, placement, scale, timing.

## Failure modes and fixes

| Symptom in output | Cause | Fix |
|---|---|---|
| A freeze or slow-down mid-action | A hold in the reference | Cut the hold from the blockout; "never a pause" in the rules |
| Feet sliding or sunk into the ground | Blockout used a run clip at the wrong rate or the origin is off | Pillars for that shot, or fix contacts first |
| Odd limb (inverted elbow, body "sucked" into a hand) | The source animation itself | Pillars + brief; report the animation bug to its owner |
| Giants drawn too small | Perspective in the layout; image models also shrink big characters in lineups and wide frames (about 2x instead of 6x) | State true scale in words every time, in every still and clip ("six times a warden's height, whatever the layout suggests") |
| Output looks like the game | Prompt said "game cinematic", or clay pixels leaking | A distinct look still; pillars; "ignore the layout's colours and blocky shapes" |
| Setting from another shot appears | Look still borrowed from a different chunk | Paint a still per chunk from its layout frame; "the setting, buildings and landmarks come from video 1" |
| A character renders as a generic person | No reference images for someone on screen briefly | Attach the identity pack for everyone visible in the chunk, however briefly |
| Identities swap after a cut | Markers layout, several characters, near colours | v2 rules: one character per shot after a cut, "this shot shows only X", signature traits, distinct proxy colours; clay with live lines |
| A cut is missing | Cut within 0.75 s of the chunk edge | Re-window the chunks (encoder check) |
| A stray line hangs between two places | Line drawn after release or with the shooter off screen | Lines only while attached and shooter on screen; release as its own beat. Aleph can't paint it out |
| Stale frame at a cut | Engine physics interpolation in the blockout | Disable interpolation for previs renders |
| Characters merged or swapped | Untagged references, similar colours | Name every image's role; one distinct colour per character |
| Provider safety block before generation (0 credits) | A reference image that reads as restraint or harm (measured: a still of a giant hand holding a woman); softer text does not help | Never pass a still of a character holding or restraining a person; use a neutral look still and let the text describe the action. One diagnostic retry, then ask the person |
| Voices differ between chunks | Model-generated audio | Audio off; voices, effects and music in the edit |
| Added cuts or characters | Model's habit | "Add no cuts beyond the layout's"; list who is in the shot |

## Story lessons for game trailers

- Show the game's signature verb. A trailer for a grapple game that never shows a line fired has missed its point; plan where each kit move appears.
- Give every character a reason for what it does next. An enemy that flees and never returns reads as a loose end; bring it back.
- Length follows the story: a 34 s cut felt short against a 45-60 s goal; fill it with action, never with holds.
- End on a title card (name or logo) the way big mobile trailers do; keep it name-neutral until the name is chosen.
- Only the people who own the canon approve spoken lines.
