## Whole-chain IK for rigid blocks (references/block-motion-rules.md, rule 4).
##
## A chain is a list of joint points from a root (a pelvis) to an end (a
## skull or a hand), each segment a rigid block of fixed length. `reach`
## moves the end to a target with FABRIK (Aristidou and Lasenby 2011):
## every segment shares the motion, none stretches, and each joint may turn
## away from the authored pose only within its own cone (a stiff spine, a
## loose neck). The root may shift inside a box when the chain alone cannot
## reach, the way a body steps its hips in to bite.
##
## Nothing here knows about any particular creature, and it runs on each
## screen from that screen's pose: it adds no network data.
extends RefCounted


## Moves the end of the chain `pts` (the authored pose, joint points from
## root to end) to `target`. `lens[i]` is the rigid length of segment i
## (pts[i] to pts[i+1]); `cones[i]` the most segment i may turn away from
## the authored pose relative to its parent (radians; segment 0 relative to
## its authored direction). The root moves from pts[0] by at most
## `root_min`..`root_max` per axis. A straight chain reaching along its
## own line folds toward `bend_hint` (any side when zero). Returns the
## solved points.
static func reach(pts: PackedVector3Array, target: Vector3, lens: PackedFloat32Array, cones: PackedFloat32Array,
		root_min := Vector3.ZERO, root_max := Vector3.ZERO, iters := 12, tol := 0.01, bend_hint := Vector3.ZERO) -> PackedVector3Array:
	var n := pts.size()
	var p := pts.duplicate()
	if n < 2:
		return p
	var anchor := pts[0]
	var prior_dir := PackedVector3Array()
	prior_dir.resize(n - 1)
	for i in n - 1:
		prior_dir[i] = _dir(pts[i], pts[i + 1])
	# A straight chain reaching for a point on its own line stays straight
	# through every pass (nothing gives it a side to bend to). Seed a small
	# bend toward `bend_hint` (or any side) so it can fold.
	if n > 2:
		var line := prior_dir[0]
		var straight := true
		for i in n - 1:
			straight = straight and prior_dir[i].dot(line) > 0.9999
		var to := target - pts[0]
		if straight and to.length() > 0.0001 and absf(to.normalized().dot(line)) > 0.9999:
			var side := bend_hint - line * bend_hint.dot(line)
			if side.length() < 0.001:
				side = line.cross(Vector3.RIGHT if absf(line.x) < 0.9 else Vector3.FORWARD)
			side = side.normalized()
			for i in range(1, n - 1):
				p[i] += side * lens[i - 1] * 0.05
	for it in iters:
		# Backward: the end on the target, each joint pulled after it.
		p[n - 1] = target
		for i in range(n - 2, -1, -1):
			p[i] = p[i + 1] + _dir(p[i + 1], p[i]) * lens[i]
		# The root: back toward its anchor, within the box it may shift in.
		var off := p[0] - anchor
		p[0] = anchor + Vector3(clampf(off.x, root_min.x, root_max.x), clampf(off.y, root_min.y, root_max.y), clampf(off.z, root_min.z, root_max.z))
		# Forward: from the root out, each segment kept rigid and inside its
		# cone around the authored pose (carried by its parent's turn).
		var turn := Quaternion.IDENTITY
		for i in n - 1:
			var d := _dir(p[i], p[i + 1])
			var ref := (turn * prior_dir[i]).normalized()
			d = cone_clamp(d, ref, cones[i])
			p[i + 1] = p[i] + d * lens[i]
			turn = Quaternion(prior_dir[i], d) if prior_dir[i].dot(d) > -0.999 else turn
		if p[n - 1].distance_to(target) < tol:
			break
	return p


## `d` turned toward `ref` until it lies within `cone` radians of it.
static func cone_clamp(d: Vector3, ref: Vector3, cone: float) -> Vector3:
	var a := d.angle_to(ref)
	if a <= cone:
		return d
	var axis := ref.cross(d)
	if axis.length() < 0.0001:
		axis = ref.cross(Vector3.RIGHT if absf(ref.x) < 0.9 else Vector3.UP)
	return ref.rotated(axis.normalized(), cone).normalized()


## The authored directions `dirs` (a chain from `root`) swung toward
## `target`: the turn that would point the chain's end at the target, each
## segment taking its share `weights[i]` of it (proximal blocks less).
static func aim(root: Vector3, dirs: PackedVector3Array, lens: PackedFloat32Array, target: Vector3, weights: PackedFloat32Array) -> PackedVector3Array:
	var tip := root
	for i in dirs.size():
		tip += dirs[i].normalized() * lens[i]
	var a := tip - root
	var b := target - root
	if a.length() < 0.001 or b.length() < 0.001 or a.normalized().dot(b.normalized()) < -0.999:
		return dirs
	var q := Quaternion(a.normalized(), b.normalized())
	var out := PackedVector3Array()
	for i in dirs.size():
		out.append((Quaternion.IDENTITY.slerp(q, weights[i]) * dirs[i]).normalized())
	return out


## A chain of points from `root`, each segment `lens[i]` long along
## `dirs[i]` (the authored pose).
static func build(root: Vector3, dirs: PackedVector3Array, lens: PackedFloat32Array) -> PackedVector3Array:
	var out := PackedVector3Array([root])
	for i in dirs.size():
		out.append(out[i] + dirs[i].normalized() * lens[i])
	return out


## A block's frame from its axis `y` (the segment) and a side direction
## `side` (projected square to it): X side, Y along, Z = X x Y.
static func frame(y: Vector3, side: Vector3) -> Basis:
	y = y.normalized()
	var x := side - y * side.dot(y)
	if x.length() < 0.001:
		x = y.cross(Vector3.FORWARD if absf(y.dot(Vector3.FORWARD)) < 0.9 else Vector3.UP)
	x = x.normalized()
	return Basis(x, y, x.cross(y))


## Continuity (rule 9): eases a freshly solved chain `now` from last
## frame's solve `prev`, so a solve that lands on a nearby but different
## shape does not jump. Each segment's direction turns toward its new
## direction at `rate` (1/s, about 12 to 20) and keeps its rigid length;
## the root follows `now` exactly. Returns `now` when `prev` is empty or a
## different size (first frame, or the chain was rebuilt).
static func ease_from(prev: PackedVector3Array, now: PackedVector3Array, lens: PackedFloat32Array, rate: float, delta: float) -> PackedVector3Array:
	if prev.size() != now.size() or now.size() < 2:
		return now
	var k := 1.0 - exp(-rate * delta)
	var out := PackedVector3Array([now[0]])
	for i in now.size() - 1:
		var a := _dir(prev[i], prev[i + 1])
		var b := _dir(now[i], now[i + 1])
		var d := a.slerp(b, k) if a.dot(b) > -0.999 else b
		out.append(out[i] + d.normalized() * lens[i])
	return out


static func _dir(a: Vector3, b: Vector3) -> Vector3:
	var d := b - a
	return d / d.length() if d.length() > 0.00001 else Vector3.UP
