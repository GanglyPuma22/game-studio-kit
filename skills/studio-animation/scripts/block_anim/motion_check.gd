## Checks a block-built animation against references/block-motion-rules.md, frame
## by frame, and sums each rule up per clip: stretch, joint gaps, joint
## limits, hinges bending the wrong way, joints flipping between frames,
## contacts sliding, steps and shuffles, balance, ground, wall and body
## penetration, pops and how far blocks drift from their gameplay pieces.
##
## Generic: a creature hands over its blocks (bind transforms, parents,
## boxes) and its rig description (limits, hinges, contacts, pairs that
## must not overlap, soft blocks; see setup_rig()). Used by recordings and
## tests; the game never runs it. Run selftest.gd after changing it: the
## checker has golden poses with known answers.
extends RefCounted

var names: Array = []
var parent: PackedInt32Array
var limit_deg: PackedFloat32Array   # per block: how far it may turn from rest relative to its parent
var soft: Dictionary = {}           # blocks allowed to scale
var bind: Array = []                # Transform3D per block (body frame)
var box_c: Array = []               # per block: box centre in its own frame (or null)
var box_h: Array = []               # per block: box half size
var contacts: PackedInt32Array      # blocks that touch the ground
var pairs: Array = []               # [a, b] that must not overlap
## Rule 8b (no box through another box): how deep two boxes may overlap,
## as a share of the thinner box's smallest half size. Blocks one or two
## joints apart (a hand and its upper arm, both thighs off the pelvis)
## overlap round the joint they share; any other pair barely may. Pairs
## that already overlap at rest may go that deep plus the margin.
var joint_share := 0.6
var body_share := 0.25
## And a least depth (m) that counts, for small bodies whose blocks are
## thin (a person's fingers resting on a thigh are not a pass-through).
var floor_m := 0.0
var _hops: Dictionary = {}          # "a_b" -> joints between the two blocks (1, 2, or 3 = farther)
var _rest_depth: Dictionary = {}    # "a_b" -> overlap depth at rest (m)
## Two joints apart (an upper arm and the chest it hangs from by the
## collarbone, both thighs off the hips), a limb's end at that joint turns
## inside the other block: that end, about a limb's thickness, is the
## joint's and does not count. "a_b" -> [centre a, half a, centre b, half b].
var _joint_cut: Dictionary = {}
## Frames to leave out (the body was just placed somewhere new).
var skip := 0
var pad := 0.8                      # support area margin round each contact (m)
var touch := 0.35                   # a contact this close to the ground is down (m)

var _rel_bind: Array = []
var _prev1: Array = []
var _prev2: Array = []
var _prev_dt := 0.0
var _down_prev: Dictionary = {}
var _down_at: Dictionary = {}
var _lift_at: Dictionary = {}
var _prev_rel: Dictionary = {}
## Walls the body is against this frame: [[normal, c, top_y], ...] (see add()).
var walls: Array = []
## A step landing closer than this (m) to where it lifted counts as a shuffle.
var shuffle := 0.6
## Hinges (knees, elbows): block -> [axis, sign]. The axis is in the
## parent block's frame; the joint's signed turn about it must have `sign`
## (+1 or -1). A turn the other way past `hinge_slack` degrees is counted.
## A rig bound with the joint already bent gives that bend as "rest_deg"
## (positive, in the bending direction): the check is then from straight.
var hinges: Dictionary = {}
var hinge_slack := 5.0
## Event thresholds: block acceleration (m/s²), planted slide (m/s) and a
## joint's turn rate (deg/s; a single-frame elbow swap shows here).
var pop_event := 1500.0
var slide_event := 1.0
var flip_event := 900.0
var r := {}
## Debugging: every rule break this clip, [frame, rule, block, amount]
## (capped per rule).
var events: Array = []
var _ev_n := {}


