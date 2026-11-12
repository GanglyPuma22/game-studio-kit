# Editing: fewer cuts, moves instead

Readable action comes from two things: the camera moves the way real gear moves ([camera rigs](camera-rigs.md)), and the viewer's eye stays in one place across cuts. When the second isn't possible, cut less. On the first film this took the cut count from about 37 in 75 s to about 28 in about 80 s, and the person called the result smoother and clearer.

## Where the rules come from

| Production | What they did | What we take |
|---|---|---|
| The Lion King (2019) | A fully virtual film shot with real crane, dolly and Steadicam rigs fitted with trackers | Simulated rigs with real limits for every moving camera |
| Mad Max: Fury Road | Almost every shot is centre-framed ("put the cross hairs on her nose"), so each new shot lands where the eye already is | When cutting fast, the subject sits at the same spot in frame on both sides of the cut |
| John Wick | Long, wide takes of choreographed fights, no cutting away, no shaky cam | Hold a shot through a whole action beat instead of cutting inside it |

## The rules, in priority order

A cut has to earn its place: it shows something the moving camera can't reach in time. Otherwise the camera moves instead.

1. **One beat, one shot.** A shot holds through a whole action beat (fire, swing, hit) and never cuts inside it. Minimum shot length 1.5 s; the only exceptions are impacts under 1 s.
2. **Move instead of cutting.** If a real rig can reach the next framing in the time available, fly to it. Three cuts in under 3 s (a slow-motion arc, her view from the fist, the forearm cut) became one FPV move; five setups for one eruption became one drone move that carries from the rise over the wall to the track onto her roof.
3. **Same spot across a cut.** The subject sits at the same place in the frame on both sides of every cut.
4. **Cut on motion.** Mid-swing or mid-leap, never on a still frame; the movement carries the eye across.
5. **Keep screen direction** (the 180-degree rule). A flip needs a camera move that crosses the line on screen.
6. **Wide before close.** Each new place opens wide, or arrives through a move like a reveal, before any close shot.
7. **Hidden transitions over hard cuts** between places: foreground passing the lens, a whip pan along the action, a match on shape or motion.
8. **Sound bridges the cut.** In the sound pass, each cut's sound starts a few frames early or runs a few frames late (J and L cuts).

## How to apply them to a film

1. **Audit every shot** in a table: shot, today's camera, the change, the rig. On the first film 16 of 23 shots got a flown camera, 2 got handheld smoothing and 5 stayed as they were.
2. **Merge the fastest-cut runs first.** Count cuts per second; any run with cuts under 1.5 s apart is a candidate for one move. Merging changes the film's structure, so show the person the shot table before re-flying.
3. **Re-fly in film order**, then re-time the edit. A merged or held move shifts every later film time: update the chunk table, the encoder windows and the shot cards in the same pass, or the next job cuts the wrong frames.
4. **Render the whole clay film** with the cut list for the person's look before any paid generation. It's free and it's where structure changes are cheap.

These rules interact with generation: a merged move is one long camera, but a generation is 3-5 s ([shot recipe](shot-recipe.md)). Split a long move at its anchors into back-to-back generations whose last and first frames match, so it still plays as one flight.
