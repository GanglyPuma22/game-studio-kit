# Runtime block rigs: workflow and lessons

How to run the boxes-first method when the blocks are posed in the engine
every frame from gameplay state (a procedural rig over a game character),
rather than keyed in Blender and baked. Read with
[primitive planning](primitive-planning.md) (coverage, fair comparison,
catalog) and [block motion rules](block-motion-rules.md) (the physical
rules and the checker). The same opt-in applies: use it only when the user
asks for boxes-first animation on a named task.

Everything here comes from one pilot: a 29-block quadruped giant
re-authored in Godot over four review rounds (18 moves: idle, turn, walk,
gallop, punches, bites, a lunge, two kinds of climb, hits, death) until the
user approved the set. Each lesson below names what went wrong, what it
cost and what to do instead.

## The modules

[scripts/block_anim/](../scripts/block_anim/) holds engine-side GDScript
that knows nothing about any creature. Copy them into the game (they are
`RefCounted` helpers, no scene or autoload) and keep the game's copy in
sync with the Kit by hand.

| File | What it does |
| --- | --- |
| [block_chain.gd](../scripts/block_anim/block_chain.gd) | FABRIK whole-chain reach with per-joint cones, an authored-pose prior, a root that may shift in a box, `aim` for weighted swings and `ease_from` for frame-to-frame continuity |
| [two_bone.gd](../scripts/block_anim/two_bone.gd) | two-bone limbs with the bend hint named for its kind (`solve_toward_point`, `solve_toward_direction`) and a hinge axis that remembers last frame's side |
| [gait.gd](../scripts/block_anim/gait.gd) | walk, canter and rotary gallop footfalls with world plants, spine flex and hind/fore load |
| [plant.gd](../scripts/block_anim/plant.gd) | the no-slide stepper with deliberate defaults (`configure(leg_length)`, rest, paired feet, no step in place) |
| [motion_check.gd](../scripts/block_anim/motion_check.gd) | the rule checker: per-clip report plus per-frame events; `setup_rig()` reads a rig description |
| [selftest.gd](../scripts/block_anim/selftest.gd) | golden poses for all of the above; `godot --headless --script .../selftest.gd` exits 1 on a failure |

The rig description template is
[block-rig.json](../../../templates/block-rig.json): blocks, parents,
limits, hinges, contacts, soft blocks, stance, scenery contacts and
per-move expectations. Keep rig facts there, not as constants in the rig
script, so the solver, the checker and the review page read the same
data and the next creature starts from data.

## Network cost

Pose every block on each client from state the game already syncs
(position, velocity, facing, action phase, targets). The rig and checker
add no network data and no server work. Say so in the PR, and do not
move hitboxes to follow the new poses without a separate decision.

## Before authoring: what the game provides per move

Make a table per move before writing rig code. Most late surprises in the
pilot would have shown up in it.

| Move | Gameplay provides (contacts, targets, phases, timing) | Missing | Pinned blocks | Free blocks | Scenery |
| --- | --- | --- | --- | --- | --- |
| Bite | head target, bite phase, hold flag | target can sit 1 m off the ground, below a rigid body's reach | skull | spine, arms, legs | ground |
| Lunge | tell, flight and landing phases | gameplay legs do not travel in flight | none | all | ground |
| Climb | climbing flag, wall normal | no ledge or wall-top state | none while climbing | all | wall face and top |

Typical gaps: legs that do not travel in a leap (feet try to land behind
the body), a whole-body drop used to reach low (the hips sink and knees go
through the ground), no ledge state in a climb (the rig needs its own ray),
targets a rigid body cannot reach. For each, decide: game change, rig
workaround, or accepted drift, and record it.

## Iteration loop that worked

1. **Check-only pass** over every clip with per-frame events (the
   pilot's: about 4 minutes for 19 clips, seconds for one). Find the
   frame, the rule and the block from the events, not from video.
2. **Render only the clips that changed**, side by side with the old
   animation, from one simulation drawn several ways in the same frame
   (old, new model, boxes) so timing, camera and light match exactly.
3. **Full render last** (the pilot's: about 25 minutes), then watch
   every changed move at full speed before calling a round done.

A live sandbox with scrubbing, boxes drawn red where a rule breaks, and
a per-frame JSON export of poses and rule results is the next step up;
the check-only pass is the minimum.

Queue heavy jobs. Rendering clips while local CI ran starved a real-time
online smoke test and failed it; it passed alone.

## Review built for decisions

The first review (18 moves × three panels, good and rough mixed) let the
user say which were better but not approve the set. What worked:

- Show a handful of moves per round by default (five), each with its own
  Approve / Needs work, and a "changed since last round" filter.
- Put the rule scores beside each move, and freeze-frames at key poses.
- Auto-frame the camera to the creature's bounds over the clip, with a
  side and a front view; fixed offsets left moves half out of frame or
  behind a wall.
- Let approved moves ship on their own (a per-move switch in game), not
  all or nothing.
- Stills and coarse strips hide the defects users notice first: a shuffle
  lasts a quarter of a second, a head in a wall shows only from one angle.
  Sample strips at full frame rate around rule events (a step, a wall
  contact) and watch at full speed.

## Pitfalls checklist

Check these before the first review; each cost at least one round in the
pilot.

- [ ] **IK hint kind.** The two-bone solver's hint is a point or a
      direction, and the call passes the same kind. A mismatch bent every
      elbow and knee skyward for two rounds while the symptoms got tuned.
      Use `two_bone.gd` and run the selftest.
- [ ] **Hinge direction is checked**, not only joint range.
- [ ] **Shortest-turn angles.** `Quaternion.get_angle()` can exceed 180°;
      use `motion_check.shortest_turn_deg()`.
- [ ] **Constraint order is written down** (rules doc, "When the rules
      conflict"), with a per-frame report of what gave way.
- [ ] **Hip floor uses the bind pelvis height**, not a gameplay height that
      already includes a crouch or stoop.
- [ ] **Stance moves only for held moves.** A punch that nudges the hips
      must not move the stance.
- [ ] **Feet follow the rig's stance**, never a gameplay foot with its own
      stepping.
- [ ] **Stepper sized to the leg** (about a third), with rest and paired
      feet. Shuffles score zero.
- [ ] **Solver continuity**: eased chain solves, hinge memory, no
      unmotivated overshoot. Joint flip rate is in the report.
- [ ] **Scenery in the checker**: walls with their top (count the nearer
      face, so feet standing on the roof are not "in the wall"), and
      pinned blocks that let go when scenery is in the way.
- [ ] **Per-move expectations**: planted contacts, when balance applies,
      thresholds.
- [ ] **Every changed move watched at full speed** from at least two
      angles.

## Handoff

Report per move: scores before and after, what the game does not provide
and how the rig covers it, remaining drift of pinned blocks, and the
review verdict. Keep verdicts unresolved until the user reviews them, and
keep the old animation selectable until the user approves the set.
