## Two-bone IK for a limb of two rigid blocks (upper and lower), with the
## bend hint named for what it is. A hint passed as a point where the
## solver expects a direction (or the reverse) bends every elbow and knee
## the wrong way, and the symptoms (odd elbows, legs behind the back, a
## wobble at the end of a punch) look like tuning problems. Pick the
## function by the kind of hint you hold, and run selftest.gd, which checks
## that a forward reach bends the elbow down and back.
##
## Continuity (references/block-motion-rules.md, rule 9): keep each limb's
## last hinge and pass it to hinge_axis() so an elbow never swaps sides
## when the hand passes close to the shoulder.
extends RefCounted


## The limb from `root` (shoulder or hip) to `target`, the middle joint
## bending toward the world point `bend_point`. Returns [middle, end]; the
## end stops short of the target when it is out of reach.
static func solve_toward_point(root: Vector3, target: Vector3, l1: float, l2: float, bend_point: Vector3) -> Array:
	return solve_toward_direction(root, target, l1, l2, bend_point - root)


## The same limb, the middle joint bending toward the direction `bend_dir`
## (from the root, e.g. "back and down" for an elbow).
static func solve_toward_direction(root: Vector3, target: Vector3, l1: float, l2: float, bend_dir: Vector3) -> Array:
	var d := target - root
	var dist := clampf(d.length(), maxf(absf(l1 - l2), 0.001) + 0.001, l1 + l2 - 0.001)
	var dir := d.normalized() if d.length() > 0.0001 else Vector3.DOWN
	var end := root + dir * dist
	var x := (l1 * l1 + dist * dist - l2 * l2) / (2.0 * dist)
	var h := sqrt(maxf(l1 * l1 - x * x, 0.0))
	var p := bend_dir - dir * bend_dir.dot(dir)
	if p.length() < 0.001:
		p = dir.cross(Vector3.RIGHT if absf(dir.x) < 0.9 else Vector3.FORWARD)
	return [root + dir * x + p.normalized() * h, end]


## The limb's hinge axis (the axis both blocks bend about) from the upper
## and lower directions. Where the limb is nearly straight the bend gives
## no axis, so it falls back to `prev` (last frame's hinge), then to the
## axis implied by `bend_dir`. It never flips sign against `prev`.
static func hinge_axis(upper: Vector3, lower: Vector3, bend_dir: Vector3, prev := Vector3.ZERO) -> Vector3:
	var ref := prev if prev.length() > 0.5 else upper.cross(bend_dir)
	var h := upper.cross(lower)
	if h.length() < 0.08:
		h = ref
	elif ref.length() > 0.001 and h.dot(ref) < 0.0:
		h = -h
	if h.length() < 0.001:
		h = Vector3.RIGHT
	return h.normalized()


## A block's basis with Y along the block (`y`) and X on the hinge.
static func block_basis(y: Vector3, hinge: Vector3) -> Basis:
	y = y.normalized()
	var x := hinge - y * hinge.dot(y)
	if x.length() < 0.001:
		x = y.cross(Vector3.FORWARD if absf(y.dot(Vector3.FORWARD)) < 0.9 else Vector3.RIGHT)
	x = x.normalized()
	return Basis(x, y, x.cross(y))
