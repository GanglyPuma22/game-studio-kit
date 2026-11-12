# One skin on a generated mesh: Blender weights, engine-posed controls

How to animate a one-piece generated character (image to 3D, a sculpt, a
scan) **as it is**: no regenerate, no cutting into rigid pieces. Blender
weights the whole mesh to an armature placed on the model's own joints; the
engine poses those controls every frame (a runtime block rig) or plays
clips on them. Read with [runtime block rigs](runtime-block-rigs.md) and
[block motion rules](block-motion-rules.md).

The pilot was a four-limbed plant giant with a hinged two-jaw head, long
claws and a loose crown of vines (20,000 triangles, 29 controls, 19 moves).
Against the same moves on the same model cut into rigid pieces: torn seams
went from 19 moves to none, the worst stretch from 33x to 2.9x, and the
count of checker problems from 255 to 174. Each rule below names what went
wrong before it existed.

## When to use it

- The model is one connected surface (plus loose shells) and the user likes
  it. Cutting it shows seams at every joint; regenerating changes the look.
- The limbs are apart in the model (not fused to the body or each other).
  Automatic weights need the surface between two limbs to be absent, not
  merely thin. A fused limb needs a tear or a regenerate first; see
  [Limits](#limits).
- Not for a model that will go through a humanoid auto-rigger: that is a
  provider route with its own eligibility rules.

## Procedure

1. **Weld a working copy by position.** Generated meshes split vertices at
   every UV seam, so heat cannot cross them and each seam tears when bent.
   Weight a copy welded by position, then give every render vertex the
   weights of its welded twin. Never weld the render mesh: it keeps its
   UVs and normals.
2. **List the loose shells** (connected components): teeth, claws, vines,
   decoration. Each needs an owner decided on purpose (rule 4). The biggest
   loose shell is usually an accessory, not the body.
3. **Put the armature on the model's joints, not the proxy's.** Mark each
   joint on the sculpt (shoulder, elbow, jaw hinge) and build bones there.
   The engine's rig has its own rest proportions; record the transform from
   each sculpt joint to the engine's rest joint and bake the mesh into the
   engine's rest pose once, in Blender, after weighting. The skin's binds
   and the engine's rest must be the same pose or every frame is offset.
4. **Weights: automatic first, then four cleanups.** Run Blender's
   automatic weights (bone heat) on the welded copy. Then:
   - *Near controls only.* Each vertex keeps only controls within two
     joints of its strongest one, before and after smoothing. Heat leaks a
     few percent between limbs sculpted close together (2 to 6% of toe
     weight on a hand's claws stretched them 2.4 to 3.6x).
   - *Rigid parts are rigid.* Teeth, claws, jaw plates, armour: every
     vertex of the shell 100% on one control.
   - *Loose shells follow the surface they sit on.* An accessory shell
     takes the weights of the nearest body vertex, so it stays attached
     when the body bends, plus a share (rising to 0.9 toward its tip) on
     its own sway control. A shell left on one rigid control floats off
     the body the first time the spine bends.
   - *Smooth a little.* Two rounds of neighbour smoothing. Eight rounds
     was measurably worse (it re-spreads the leaks).
   Normalise and cap at four influences last.
5. **Hinged parts rest closed.** A mouth sculpted open stays open unless
   the bake closes it about its hinge. Close it in the rest pose, record
   the sculpt's gap, and expose rest gap and full gape as tunable values.
   Neither jaw may close past the other.
6. **Check every end control's frame against the mesh.** Boxes hide a
   wrong roll; a real hand does not. Render one planted pose per hand,
   foot and head and look for the palm side, the claw direction and the
   thumb side. The pilot's "walking on its wrists" was a 180 degree roll in
   the planted-hand convention that predated the skin.
7. **Keep the old body behind a switch** so before and after can be
   recorded from the same commit with the same moves.

## Measure, then look

Run the same recordings before and after and compare numbers before
opinions:

- **Stretch**: per triangle, longest edge ratio against rest; report the
  worst and which control owns it. Under 2x is clean, 2 to 3x shows only in
  extremes, over 3x reads as rubber.
- **Tears**: gap between vertices that share a position at rest.
- **Folds**: triangles whose normal flipped against rest.
- **Contacts**: sink, slide and hover for every part that stands on
  something (count paws that carry weight as feet).
- **Speed**: degrees per second per joint; a spike is a flip.

Then make contact sheets from a camera chosen for the moving part (front
and side of the acting limb, every second frame through the action). A
default three-quarter camera hid a shoulder flip for a whole review round.
The user judges in the model viewer before the game.

## Motion rules that made it read as fluid

These are about the performance, not the weights. They apply to any
character posed in the engine from gameplay state.

- **Act the wind-up; be exact at the hit.** Gameplay moves a hit point
  (a head, a fist) on its own simple path. Do not drag a long body after
  that point for the whole move. Let the body play its own coil in the
  wind-up, then blend onto the gameplay point so the two agree from just
  before the hit frame to the end of the active window. Use an explicit
  weight for "how exact is the hitting part now" and ease it back after.
- **The root goes with the reach.** A long chain reaching far from a fixed
  root buckles sideways or folds through the floor. Move the root (hips)
  toward a pounce pose first and keep a minimum distance from root to tip.
- **Choose the wind-up for the limb's length.** A hand cocked beside the
  head works on human proportions. On long arms it folds the elbow up over
  the shoulder. Draw a long arm back low at the flank with the elbow
  straight behind, and join the gameplay path early in the throw.
- **Check the bend direction with the perpendicular.** The elbow goes
  toward the pole's component perpendicular to the shoulder-to-hand line,
  not toward the pole. Work it out before rendering.
- **Hold a contact until the body is past it.** A caught ledge, a planted
  hand: latch it. If the test that found the contact stops passing as the
  body moves (the lip is now below the hips), the limb falls back to its
  search pose and reads as a second reach.
- **Planted hands and feet lie flat and stay put; free ones clear the
  ground.** The lower a free wrist, the flatter the hand, so long claws
  trail instead of stabbing down. A reaching limb never goes below where it
  stands when planted.
- **The grabber goes to the target.** When a catch volume is bigger than
  the part that visibly catches, never place the target in the mouth or
  hand on the catch tick. Finish the motion onto the target over about
  0.1 s (cap how far past its path the part may go), keep the target where
  it was caught meanwhile, then ease both back to the hold pose. Catch
  timing and damage stay on the gameplay tick.
- **Appendages get a spring, not a rigid parent.** A stalk follows its
  base with a damped spring (stiffness about 60, damping about 7), the lag
  capped at under half its length and scaled by a slider. It settles
  upright; it does not hang or swing forever.
- **Cap angular speed per joint** and ease every pole and aim between
  moves, so no joint flips in one frame.

## Joint and contact limits

A pose solved fresh each frame from gameplay targets has no memory, so any
jump in a target is a pop on screen. Treat the body as a machine's arm is
treated: every joint and every end has a range and a top speed, and the
solver's answer is clamped to them every frame. Each of these was a defect
a reviewer found by eye before it existed:

| Limit | Rule | What it stopped |
| --- | --- | --- |
| Limb speed | Upper and lower segment directions turn no faster than a cap against their parent (about 1100 deg/s; 1.8x in a thrown punch) | A limb crossing the body in one frame at a phase change |
| Hinge roll | An elbow or knee hinge rolls about its upper segment no faster than about 540 deg/s | Elbow and knee flips near a straight limb or a changed pole |
| Wrist and ankle speed | The end block turns against its limb no faster than about 1400 deg/s | A palm turning a quarter turn when its job changed |
| Root speed | The hips move against the character's own position no faster than a cap | One frame of hips a metre low at a catch, folding the feet into the ground |
| Joint range | The shoulder swings back no more than about 50 degrees from down the side | An elbow held level behind the back in a wind-up |
| Self clearance | Elbow and mid-forearm keep a radius from the trunk; the elbow swings out round the shoulder-to-hand line, the hand stays | A forearm through the hips in a low punch |
| Solid floor | After the solve, neither end of a sole is under the ground; the ankle rises and the knee takes it up | Feet standing on their toes in the floor when the hips drop |
| Own side | A foot in the air stays on its side of the body | Shins crossing in a step out of a turn |
| Foot heading | A flat foot points where the hips point (a little toe-out), never where the knee pole points | Toes splayed 70 degrees on top of a climb, hocks crossed behind while the shins stayed apart |
| Limb against limb | Wrist, palm and mid-claw points keep a radius from the thigh and shin of the last frame; push outward, re-solve, and turn the paw about the wrist if the claws still reach in. Off during a strike and a held contact | Forearms and claws inside the haunches on top of a climb |
| Head out of the way | On a wall the head looks up the wall, not at it | Claws through the face on each reach |
| Dead body | Knees keep facing the body's front; the whole body is lifted so its lowest point is on the floor | Legs rolled 170 degrees at the hips to "clear" the ground, head 1.8 m under it |

Rules for applying them:

- **A held contact is exempt, a new one is not.** A paw that has stood
  planted for a moment is not speed limited (the contact comes first). One
  that was put down this frame still is, or the arm snaps to it.
- **Limits are in the parent's frame**, so a turning body does not use them up.
- **Reach for a contact only when it is in reach.** Coming down from a
  jump, keep the limbs stretched ahead until the ground is within a limb's
  length. Aiming at it from high up swings them under the body and out again.
- **When the game moves the whole character** (a death topple that turns
  the root), solve the floor in the turned frame: "up" is the world's up
  brought into the character's frame, not the character's own Y.
- **Scale by the character's own lengths** (leg length, arm length), never
  by a bare size factor: offsets tuned in "sizes" were half what was meant
  on this model.
- **A climb faster than a foot can step is a scramble.** Drive the feet
  from the height gained (drawn up, knees out, soles on the face, kicking
  in turn) instead of stepping to holds the body has already passed.

## The gate before the viewer

The user should never be the one to find a flip. Split the checker's
findings in two:

- **Blockers** stop a take being sent at all: torn seams, a hit point
  missed at the hit, limbs through each other or the trunk, skin of one
  part inside another, any skin but a foot under the floor, a joint past
  its range, a flat foot turned far from the hips' heading, joint speed,
  hinge roll speed, and a foot deep in the floor. These are the findings a
  viewer sees at once.
- **Notes** are measured and ratcheted against a baseline (they may not get
  worse): stretch, fold counts, small slides and sinks.

Never send a take with a blocker "marked as failing". Twice on the pilot a
flagged flip was sent with a note attached and came back as the user's
first comment; the note did not save the round. If a blocker cannot be
fixed, hold that move and say so in one line. When the baseline is re-taken
after an improvement, list what moved into it.

Calibrate each blocker on moves the user has already approved: a limit that
fails an approved move is too tight, and one that passes a move the user
rejected is missing or too loose. Add a check for every defect the user
finds that the checker did not.

Set the note limits the same way. Limits copied from another body (the
pilot started with a two-legged giant's) left 17 of 19 moves "known
failing" after the user had approved most of them, and the list stopped
meaning anything. Set from the approved moves, 13 passed outright and the
6 left were each a real defect worth fixing.

### Checks that see the mesh, not the skeleton

Capsules between joints are thinner than the body. On the pilot a haunch
was 1.5 m front to back with a 0.5 m capsule, and claws and a head reach
far past theirs, so limbs sat inside each other for whole moves and the
capsule check passed. The user found three such defects in one look. What
closed the gap:

- **Mesh overlap.** On the posed skin, test each part's vertices against
  the surface of the rest of the body (generalised winding number; cluster
  the far triangles, prefilter candidates by distance and by being behind
  the nearest normal). Subtract what already overlaps at rest. Deeper than
  about 1 % of body height for 6 frames or more is a blocker; shorter is a
  note, because a fast strike brushes past itself.
- **Joint range.** Swing and roll of every limb joint from rest, with a
  limit per joint. Speed checks pass a pose that is wrong but still.
- **Dead and fallen frames count.** Skipping them hid the worst pose in
  the set.
- **Everything against the floor**, not only the feet.

A checker that only measures what has gone wrong before will miss the next
kind of defect. When the user finds one by eye, first write the check that
fails on that recording, then fix the move.

### The loop and when to stop

An agent runs record, check, fix one cause, record again, and the user sees
a move only after it passes. Without a stop rule the loop thrashes: the
pilot spent about 20 rounds on one clearance problem, trading one move's
pass for another's fail. Stop and report when:

- one move has had 5 rounds without a pass,
- 2 rounds in a row did not improve the blocked number, or
- a fix for one move breaks a move that had passed.

The report gives the blocked number per round, what was tried, and the
options: re-pose, change the move's design, or ask the user to accept it.
After the last fix, run the whole move list again, then look at a contact
sheet of each changed move before sending.

### Leniency

Loosen a limit for one move with a written reason, never for the whole
character to get a failing move through. A brief overlap in a strike is a
note; a body lying dead is exempt from standing-feet checks but not from
the floor or joint range; a defect of the mesh is counted once on the body
and fixed there; a grab that must enter the held thing exempts that pair
for that move. Raising a limit because the agent could not fix the move is
not leniency: that is the stop rule, and the choice is the user's.

## Limits

- **Linear blend skinning smears at extremes.** Arms straight overhead on
  a mesh modelled arms-down collapse the shoulder whatever the weights.
  That is fixed with a corrective shape or a helper bone, or by keeping
  the move inside the range, not by re-weighting.
- **Regenerating in a different rest pose is a different experiment.** It
  helps only the defect it targets. Limbs held away from the body fix
  fused surfaces and weight bleed between them; they do not fix overhead
  smear, and a new generation changes proportions and colour. Judge such a
  test on the defect it was meant to fix, with the same weighting method
  on both sides.
- **Fused limbs.** Where the generator merged a hand into a thigh, heat
  treats them as one surface. Tear the surface there first (and cap the
  holes), or regenerate with the limbs apart, before weighting.
- **Twist** along a forearm or thigh needs a twist bone or split weights;
  one control per segment will candy-wrap past about 90 degrees.

## Checklist

- [ ] Working copy welded by position; render mesh untouched
- [ ] Loose shells listed, each with an owner
- [ ] Bones on the sculpt's joints; mesh baked to the engine's rest
- [ ] Automatic weights, then near-controls, rigid parts, shells, 2 smooths
- [ ] Hinged parts closed at rest, gap and gape tunable
- [ ] One planted-pose render per hand, foot and head
- [ ] Old body behind a switch; same recordings before and after
- [ ] Stretch, tears, folds, contacts and joint speed compared
- [ ] Joint, speed, clearance and floor limits on; held contacts exempt
- [ ] Mesh overlap, joint range and whole-body floor checks on, dead frames included
- [ ] No blocker on any take sent; held moves named
- [ ] Loop stopped and reported at 5 rounds or 2 without progress
- [ ] Contact sheets from a camera per acting limb
- [ ] User looked in the viewer before the game
