# Inputs: what each one is allowed to say

A video model copies what its inputs say, flaws included. Give each input exactly one job, make the inputs agree, and say in the prompt what each one is for. Most failed shots were input faults, not model limits.

| Input | Its only job | Never use it for |
|---|---|---|
| Painted first and last frame | The control: composition, who is where, the start and end state of the shot's one action. Painted together in one session, from one layout | Two actions; a state that undoes itself; frames from different sessions |
| Character sheet, one per character | Identity: silhouette, palette, costume, props. One body per sheet, made from the character's current canonical model plus its approved concept look | Look or style; a sheet with several bodies (a model drew a second copy) |
| Style frame (one approved frame) | Light, lens, texture, grade, in every shot | Composition or identity |
| Camera-only guide clip | The camera's path and timing, and where each character is, for camera-heavy shots: the grey set with each character as a simple blob, cut to the shot | Body motion; locked shots (send frames only) |
| Layout with articulated characters | Staging, timing, the source for painting the frames | Sending to the model, unless an exact pose is the point and its animation is clean: the model copies stiff limbs, pauses and sinking feet |
| Prompt | Camera, who (one fixed line per character, written from its sheet), the one action as a verb phrase, the fixed style line | Anything that contradicts the frames ("it has not touched her yet" kept a grab apart) |

## The guide method (A/B tested, Nov 2026)

On a flown 4 s chase move with the same frames, sheets and style frame in every take:
- **frames only** failed: the model ignored the start frame, reached the end frame by 1.9 s and held still. Two frames can't carry a moving camera;
- **frames + camera-only blob guide** (Kling 4) followed the path and timing and landed on both frames;
- **Seedance 2.5 + the same guide** gave the same structure, slightly more fluid, at 3x the price.

So: camera-heavy shots send frames plus the blob guide; locked shots send frames only. A blob reads as whatever it looks like: a pillar near the ground became a man running on the ground. Make fliers read as airborne (line visible, off the ground, "always in the air" in the prompt), and mark the direction of anything with a front (a cone on the business end of a weapon), or the model may flip it.

## Identity and consistency

- One sheet per character, and the prompt's words for that character written from the sheet. Inputs that disagree make the model pick one source per shot: a concept with an extra prop, blue boards and an "orange" prompt gave three different versions of one character.
- The character's **design** must match its current canonical model: a film is recognised by its characters and their abilities. The **art style** may differ from the product's own render; for a hype or marketing short it usually should.
- Every character visible in a shot, however briefly, gets its sheet; an unreferenced character comes out generic.
- A style reference clip had about no effect; a style frame did.

## Prompt anatomy

Build each prompt from fixed blocks so one change reaches every shot:
1. **Inputs**: the role of each attached image and the guide clip ("Image 1 is the first frame, Image 2 the last frame, Image 3 the look; the video is a rough camera layout: copy its camera and timing, perform the bodies yourself").
2. **Cast**: one fixed sentence per character in the shot, identical in every prompt; "This shot shows only X."
3. **Scale**: true sizes in words every time (models shrink big characters in wide frames).
4. **The one action**: a verb phrase; at a contact beat, which hand acts, where the other limbs are, and "no other hand appears".
5. **Rules**: "never a pause, freeze or slow-down; add no cuts; no camera shake except on named impacts".
6. **Look**: the fixed style line and a short avoid list (weightless motion, sinking feet, extra limbs, text, logos).

Prompts describe the target look; naming the product's own render style gets that render back. Keep any inspiring work's names and terms out of prompts.

## Thin props (cables, lines, ropes)

With no line in the layout the model invents the familiar trope. Draw the line in the layout only while attached, give the prop its own reference image, route each line in words by start and end with negatives, name the attachment point, allow a steadying hand, and **cut on every release** so the model never draws a detach. Don't draw props over the render yourself.

## Moderation

Never pass a reference image of one character holding or restraining another: provider moderation blocks the job (no charge) whatever the text says. The text may describe the action; the images must not show it. One diagnostic retry, then ask.

## Audio

Generate silent clips; build voices, effects and music in the edit so voices stay consistent across shots.