func setup(p_names: Array, p_parent: PackedInt32Array, p_limits: PackedFloat32Array, p_bind: Array,
		p_box_c: Array, p_box_h: Array, p_contacts: PackedInt32Array, p_pairs: Array, p_soft: Array) -> void:
	names = p_names
	parent = p_parent
	limit_deg = p_limits
	bind = p_bind
	box_c = p_box_c
	box_h = p_box_h
	contacts = p_contacts
	pairs = p_pairs
	soft = {}
	for b in p_soft:
		soft[b] = true
	_rel_bind.resize(bind.size())
	for i in bind.size():
		if parent[i] >= 0:
			_rel_bind[i] = (bind[parent[i]] as Transform3D).affine_inverse() * bind[i]
	# Pairs that already overlap at rest (the model hugs itself) may go
	# that deep; deeper is a block passing through another.
	_hops = {}
	_rest_depth = {}
	_joint_cut = {}
	for pr in pairs:
		var key := "%d_%d" % [pr[0], pr[1]]
		_hops[key] = _hop_count(pr[0], pr[1])
		if int(_hops[key]) == 2 and box_c[pr[0]] != null and box_c[pr[1]] != null:
			_joint_cut[key] = [_cut_root(pr[0], pr[1]), _cut_root(pr[1], pr[0])]
		var d := _depth(bind, Transform3D.IDENTITY, pr[0], pr[1])
		if d > 0.0:
			_rest_depth[key] = d
	reset()


## Block a's box ([centre, half]) for a pair two joints from block b: a
## limb (long along its own y, starting at its joint) hanging off b's
## child or off b's parent loses the end at that joint.
func _cut_root(a: int, b: int) -> Array:
	var c: Vector3 = box_c[a]
	var h: Vector3 = box_h[a]
	var thick := maxf(h.x, h.z)
	var shares_joint: bool = parent[a] >= 0 and (parent[parent[a]] == b or parent[a] == parent[b])
	if not shares_joint or h.y < 1.5 * thick:
		return [c, h]
	var lo := c.y - h.y
	var hi := c.y + h.y
	# The joint is at the block's origin (y = 0): cut from that end.
	if absf(lo) <= absf(hi):
		lo = maxf(lo, 0.0) + 1.2 * thick
	else:
		hi = minf(hi, 0.0) - 1.2 * thick
	if hi <= lo:
		return [c, Vector3(h.x, 0.0, h.z)]
	return [Vector3(c.x, (lo + hi) * 0.5, c.z), Vector3(h.x, (hi - lo) * 0.5, h.z)]


## How deep blocks a and b overlap with these transforms (in one frame),
## leaving out a joint's end where they meet two joints apart.
func pair_depth(a: int, ta: Transform3D, b: int, tb: Transform3D) -> float:
	if a > b:
		return pair_depth(b, tb, a, ta)
	if box_c[a] == null or box_c[b] == null:
		return 0.0
	var ca: Vector3 = box_c[a]
	var ha: Vector3 = box_h[a]
	var cb: Vector3 = box_c[b]
	var hb: Vector3 = box_h[b]
	var key := "%d_%d" % [a, b]
	if _joint_cut.has(key):
		var cut: Array = _joint_cut[key]
		ca = cut[0][0]
		ha = cut[0][1]
		cb = cut[1][0]
		hb = cut[1][1]
		if ha.y <= 0.0 or hb.y <= 0.0:
			return 0.0
	return box_depth(ta * ca, ta.basis, ha, tb * cb, tb.basis, hb)


## How far blocks a and b go into each other past their allowance.
func pair_over(a: int, ta: Transform3D, b: int, tb: Transform3D) -> float:
	var d := pair_depth(a, ta, b, tb)
	if d <= 0.0:
		return 0.0
	return maxf(0.0, d - allowed_depth(mini(a, b), maxi(a, b)))


## Every pair of boxed blocks that are not parent and child (those always
## meet at their joint): what "no_overlap": "all" asks for.
static func all_pairs(p_parent: PackedInt32Array, p_box_c: Array, exclude: Array = []) -> Array:
	var out: Array = []
	var n := p_parent.size()
	for a in n:
		for b in range(a + 1, n):
			if p_box_c[a] == null or p_box_c[b] == null:
				continue
			if p_parent[a] == b or p_parent[b] == a:
				continue
			var skip := false
			for ex in exclude:
				if (ex[0] == a and ex[1] == b) or (ex[0] == b and ex[1] == a):
					skip = true
			if not skip:
				out.append([a, b])
	return out


