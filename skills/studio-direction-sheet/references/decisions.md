# The seven decisions

Each decision is: what to decide, the parameters, why it reads, do and don't, and the failure it prevents. Values marked **[tune]** are starting points to adjust in play, not rules. The decisions are standard animation craft (anticipation, staging, follow-through, squash and stretch and timing are among the twelve principles in Thomas and Johnston, *The Illusion of Life*, 1981; smear frames and animating on twos are long-standing hand-drawn practice).

## D1. The look and the palette

- **Decide:** one style phrase ("graphic-novel ink", "neon on black") and a small palette of named colours, before any motion is designed.
- **Parameters:** 2 to 4 colours, each with a job: core or hot, body, rim or accent. Name them and give values. In a game, the palette belongs to the character or faction and is reused by every effect that character makes.
- **Why it reads:** the eye identifies the source of an effect by colour before shape. A locked palette makes an effect belong to its owner instead of looking pasted in.
- **Do:** sample every effect's ramp from the character's named colours. **Don't:** let each effect pick its own colours, or use realistic gradients in a flat style.
- **Fails as:** physically plausible fire that could belong to anyone.
- **In a game:** palette serves identification first (team, character, threat), beauty second.

## D2. The one moment and when it hits

- **Decide:** exactly one hero moment per move, effect or shot, and the time it lands.
- **Parameters:** the time in seconds or as a frame at a stated rate, or a fraction of the duration (a 5 s shot whose burst hits at 2.2 s, 44 % in). Everything before is preparation; everything after is consequence. A multi-beat shot has one moment per beat, separated by a cut or a clear settle.
- **Why it reads:** viewers keep one peak per beat. Two peaks read as noise; an untimed peak drifts to wherever the default puts it, usually too early or smeared over the whole length.
- **Do:** write the hit time before production. **Don't:** ask for "an exciting sequence".
- **Fails as:** constant intensity. An effect at full strength the whole time has no moment.

## D3. Anticipation, release, settle

- **Decide:** the moment's three phases as silhouettes and lengths.
  - **Anticipation:** a readable gather (compress, coil, draw back) whose silhouette differs from rest.
  - **Release:** the fastest phase; the peak change often takes 1 to 3 frames.
  - **Settle:** overshoot past rest, then decay. It never stops dead.
- **Parameters [tune]:** anticipation about 20 to 40 % of the time before the hit and readable at full speed; settle 1.5 to 3 times the release, with at least one visible overshoot.
- **Why it reads:** anticipation tells the viewer where to look and what comes next; the settle separates weight from a cut-off. No anticipation feels random; no settle feels weightless.
- **Do:** make the anticipation pose read at a glance from the usual camera. **Don't:** stretch anticipation until the action feels late.
- **In a game:** the anticipation is also the opponent's reaction window. Read its length from the game's tuning and record which value it is. Changing it is a balance change (see the limits below).
- **Fails as:** an effect that comes out of nowhere and vanishes.

## D4. Smears and cadence

- **Decide:** where smear shapes appear and whether authored poses step.
- **Parameters:** a smear is a deliberately distorted in-between stretched along the path of travel, on the fastest 1 or 2 frames of a movement only. Stepping on twos holds each pose for 2 frames (poses change at 12 per second on a 24 fps timeline). Slow and settling phases may return to smooth motion; mixed cadence is normal.
- **Why it reads:** a smear keeps the feeling of speed without blur's mush; stepped poses give a graphic snap that suits a drawn look, where smooth in-betweens everywhere read as floaty.
- **Do:** keep smears to the release and fast transits. **Don't:** hold a smear longer than about 2 frames (it reads as deformation), or step anything in the limits below.
- **Fails as:** uniform smooth interpolation: everything glides, nothing lands.
- **May be waived** with a reason (a realistic look, a move with no fast phase).

## D5. Where the eye goes and the empty space

- **Decide:** one focal point and what stays quiet around it.
- **Parameters:** the focal point is the brightest, highest-contrast element; the hero moment happens at it. Secondary elements run at lower contrast, smaller size and less motion. Name the empty space that must stay empty.
- **Why it reads:** the eye goes to contrast and motion first. An ambient effect brighter than the event that matters sends the eye to the wrong place; in a game that is a readability bug.
- **Do:** spend contrast on the moment that matters. **Don't:** fill space because it looks empty.
- **In a game:** a play space is never an empty stage, so D5 becomes contrast budgeting against a busy scene. When two effects fire together, the one with a gameplay consequence wins the budget.
- **Fails as:** three effects at equal strength; nobody can say what happened.

## D6. The loop

- **Decide:** whether the piece loops; if it does, the loop point and how the seam hides.
- **Parameters:** loop at a low-energy pose (rest or settle), never mid-release; first and last poses equal, or cross-faded by design; particle loops fade in and out at the bounds.
- **Why it reads:** a visible seam resets attention every cycle.
- **Scope:** idles, ambient emitters, menu or ident loops. **Waive** it for one-shot abilities and narrative shots.

## D7. What to avoid

