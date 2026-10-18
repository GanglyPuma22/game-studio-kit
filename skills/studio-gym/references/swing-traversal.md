# Swing and grapple traversal gyms

Read alongside [studio-gym](../SKILL.md) when the game's main verb is a grapple, a rope or a swing: hooks fired at anchors, reeled in or swung on, carrying the player at speed between tall structures or large moving targets. Traversal of this kind is a feel problem first. The physics can be correct while the controls are unplayable, and the gym is where both get measured.

What studios have said about it, in short ([sources](sources.md)):

- Swinging traversal is built around **anchor geometry metrics**: building heights, street widths and spacing were set so a web always has something to attach to. "If you don't have something to swing from, you can't swing."
- Control is simplified from the realistic model. An early fully manual two-hook control scheme was found too hard to operate and was moved, in the developers' words, "like manual to automatic".
- The camera carries the sense of speed: field of view and follow distance rise with speed, pitch follows the arc, and each new attachment briefly kicks the field of view.
- Input friction matters as much as physics. A traversal ability bound to an awkward button combination went unused until it became one press.
- Climbing onto a much larger moving enemy needs both sides to read what is happening, which is its own design problem, separate from swinging.

## Inventory additions

Add these rows to step 1, with the current numbers read from code:

| Verb or system | Numbers to record |
|---|---|
| Fire hook (left, right, both) | Search radius, aim cone, maximum rope length, travel time, what counts as a valid anchor |
| Target assist | How a candidate is scored (angle from aim, distance, surface type), lock persistence, override input |
| Reel and boost | Reel speed, boost force, any resource it spends (per second, capacity, refill rule) |
| Swing | Gravity used during a swing, damping, rope stiffness or fixed length, input steering force |
| Release | Speed retained, the angle range that sends the player up versus forward |
| Wall contact | Run, slide, kick-off speed and angle; what happens when the rope wraps a corner |
| Strike from the swing | Approach speed window, hit volume size, angle window, slow-motion or hit-stop timing |
| Camera | Field of view and follow distance against speed, roll with the rope, collision behaviour at speed |
| Failure | What happens with no anchor in range, out of the boost resource, rope snagged, hook on a moving target |

## Rooms to add

### Anchor field
- **Geometry.** Pillars and walls at marked heights (10, 20, 40, 60 m) and spacings (10 to 80 m), in rows that open out until they exceed the search radius.
- **Questions.** At what spacing does continuous swinging break? Does the reticle show when nothing is in range?
- **Metrics.** Distance to the chosen anchor, number of candidates in range, time without an anchor.
- **Expected.** Continuous travel at spacings up to the radius minus a margin; a clear "no anchor" signal past it.

### Swing arcs
- **Geometry.** A single tall anchor over open ground with height rings and a distance grid.
- **Questions.** Swing apex, ground clearance at the bottom of the arc, speed at the bottom, how much steering changes the arc.
- **Metrics.** Speed, height above ground, rope length, rope angle.

### Release and momentum lane
- **Geometry.** A straight run of anchors with distance markers every 10 m and a long empty stretch after the last one.
- **Questions.** Speed kept through a chain of swings; distance carried after the last release; how the release angle splits speed between up and forward.
- **Metrics.** Speed per swing, speed and angle at release, carry distance.
- **Expected.** Speed does not decay to nothing over a chain, and does not grow without limit either.

### Target-assist room
- **Geometry.** Anchor clusters at known angles from the aim: two valid anchors at equal distance, one valid and one invalid surface side by side, anchors behind the player, and an anchor on a moving target.
- **Questions.** Which anchor the assist picks and whether a player would have picked it.
- **Metrics.** Candidate list with scores, chosen anchor, aim angle. A driven check measures the pick rate on each cluster.

### Moving and large targets
- **Geometry.** An anchor on a moving, rotating body the size of the game's largest creature, with a marked strike zone.
- **Questions.** Does the hook hold as the target moves? Can the player approach the strike zone inside its speed and angle window? Does the target's own motion throw the player off?
- **Metrics.** Relative speed at contact, angle into the strike zone, hit or miss with the reason.

### Corners and tight spaces
- **Geometry.** Narrow alleys, overhangs and a corner the rope must wrap.
- **Questions.** Rope wrap or snap behaviour, wall-run and kick-off, camera collision at speed in a tight space.

### Camera at speed
- **Geometry.** The momentum lane with pass-by walls at fixed distances.
- **Questions.** Does the camera clip at speed? Do field of view and follow distance follow their curves? Is the horizon readable through a fast arc?
- **Metrics.** Speed, field of view, follow distance, camera roll, camera collision events.

### Resource and failure room
- **Geometry.** A course longer than one full boost resource, with a refill point. Skip it when traversal spends nothing.
- **Questions.** What a player sees and does as the resource runs out; what the fall looks and sounds like; recovery from a fall.

## Checks

Driven checks are valuable here because a person cannot fly the same arc twice. Fix the seed, start from the same point and replay the same inputs, then compare apex, carry distance and speed per swing with the golden snapshot. Target-assist pick rates belong in the snapshot too. Feel, camera comfort and whether the controls are learnable are judged only by a person playing the anchor field and the momentum lane, and that judgement is the main point of the gym for this kind of game.