## Joints between blocks a and b along the tree (1 = parent and child, 2 =
## grandparent or siblings), capped at 3.
func _hop_count(a: int, b: int) -> int:
	var up_a := {a: 0}
	var x := a
	var k := 0
	while parent[x] >= 0 and k < 3:
		x = parent[x]
		k += 1
		up_a[x] = k
	x = b
	k = 0
	while k <= 3:
		if up_a.has(x):
			return mini(3, int(up_a[x]) + k)
		if parent[x] < 0:
			break
		x = parent[x]
		k += 1
	return 3


## How deep blocks a and b may overlap before it counts (m).
func allowed_depth(a: int, b: int) -> float:
	var key := "%d_%d" % [a, b]
	var ha: Vector3 = box_h[a]
	var hb: Vector3 = box_h[b]
	var thin := minf(minf(ha.x, minf(ha.y, ha.z)), minf(hb.x, minf(hb.y, hb.z)))
	var share := joint_share if int(_hops.get(key, 3)) <= 2 else body_share
	var allow := share * thin
	if _rest_depth.has(key):
		allow = maxf(allow, float(_rest_depth[key]) + body_share * thin)
	# A graze too slight to see is not a pass-through.
	return allow + maxf(0.1 * thin, floor_m)


## Same as setup() but limits, contacts, pairs and soft blocks come from a
## rig description (a Dictionary, e.g. parsed from the Kit's
## templates/block-rig.json), naming blocks instead of numbering them.
## Blocks the description leaves out get `default_limit` degrees.
func setup_rig(p_names: Array, p_parent: PackedInt32Array, p_bind: Array, p_box_c: Array, p_box_h: Array, desc: Dictionary) -> void:
	unknown = []
	var idx := {}
	for i in p_names.size():
		idx[p_names[i]] = i
	var lim := PackedFloat32Array()
	lim.resize(p_names.size())
	lim.fill(float(desc.get("default_limit", 45.0)))
	var jl: Dictionary = desc.get("limits", {})
	for k in jl:
		if _known(idx, k):
			lim[idx[k]] = float(jl[k])
	var con := PackedInt32Array()
	for k in desc.get("contacts", []):
		if _known(idx, k):
			con.append(idx[k])
	var prs: Array = []
	var no: Variant = desc.get("no_overlap", [])
	if no is String and no == "all":
		# Every pair but parent and child, less the pairs named in "overlap_ok".
		var ex: Array = []
		for pr in desc.get("overlap_ok", []):
			if _known(idx, pr[0]) and _known(idx, pr[1]):
				ex.append([idx[pr[0]], idx[pr[1]]])
		prs = all_pairs(p_parent, p_box_c, ex)
	else:
		for pr in no:
			if _known(idx, pr[0]) and _known(idx, pr[1]):
				prs.append([idx[pr[0]], idx[pr[1]]])
	var sf: Array = []
	for k in desc.get("soft", []):
		if _known(idx, k):
			sf.append(idx[k])
	hinges = {}
	var hg: Dictionary = desc.get("hinges", {})
	for k in hg:
		if _known(idx, k):
			var a: Array = hg[k].axis
			hinges[idx[k]] = [Vector3(a[0], a[1], a[2]).normalized(), signf(float(hg[k].get("sign", 1.0))), float(hg[k].get("rest_deg", 0.0))]
	setup(p_names, p_parent, lim, p_bind, p_box_c, p_box_h, con, prs, sf)


## Names in a rig description that the rig does not have (typos, renamed
## blocks), collected by setup_rig(); empty when the two agree.
var unknown: Array = []


func _known(idx: Dictionary, k) -> bool:
	if idx.has(k):
		return true
	unknown.append(k)
	push_warning("block rig description names an unknown block: %s" % k)
	return false