- **Decide:** 2 to 5 named failures for this subject.
- **Parameters:** nouns a reviewer can point at ("orb", "brown mush", "white flash", "body hidden by its own trail"), not adjectives ("bad").
- **Why it reads:** generators and agents drift toward their average. The avoid-list is the only part of a direction that pushes away from it.
- **Do:** build it from the last failure actually seen, and add one noun per killed take. **Don't:** copy another subject's list.
- **Fails as:** the default look with the subject pasted in.

## Limits in a real-time game

These outrank the seven decisions on any in-engine sheet.

1. **Readability and counterplay first.** Anticipation is the opponent's reaction window. Never shorten a telegraph for feel without treating it as a balance change.
2. **Two classes of effect.** Anything that carries information (telegraphs, impact zones, paths, destruction state, footing) is driven by replicated state with fixed parameters and looks the same on every client. Pure dressing (motes, sparks, chunks with no meaning) is client-local and may vary. Never let a cosmetic particle system be the only carrier of information, and never rely on GPU particles being deterministic across machines.
3. **Silhouettes stay visible.** No full-screen flash, smoke volume or particle density that hides a character's silhouette or anticipation pose. If an effect covers a character, shrink the effect.
4. **Camera limits stand.** No effect-driven camera impulse beyond the game's camera settings. Sell impact on the effect.
5. **Stepped cadence stays off movement.** Locomotion, blend spaces, camera and camera-relative motion stay smooth; telegraphs stay smooth.
6. **Budgets are stated.** Each emitter: amount, lifetime, draw passes, and whether it collides (cosmetic ones should not). Ambient emitters at a low fixed rate. Set real numbers from the game's target hardware.

## In-engine mapping

Written for Godot 4; the ideas carry to other engines.

| Decision | Where it lives |
|---|---|
| D1 | Named colours in one shared resource per character; particle colour ramps, flash materials and UI accents sample it |
| D2 | One hit frame. A method-call track key (or one gameplay event) fires damage, the burst (`restart()` on a one-shot emitter), the sound and hit-stop together, so no layer drifts. The hit time sits in the move's tuning next to its other values |
| D3 | Anticipation: the wind-up keys and the telegraph, its length a tuning value. Release: the fastest keys, a burst with `explosiveness = 1.0` and high initial velocity. Settle: follow-through keys on secondary parts, particle damping and fade curves, recovery frames. Never cut from release straight to idle |
| D4 | A smear mesh (a flat, palette-coloured arc or blade shown for 1 or 2 frames at the fastest point) or a vertex stretch along the swing. Stepped poses: keys on a 1/12 s grid with nearest interpolation on the action clip's pose tracks, never on the blend space |
| D5 | Per-class caps on brightness, size and alpha; ambient emitters lower and slower than gameplay effects |
| D6 | Idle clips loop at rest; ambient emitters use seamless ramps. One-shots waive it |
| D7 | Kept with the character's sheet; new effects are checked against it before a playtest, not after |

Starting shapes **[tune]**, to adjust in play:

- **Mid-size melee hit:** anticipation 0.25 to 0.40 s (also the dodge window), hit frame, burst of 40 to 120 particles with explosiveness 1.0 and 0.3 to 0.6 s life, settle 0.3 to 0.5 s with one overshoot, hit-stop 40 to 90 ms on a confirmed hit.
- **Large character slam:** anticipation 0.6 to 1.0 s with a ground telegraph that grows to the true radius; low, wide debris of large, few particles with a 0.8 to 1.5 s settle; a dust ring at ground level. Large bodies move each limb slower but cover more ground.
- **Fast traversal:** smear on the body only during the fastest frames; a thin, short trail. A trail that shows other players the path is information and belongs to the synced class.

## Video mapping

For one generated shot. Fill the decisions in this order before any run:

1. **D1:** the project's style string and the character's palette names, worded the same in every shot. Palette drift between shots breaks identity.
2. **D2:** one moment per shot with its time ("the grab closes at 2.2 s of 5 s").
3. **D3:** the three phases as visible silhouettes. For a large character the wind-up must read at its size.
4. **D4:** smear or blur for the fastest element only. Diffusion video models cannot be relied on for true on-twos cadence or one-frame smears from text. If the stepped look is wanted, enforce it after (hold each generated frame twice) or through a reference rendered on twos. Direct the intent; verify the cadence frame by frame.
5. **D5:** the focal point and what stays still ("background figures still; only the hand moves").
6. **D6:** only for pieces meant to loop; narrative shots waive it.
7. **D7:** per character, kept across shots: proportion drift, muddy skin, extra fingers or limbs, camera shake or roll beyond the project's rules, photoreal texture against a drawn look.

A shot is not ready to generate until D1 to D3, D5 and D7 are written. Where a reference video exists it carries the timing ([studio-cinematic](../../studio-cinematic/SKILL.md)); the sheet carries the look.

## Sources

- Frank Thomas and Ollie Johnston, *The Illusion of Life: Disney Animation* (1981): the twelve principles behind D3 and D5 and the timing language throughout.
- The seven-decision list itself comes from a short motion-design demo (November 2026) contrasting a directed and a described effect on the same model. The demo was a single effect on an empty background with no character, camera or scene, so the in-engine mapping, the video mapping and the limits above are this kit's adaptation, not the demo's.
- Godot 4 documentation for the in-engine mapping: particle process materials (explosiveness, colour ramps, fixed rate), AnimationPlayer method-call tracks, AnimationTree blending.
