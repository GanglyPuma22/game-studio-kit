# Block motion rules

Rules for animating a creature built from rigid blocks (the boxes-first
method in [primitive planning](primitive-planning.md)): each body part is a
rigid box and the detailed model is skinned to those boxes. The rules are
simple physical assumptions, not a physics simulation. They are short
enough to follow by hand when blocking a move and precise enough for a
script to check ([motion_check.gd](../scripts/block_anim/motion_check.gd)).

A creature supplies its block list, joint limits, hinges, contact points
and which blocks carry gameplay hitboxes, ideally in one rig description
([block-rig.json](../../../templates/block-rig.json)). Nothing here is
specific to one creature or game. First proven on a 29-block quadruped
giant in a Godot team fighter, re-authored over four review rounds until
the user approved the set.

## The rules

1. **Blocks are rigid.** A block never stretches, squashes or scales.
   Length comes from the model; a pose only moves and rotates blocks.
   Named soft blocks are the one exception (a throat sac may swell). A
   neck that needs to reach further gets that reach from the blocks behind
   it, never from stretching.
2. **Joints stay joined.** A child block's joint sits on its parent's
   joint in every frame. Bending at a joint is fine; a gap or overlap
   there is a bug.
3. **Joints have limits, and hinges bend one way.** Each joint has a cone
   (how far it may swing from its rest direction relative to its parent)
   and a twist range. Spine joints are stiff (about 30°), necks and wrists
   loose (50° to 70°). Knees and elbows are hinges: they bend about one
   axis and only in their anatomical direction. Range alone does not catch
   a knee bent backwards, so the checker tests direction too. The rig
   enforces a limit where it can (an ankle past its range turns back and
   the leg is solved again with the sole where it now sits), and a planted
   foot whose leg would leave its range steps instead (rule 6).
4. **Reach with the whole chain.** When an end block (the skull for a
   bite, a hand for a punch) must reach a point, every block from the root
   to that end shares the motion: distal joints move most, proximal joints
   less, and the root (the pelvis) shifts only when the chain alone cannot
   reach. The supporting legs re-solve under the shifted root. A bite drops
   the chest, arches the spine and bends the front arms; it is not a head
   moving alone.
5. **Hitting blocks are pinned; the rest follow the rules.** A block that
   carries a gameplay hit (the head in a bite, the hand in a punch) goes
   exactly where the game puts it. Every other block may leave its
   gameplay piece by a small budget to obey the other rules, and the
   checker reports how far. A pinned block lets go when scenery is in the
   way (rule 8): the game's body can lean into a wall the visual head must
   not enter.
6. **Planted contacts do not slide, and steps are deliberate.** A foot or
   palm on the ground holds its ground position until it lifts. Gaits plant
   at touchdown and lift at liftoff; nothing slides in between. A planted
   contact also holds its heading, and steps (lifts and re-plants, never
   slides) when the body has moved too far over it: past the leg's reach
   or range, or (in a gait) too far from where the stride wants it. A foot
   twisted past about 35° pivots on the ground instead of stepping in
   place. Steps are never fidgets: see the stepper defaults below.
7. **Weight sits over support.** Standing or moving slowly, the centre of
   mass stays over the support area (the feet and palms on the ground).
   Moving fast, it may lead the support (a gallop falls forward into each
   stride); in flight it follows a ballistic arc. Balance is not checked
   in flight or mid-lunge.
8. **Nothing goes through the ground, the scenery or the body.** No block
   below the ground or inside a wall; limbs do not pass through the torso.
   The hips keep a floor (they do not sink below a set share of their
   *bind* height unless kneeling), and in a deep crouch a knee that would
   go through the ground rises into a squat instead. On a climb the body
   hangs back off the face, the head stays its own length off it, and a
   hand or foot moving from the face onto the top goes up past the edge
   first, then over (a straight line cuts through the corner). Walking up
   to a wall, a short ray ahead holds the head and front limbs back before
   contact.
9. **Momentum: no pops, no flips.** Block positions and rotations change
   smoothly. A big move starts with anticipation (a counter-move of about a
   fifth of the move, the opposite way), and the heaviest blocks start and
   stop first: hips, then chest, then neck, then head and hands
   (overlapping action). Loose parts lag and settle. The solver must be
   continuous too: a chain solve eases from last frame's shape instead of
   jumping to a nearby one, and an elbow or knee remembers which way it
   bent so it never swaps sides as a hand passes close to the shoulder.
   Settle without overshoot unless the overshoot is the point of the move;
   an unmotivated one reads as a wobble.
10. **Gaits follow real footfall patterns.** Walk, canter and gallop use
    measured animal footfall orders and duty factors (share of the stride
    a foot is down), with suspension phases where the animal has them. A
    gallop is not a fast walk: fewer feet down, longer flight, and the
    spine flexes and extends with each stride.

## When the rules conflict

They will (a low bite with the head pinned, the knees above ground and the
feet planted cannot all hold). Settle conflicts in this order, in one
place, and log which rule gave way and by how much each frame:

1. Hard: rigid blocks, joined joints, nothing below the ground or inside
   scenery.
2. Planted contacts (no slide).
3. Hitbox pins (a pinned block may trail its gameplay piece, and the
   drift is reported).