## The shortest turn of `q` in degrees (0..180). Quaternion.get_angle()
## can return more than 180 for the same rotation (q and -q), which once
## sent a whole tuning round after limits that were not broken.
static func shortest_turn_deg(q: Quaternion) -> float:
	return rad_to_deg(2.0 * acos(minf(1.0, absf(q.normalized().w))))


## The signed turn of `q` about `axis` (degrees, -180..180), taking the
## short way round.
static func signed_turn_deg(q: Quaternion, axis: Vector3) -> float:
	q = q.normalized()
	if q.w < 0.0:
		q = -q
	return rad_to_deg(2.0 * atan2(Vector3(q.x, q.y, q.z).dot(axis.normalized()), q.w))


func reset() -> void:
	events = []
	_ev_n = {}
	_prev1 = []
	_prev2 = []
	_prev_dt = 0.0
	_down_prev = {}
	_down_at = {}
	_lift_at = {}
	_prev_rel = {}
	r = {"hinge_frames": 0, "hinge_over": 0.0, "hinge_at": "", "turn_rate": 0.0, "turn_at": "", "frames": 0, "stretch": 0.0, "gap": 0.0, "gap_at": "", "limit_frames": 0, "limit_over": 0.0, "limit_at": "",
		"slide": 0.0, "down_time": 0.0, "slide_max": 0.0, "ground": 0.0, "ground_at": "",
		"wall": 0.0, "wall_at": "", "wall_frames": 0, "steps": 0, "slow_steps": 0, "shuffles": 0, "self_frames": 0, "self_at": "", "self_depth": 0.0, "self_pairs": {}, "self_max": {}, "slow_frames": 0, "unbalanced": 0, "air_frames": 0,
		"pop": 0.0, "pop_at": "", "drift": {}}


