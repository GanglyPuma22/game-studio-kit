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
- [ ] Contact sheets from a camera per acting limb
- [ ] User looked in the viewer before the game