4. Joint ranges and hinge direction.
5. Style: balance, overlap timing, secondary motion.

Patches added one by one in rig code (a hip floor here, a knee raise
there) give results that depend on their order. Write the order down
before the first patch.

## Gaits (rule 10)

Limb order: left hind, right hind, left fore, right fore. Offsets are the
share of the stride when each foot lands; duty is the share it stays down.
[gait.gd](../scripts/block_anim/gait.gd) blends between them.

| Gait | Footfalls (LH, RH, LF, RF) | Duty | Suspension | Spine |
| --- | --- | --- | --- | --- |
| Walk (lateral sequence) | 0, 0.5, 0.25, 0.75 | 0.65 | none | small sway |
| Canter (3 beats, right lead) | 0, 0.3, 0.3, 0.6 | 0.42 | one, after the leading fore | mild flex |
| Rotary gallop (cheetah) | 0.6, 0.5, 0, 0.1 | 0.28 | two: gathered and extended | flex in gathered flight, extend in extended flight (flex about twice extension) |

The gallop's two flights carry its look: in **gathered flight** (after the
fore feet lift) the spine flexes and all four legs swing under the body;
in **extended flight** (after the hind feet lift) the spine extends and the
legs reach fore and aft. Speed comes mostly from a longer stride, not a
faster one (Hildebrand 1961, cheetah).

## Stepper defaults (rule 6)

Emergent stepping (a foot steps whenever some rule says so) made the feet
patter during punches, bite holds and landings: each small body nudge set
off another step, often straight back to where the foot stood.
[plant.gd](../scripts/block_anim/plant.gd) ships with deliberate defaults:

- The foot's target is a stance the rig owns, under the hips. Never
  follow a gameplay foot that has stepping logic of its own.
- It steps when the stance has moved about a third of a leg
  (`configure(leg_length)`), not a fixed few centimetres.
- It rests about 0.35 s between steps; the two feet of a pair take turns.
- A step that would land within a quarter of the tolerance of where it
  stands is dropped.
- A twisted foot pivots instead of stepping.
- When a *held* move carries the hips somewhere (a bite drawing them in),
  the stance moves with them and the feet step under once. Do not move the
  stance for transient moves (a punch), or the feet step forward and back.

The checker counts shuffles (steps landing within 0.6 m of where they
lifted on a large creature; scale it to the body). Aim for zero.

## What the checker measures

Per clip, from the posed blocks each frame
([motion_check.gd](../scripts/block_anim/motion_check.gd)), with
per-frame events (frame, rule, block, amount) for debugging:

| Check | Rule | Measure |
| --- | --- | --- |
| Stretch | 1 | largest scale change of any rigid block (%) |
| Joint gap | 2 | largest distance between a child's joint and its parent's joint (m) |
| Joint limits | 3 | frames over a limit and the worst excess (degrees; the *shortest* turn from rest relative to the parent) |
| Hinge direction | 3 | frames with a hinge bent the wrong way and the worst amount (degrees) |
| Hitbox drift | 5 | largest distance from each pinned block to its gameplay piece, and from free blocks to theirs (m) |
| Foot slide | 6 | ground distance a planted contact moves while down (m per second of contact) |
| Steps and shuffles | 6 | steps per clip, and shuffles: steps that land close to where they lifted |
| Balance | 7 | share of slow frames with the centre of mass outside the support area |
| Ground and body | 8 | deepest block below the ground (m); frames with a limb inside the torso |
| Walls | 8 | deepest block inside a wall the body is against (m), which block, how many frames. The rig supplies the wall's face and top; the nearer face counts, so a foot standing on the top is not "in" the wall |
| Pops | 9 | largest block acceleration (m/s²) |
| Joint flips | 9 | fastest joint turn between frames (deg/s); an elbow swapping sides shows here, not in position acceleration |

Thresholds belong to the move, not the rig: which contacts should be
planted, whether balance applies, how much drift a pinned block may have.
Record them per move in the rig description and show them beside each
move's scores.

Before trusting any score, run
[selftest.gd](../scripts/block_anim/selftest.gd): golden poses with known
answers (a 200° turn reads 160°, a backward knee is flagged, a forward
reach bends the elbow down and back). A checker bug once reported 125°
excesses that did not exist and a round of tuning went after them.

## Sources

- FABRIK (Aristidou and Lasenby 2011): position-based chain IK that
  handles joint constraints and several end effectors. Used with cone
  limits, a movable root and a pose prior.
  https://www.andreasaristidou.com/FABRIK
- Unreal's full-body IK effectors (strength, pull chain, chain depth):
  the whole chain to the nearest fork moves with an effector.
  https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PBIKEffector
- Rotary and transverse gallops, suspension phases, gathered and extended
  flight: Hildebrand's cheetah studies and "16 Ways to Gallop"
  (arXiv 2503.13716). https://arxiv.org/html/2503.13716v1
- Plausibility checks (foot sliding as contact displacement, ground
  penetration, centre of mass over the support polygon) follow measures
  common in motion-generation evaluation (for example HUMOS,
  arXiv 2409.03944).
- Anticipation, follow-through and overlapping action: the twelve
  principles of animation (Thomas and Johnston).