## One frame: `pose` per block (body frame), the body's world transform,
## the ground height, frame time, whether the body is moving slowly (so
## balance applies) and `drift` (part name -> m from its gameplay piece).
func add(pose: Array, gx: Transform3D, ground_y: float, dt: float, slow: bool, drift: Dictionary) -> void:
	if skip > 0:
		skip -= 1
		_prev1 = []
		_prev2 = []
		_prev_dt = 0.0
		_down_prev = {}
		_prev_rel = {}
		return
	r.frames += 1
	var n := pose.size()
	var worst_limit := 0.0
	var worst_limit_at := ""
	var worst_hinge := 0.0
	var worst_hinge_at := ""
	var centres: Array = []
	centres.resize(n)
	var mass := 0.0
	var com := Vector3.ZERO
	for i in n:
		var t: Transform3D = pose[i]
		# Rule 1: rigid blocks keep their scale.
		if not soft.has(i):
			var sc := t.basis.get_scale()
			var st := maxf(absf(sc.x - 1.0), maxf(absf(sc.y - 1.0), absf(sc.z - 1.0)))
			r.stretch = maxf(r.stretch, st)
		var p := parent[i]
		if p >= 0:
			# Rule 2: the joint sits on its parent's joint.
			var pt: Transform3D = pose[p]
			var want: Vector3 = pt * (_rel_bind[i] as Transform3D).origin
			var gap := want.distance_to(t.origin)
			if gap > r.gap:
				r.gap = gap
				r.gap_at = names[i]
			# Rule 3: within its limit from rest, relative to its parent.
			var rel := (pt.basis.orthonormalized().inverse() * t.basis.orthonormalized()) * (_rel_bind[i] as Transform3D).basis.orthonormalized().inverse()
			var rq := rel.get_rotation_quaternion()
			var ang := shortest_turn_deg(rq)
			# Hinges bend one way only (a knee never bends forward).
			if hinges.has(i):
				# Measured from straight: the bind's own bend (rest_deg, in the
				# hinge's bending direction) counts, so a rig bound with bent
				# knees can straighten them without reading as bent backwards.
				var hj: Array = hinges[i]
				var rest_deg: float = float(hj[2]) if hj.size() > 2 else 0.0
				var wrong: float = -float(hj[1]) * signed_turn_deg(rq, hj[0]) - rest_deg - hinge_slack
				if wrong > 0.0:
					_ev("hinge", names[i], wrong)
				if wrong > worst_hinge:
					worst_hinge = wrong
					worst_hinge_at = names[i]
			# Continuity: how fast the joint turned since last frame.
			if _prev_rel.has(i) and dt > 0.0:
				var rate := shortest_turn_deg((_prev_rel[i] as Quaternion).inverse() * rq) / dt
				if rate > flip_event:
					_ev("flip", names[i], rate)
				if rate > r.turn_rate:
					r.turn_rate = rate
					r.turn_at = "%s@%d" % [names[i], r.frames]
			_prev_rel[i] = rq
			var over := ang - limit_deg[i]
			if over > 0.0:
				_ev("limit", names[i], over)
			if over > worst_limit:
				worst_limit = over
				worst_limit_at = names[i]
		if box_c[i] != null:
			var c: Vector3 = gx * (t * (box_c[i] as Vector3))
			centres[i] = c
			var hv: Vector3 = box_h[i]
			var vol := hv.x * hv.y * hv.z
			com += c * vol
			mass += vol
	if worst_hinge > 0.0:
		r.hinge_frames += 1
		if worst_hinge > r.hinge_over:
			r.hinge_over = worst_hinge
			r.hinge_at = worst_hinge_at
	if worst_limit > 0.0:
		r.limit_frames += 1
		if worst_limit > r.limit_over:
			r.limit_over = worst_limit
			r.limit_at = worst_limit_at
	# Rule 8: nothing inside a wall the body is against (set per frame by
	# the rig, e.g. while climbing: [normal, c] for the face n.x = c, solid
	# on the side the normal points away from).
	var wall_worst := 0.0
	var wall_block := ""
	var wall_by := {}
	for w in walls:
		var wn: Vector3 = w[0]
		var wc: float = w[1]
		for i in n:
			if box_c[i] == null:
				continue
			for p in _wall_points(gx * (pose[i] as Transform3D), i, w):
				if w.size() > 2 and p.y > float(w[2]):
					continue   # above the wall's top
				var into: float = wc - wn.dot(p)
				if w.size() > 2:
					into = minf(into, float(w[2]) - p.y)   # the nearer face: a foot on the top is not in the wall
				if into > 0.05:
					wall_by[names[i]] = maxf(wall_by.get(names[i], 0.0), into)
				if into > wall_worst:
					wall_worst = into
					wall_block = names[i]
	if wall_worst > 0.05:
		for b in wall_by:
			_ev("wall", b, wall_by[b])
		r.wall_frames += 1
	if wall_worst > r.wall:
		r.wall = wall_worst
		r.wall_at = wall_block
	# Rule 8: nothing under the ground.
	for i in n:
		if box_c[i] == null:
			continue
		var low := _lowest(gx * (pose[i] as Transform3D), i)
		if ground_y - low > 0.05:
			_ev("ground", names[i], ground_y - low)
		if ground_y - low > r.ground:
			r.ground = ground_y - low
			r.ground_at = names[i]
	# Rule 8b: no block through another (beyond the joint they share).
	var self_hit := false
	for pr in pairs:
		var dep := _depth(pose, gx, pr[0], pr[1])
		if dep <= 0.0:
			continue
		var over := dep - allowed_depth(pr[0], pr[1])
		if over <= 0.0:
			continue
		var pn := "%s/%s" % [names[pr[0]], names[pr[1]]]
		self_hit = true
		_ev("self", pn, over)
		r.self_pairs[pn] = int(r.self_pairs.get(pn, 0)) + 1
		r.self_max[pn] = maxf(float(r.self_max.get(pn, 0.0)), over)
		if over > r.self_depth:
			r.self_depth = over
			r.self_at = pn
	if self_hit:
		r.self_frames += 1
	# Rule 6: planted contacts hold still.
	var support: Array = []
	for b in contacts:
		var low2 := _lowest(gx * (pose[b] as Transform3D), b)
		var down := low2 - ground_y < touch
		var c2: Vector3 = centres[b]
		if down:
			support.append(Vector2(c2.x, c2.z))
			r.down_time += dt
			if _down_prev.get(b, false):
				var prev: Vector3 = _down_at[b]
				var mv := Vector2(c2.x - prev.x, c2.z - prev.z).length()
				r.slide += mv
				if mv / maxf(dt, 0.001) > slide_event:
					_ev("slide", names[b], mv / maxf(dt, 0.001))
				r.slide_max = maxf(r.slide_max, mv / maxf(dt, 0.001))
		# Steps: a contact lifting off and landing again. A step that lands
		# within `shuffle` of where it lifted is a shuffle (a fidget, not a
		# step that goes anywhere).
		if _down_prev.get(b, false) and not down:
			r.steps += 1
			if slow:
				r.slow_steps += 1
			_lift_at[b] = _down_at[b]   # where it stood, not where the first airborne frame caught it
		elif down and not _down_prev.get(b, true) and _lift_at.has(b):
			var went := Vector2(c2.x - (_lift_at[b] as Vector3).x, c2.z - (_lift_at[b] as Vector3).z).length()
			if went < shuffle:
				r.shuffles += 1
				_ev("shuffle", names[b], went)
			_lift_at.erase(b)
		_down_prev[b] = down
		_down_at[b] = c2
	if support.is_empty():
		r.air_frames += 1
	# Rule 7: weight over the support area while slow.
	if slow and mass > 0.0:
		r.slow_frames += 1
		var cm := com / mass
		if support.is_empty() or _outside(Vector2(cm.x, cm.z), support) > pad:
			r.unbalanced += 1
	# Rule 9: no pops (block accelerations).
	if _prev2.size() == n and dt > 0.0 and _prev_dt > 0.0:
		for i in n:
			if centres[i] == null or _prev1[i] == null or _prev2[i] == null:
				continue
			# Velocities over each interval, so uneven frame times do not read as acceleration.
			var v1: Vector3 = ((centres[i] as Vector3) - (_prev1[i] as Vector3)) / dt
			var v0: Vector3 = ((_prev1[i] as Vector3) - (_prev2[i] as Vector3)) / _prev_dt
			var a: float = (v1 - v0).length() / (0.5 * (dt + _prev_dt))
			if a > pop_event:
				_ev("pop", names[i], a)
			if a > r.pop:
				r.pop = a
				r.pop_at = "%s@%d" % [names[i], r.frames]
	_prev2 = _prev1
	_prev1 = centres
	_prev_dt = dt
	for k in drift:
		var d: Dictionary = r.drift.get(k, {"max": 0.0, "sum": 0.0})
		d.max = maxf(d.max, float(drift[k]))
		d.sum += float(drift[k])
		r.drift[k] = d


func _ev(rule: String, block: String, amount: float) -> void:
	var n: int = _ev_n.get(rule, 0)
	_ev_n[rule] = n + 1
	if n < (600 if rule == "wall" else (3000 if rule == "self" else 40)):
		events.append([r.frames, rule, block, snappedf(amount, 0.01)])


## The clip's summary (rounded, ready for JSON).
func report() -> Dictionary:
	var out := {}
	var f := maxi(int(r.frames), 1)
	out.frames = r.frames
	out.stretch_pct = snappedf(r.stretch * 100.0, 0.1)
	out.joint_gap_m = snappedf(r.gap, 0.01)
	out.joint_gap_at = r.gap_at
	out.limit_frames_pct = snappedf(100.0 * r.limit_frames / f, 0.1)
	out.limit_over_deg = snappedf(r.limit_over, 0.1)
	out.limit_at = r.limit_at
	out.hinge_frames_pct = snappedf(100.0 * r.hinge_frames / f, 0.1)
	out.hinge_over_deg = snappedf(r.hinge_over, 0.1)
	out.hinge_at = r.hinge_at
	out.turn_rate_deg_s = snappedf(r.turn_rate, 1.0)
	out.turn_at = r.turn_at
	out.slide_m_per_s = snappedf(r.slide / maxf(r.down_time, 0.001), 0.01)
	out.slide_peak_m_per_s = snappedf(r.slide_max, 0.1)
	out.ground_m = snappedf(r.ground, 0.01)
	out.ground_at = r.ground_at
	out.self_overlap_pct = snappedf(100.0 * r.self_frames / f, 0.1)
	out.self_at = r.self_at
	out.self_depth_m = snappedf(r.self_depth, 0.01)
	var sp: Array = []
	for k in r.self_pairs:
		sp.append([k, r.self_pairs[k]])
	sp.sort_custom(func(x, y): return x[1] > y[1])
	var top := {}
	for e in sp.slice(0, 6):
		top[e[0]] = snappedf(100.0 * float(e[1]) / f, 0.1)
	out.self_pairs_pct = top
	# The deepest pairs, how far past their allowance (m).
	var dp: Array = []
	for k in r.self_max:
		dp.append([k, r.self_max[k]])
	dp.sort_custom(func(x, y): return x[1] > y[1])
	var deep := {}
	for e in dp.slice(0, 6):
		deep[e[0]] = snappedf(e[1], 0.01)
	out.self_deep_m = deep
	out.unbalanced_pct = snappedf(100.0 * r.unbalanced / maxi(int(r.slow_frames), 1), 0.1) if r.slow_frames > 0 else -1.0
	out.wall_m = snappedf(r.wall, 0.01)
	out.wall_at = r.wall_at
	out.wall_frames = r.wall_frames
	out.steps = r.steps
	out.slow_steps = r.slow_steps
	out.shuffles = r.shuffles
	out.airborne_pct = snappedf(100.0 * r.air_frames / f, 0.1)
	out.pop_m_s2 = snappedf(r.pop, 1.0)
	out.pop_at = r.pop_at
	var dr := {}
	for k in r.drift:
		dr[k] = {"max": snappedf(r.drift[k].max, 0.01), "mean": snappedf(r.drift[k].sum / f, 0.01)}
	out.drift_m = dr
	return out


func _corners(t: Transform3D, i: int) -> Array:
	var c: Vector3 = box_c[i]
	var h: Vector3 = box_h[i]
	var out: Array = []
	for sx in [-1.0, 1.0]:
		for sy in [-1.0, 1.0]:
			for sz in [-1.0, 1.0]:
				out.append(t * (c + Vector3(h.x * sx, h.y * sy, h.z * sz)))
	return out


## The points of block i to test against wall `w`: its corners, plus,
## for a wall with a top, where its edges cross the surface on which the
## depth behind the face equals the depth below the top. The deepest
## point (the larger of the two depths' minimum) lies at one of these, so
## a rotated box cutting a ledge's corner is not missed.
func _wall_points(t: Transform3D, i: int, w: Array) -> Array:
	var pts := _corners(t, i)
	if w.size() < 3:
		return pts
	var wn: Vector3 = w[0]
	var wc: float = w[1]
	var top: float = w[2]
	var out: Array = pts.duplicate()
	for a in 8:
		for bit in [1, 2, 4]:
			var b: int = a | bit
			if b == a:
				continue
			var pa: Vector3 = pts[a]
			var pb: Vector3 = pts[b]
			var fa: float = (wc - wn.dot(pa)) - (top - pa.y)
			var fb: float = (wc - wn.dot(pb)) - (top - pb.y)
			if (fa < 0.0) != (fb < 0.0):
				out.append(pa.lerp(pb, fa / (fa - fb)))
	return out


func _lowest(t: Transform3D, i: int) -> float:
	var lo := INF
	for p in _corners(t, i):
		lo = minf(lo, p.y)
	return lo


## How far `p` lies outside the convex hull of `pts` (0 inside).
static func _outside(p: Vector2, pts: Array) -> float:
	if pts.size() == 1:
		return p.distance_to(pts[0])
	var hull: PackedVector2Array = Geometry2D.convex_hull(PackedVector2Array(pts))
	if hull.size() >= 4 and Geometry2D.is_point_in_polygon(p, hull):
		return 0.0
	var best := INF
	for i in hull.size() - 1:
		best = minf(best, p.distance_to(Geometry2D.get_closest_point_to_segment(p, hull[i], hull[i + 1])))
	if hull.size() < 2:
		best = p.distance_to(pts[0])
	return best


## How deep the boxes of blocks a and b overlap (m): the least overlap
## along the separating-axis candidates, 0 or less when apart.
func _depth(pose: Array, gx: Transform3D, a: int, b: int) -> float:
	return pair_depth(a, gx * (pose[a] as Transform3D), b, gx * (pose[b] as Transform3D))


## Overlap depth of two oriented boxes (centre, basis with its scale, half
## size): 0 or less when apart.
static func box_depth(ca: Vector3, ba: Basis, ha0: Vector3, cb: Vector3, bb: Basis, hb0: Vector3) -> float:
	var ax := [ba.x.normalized(), ba.y.normalized(), ba.z.normalized()]
	var bx := [bb.x.normalized(), bb.y.normalized(), bb.z.normalized()]
	var sa := ba.get_scale()
	var sb := bb.get_scale()
	var ha: Vector3 = ha0 * sa
	var hb: Vector3 = hb0 * sb
	var axes: Array = ax + bx
	for i in 3:
		for j in 3:
			var c: Vector3 = (ax[i] as Vector3).cross(bx[j])
			if c.length() > 0.001:
				axes.append(c.normalized())
	var d := cb - ca
	var least := INF
	for l in axes:
		var ra := absf(ha.x * (ax[0] as Vector3).dot(l)) + absf(ha.y * (ax[1] as Vector3).dot(l)) + absf(ha.z * (ax[2] as Vector3).dot(l))
		var rb := absf(hb.x * (bx[0] as Vector3).dot(l)) + absf(hb.y * (bx[1] as Vector3).dot(l)) + absf(hb.z * (bx[2] as Vector3).dot(l))
		var o := ra + rb - absf(d.dot(l))
		if o <= 0.0:
			return 0.0
		least = minf(least, o)
	return least


## Do the boxes of blocks a and b overlap (separating axis test)?
func _overlap(pose: Array, gx: Transform3D, a: int, b: int) -> bool:
	if box_c[a] == null or box_c[b] == null:
		return false
	var ta: Transform3D = gx * (pose[a] as Transform3D)
	var tb: Transform3D = gx * (pose[b] as Transform3D)
	var ca: Vector3 = ta * (box_c[a] as Vector3)
	var cb: Vector3 = tb * (box_c[b] as Vector3)
	var ax := [ta.basis.x.normalized(), ta.basis.y.normalized(), ta.basis.z.normalized()]
	var bx := [tb.basis.x.normalized(), tb.basis.y.normalized(), tb.basis.z.normalized()]
	var sa := ta.basis.get_scale()
	var sb := tb.basis.get_scale()
	var ha: Vector3 = (box_h[a] as Vector3) * sa
	var hb: Vector3 = (box_h[b] as Vector3) * sb
	var axes: Array = ax + bx
	for i in 3:
		for j in 3:
			var c: Vector3 = (ax[i] as Vector3).cross(bx[j])
			if c.length() > 0.001:
				axes.append(c.normalized())
	var d := cb - ca
	for l in axes:
		var ra := absf(ha.x * (ax[0] as Vector3).dot(l)) + absf(ha.y * (ax[1] as Vector3).dot(l)) + absf(ha.z * (ax[2] as Vector3).dot(l))
		var rb := absf(hb.x * (bx[0] as Vector3).dot(l)) + absf(hb.y * (bx[1] as Vector3).dot(l)) + absf(hb.z * (bx[2] as Vector3).dot(l))
		if absf(d.dot(l)) > ra + rb:
			return false
	return true
