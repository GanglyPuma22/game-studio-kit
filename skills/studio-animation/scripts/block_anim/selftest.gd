## Golden tests for the block animation modules: poses with known answers,
## run before trusting any clip score. A checker or IK bug sends tuning the
## wrong way for whole rounds, so these come first.
##   godot --headless --script <kit>/skills/studio-animation/scripts/block_anim/selftest.gd
## Prints one line per check and exits 1 if any fails.
extends SceneTree

var _fails := 0
var _dir := ""


func _init() -> void:
	_dir = (get_script() as Script).resource_path.get_base_dir()
	var Check = load(_dir + "/motion_check.gd")
	var Chain = load(_dir + "/block_chain.gd")
	var Two = load(_dir + "/two_bone.gd")
	var Plant = load(_dir + "/plant.gd")
	var Gait = load(_dir + "/gait.gd")

	# Angles: a 200° turn is a 160° turn the other way.
	_near("shortest turn of a 200 deg turn is 160", Check.shortest_turn_deg(Quaternion(Vector3.UP, deg_to_rad(200.0))), 160.0, 0.01)
	_near("shortest turn of a 90 deg knee is 90", Check.shortest_turn_deg(Quaternion(Vector3.RIGHT, deg_to_rad(90.0))), 90.0, 0.01)
	_near("signed turn +30 about X", Check.signed_turn_deg(Quaternion(Vector3.RIGHT, deg_to_rad(30.0)), Vector3.RIGHT), 30.0, 0.01)
	_near("signed turn -30 about X", Check.signed_turn_deg(Quaternion(Vector3.RIGHT, deg_to_rad(-30.0)), Vector3.RIGHT), -30.0, 0.01)
	_near("signed turn of -q is the same turn", Check.signed_turn_deg(-Quaternion(Vector3.RIGHT, deg_to_rad(30.0)), Vector3.RIGHT), 30.0, 0.01)

	# Checker on a two-block leg: thigh (root) and shin hanging below it.
	var desc := {"limits": {"thigh": 180.0, "shin": 150.0}, "contacts": ["shin"],
		"hinges": {"shin": {"axis": [1, 0, 0], "sign": 1}}}
	var bind := [Transform3D(Basis(), Vector3(0, 2, 0)), Transform3D(Basis(), Vector3(0, 1, 0))]
	var box_c := [Vector3(0, -0.5, 0), Vector3(0, -0.5, 0)]
	var box_h := [Vector3(0.1, 0.5, 0.1), Vector3(0.1, 0.5, 0.1)]
	var parent := PackedInt32Array([-1, 0])
	var c = Check.new()
	c.setup_rig(["thigh", "shin"], parent, bind, box_c, box_h, desc)
	c.add(_leg(bind, 40.0), Transform3D.IDENTITY, -1.0, 1.0 / 60.0, false, {})
	_near("knee bent the right way is not a hinge error", c.report().hinge_frames_pct, 0.0, 0.01)
	c.reset()
	c.add(_leg(bind, -40.0), Transform3D.IDENTITY, -1.0, 1.0 / 60.0, false, {})
	_near("knee bent the wrong way is a hinge error", c.report().hinge_frames_pct, 100.0, 0.01)
	# A rig bound with its knee already bent 40 degrees: straightening it is
	# not bending it backwards (rest_deg), bending past straight still is.
	var bent_desc := desc.duplicate(true)
	bent_desc.hinges.shin["rest_deg"] = 40.0
	var bent_bind := _leg(bind, 40.0)
	var cb = Check.new()
	cb.setup_rig(["thigh", "shin"], parent, bent_bind, box_c, box_h, bent_desc)
	cb.add(_leg(bind, 0.0), Transform3D.IDENTITY, -1.0, 1.0 / 60.0, false, {})
	_near("a bent-bound knee straightened is not a hinge error", cb.report().hinge_frames_pct, 0.0, 0.01)
	cb.reset()
	cb.add(_leg(bind, -30.0), Transform3D.IDENTITY, -1.0, 1.0 / 60.0, false, {})
	_near("a bent-bound knee bent backwards is a hinge error", cb.report().hinge_frames_pct, 100.0, 0.01)
	_near("and by how much (40 less 5 slack)", c.report().hinge_over_deg, 35.0, 0.2)
	c.reset()
	c.add(_leg(bind, 0.0), Transform3D.IDENTITY, -1.0, 1.0 / 60.0, false, {})
	c.add(_leg(bind, 90.0), Transform3D.IDENTITY, -1.0, 1.0 / 60.0, false, {})
	_near("a 90 deg knee swap in one frame reads 5400 deg/s", c.report().turn_rate_deg_s, 5400.0, 1.0)
	c.reset()
	var stretched := _leg(bind, 0.0)
	stretched[1] = Transform3D(Basis().scaled(Vector3(1, 1.2, 1)), (stretched[1] as Transform3D).origin)
	c.add(stretched, Transform3D.IDENTITY, -1.0, 1.0 / 60.0, false, {})
	_near("a 20% stretched block reads 20%", c.report().stretch_pct, 20.0, 0.1)
	c.reset()
	c.add(_leg(bind, 0.0), Transform3D.IDENTITY, 0.5, 1.0 / 60.0, false, {})
	_near("a shin 0.5 m into the ground reads 0.5", c.report().ground_m, 0.5, 0.01)

	# Rule 8b: no block through another. A torso, an arm (upper, fore) off
	# its top: the forearm swung into the torso is a block through a block;
	# the upper arm meeting the torso at the shoulder is their joint.
	var ob_n := ["torso", "upper", "fore"]
	var ob_par := PackedInt32Array([-1, 0, 1])
	var ob_bind := [Transform3D(Basis(), Vector3(0, 1, 0)), Transform3D(Basis(), Vector3(0.35, 1.45, 0)), Transform3D(Basis(), Vector3(0.35, 1.05, 0))]
	var ob_c := [Vector3.ZERO, Vector3(0, -0.2, 0), Vector3(0, -0.2, 0)]
	var ob_h := [Vector3(0.3, 0.5, 0.15), Vector3(0.07, 0.2, 0.07), Vector3(0.06, 0.2, 0.06)]
	var cc = Check.new()
	cc.setup_rig(ob_n, ob_par, ob_bind, ob_c, ob_h, {"no_overlap": "all"})
	_check("'all' pairs leave out parent and child", cc.pairs.size() == 1)
	cc.add(ob_bind, Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_near("arm hanging clear of the torso: no overlap", cc.report().self_overlap_pct, 0.0, 0.01)
	cc.reset()
	var ob_thru := ob_bind.duplicate()
	ob_thru[2] = Transform3D(Basis(Vector3.FORWARD, deg_to_rad(90.0)), Vector3(0.35, 1.05, 0))   # forearm swung in, through the torso
	cc.add(ob_thru, Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_near("forearm through the torso is an overlap", cc.report().self_overlap_pct, 100.0, 0.01)
	_check("and names the pair", cc.report().self_at == "torso/fore")
	# A graze: the forearm 4 cm into the torso's side counts on a bare
	# checker, not with a 5 cm floor (a small body's hand on its hip).
	var ob_graze := ob_bind.duplicate()
	ob_graze[2] = Transform3D(Basis(), Vector3(0.31, 1.05, 0))
	cc.reset()
	cc.add(ob_graze, Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_near("a 4 cm graze counts with no floor", cc.report().self_overlap_pct, 100.0, 0.01)
	cc.reset()
	cc.floor_m = 0.05
	cc.add(ob_graze, Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_near("and not with a 5 cm floor", cc.report().self_overlap_pct, 0.0, 0.01)
	_near("box depth of two unit boxes 0.25 apart is 0.75", Check.box_depth(Vector3.ZERO, Basis(), Vector3(0.5, 0.5, 0.5), Vector3(0.25, 0, 0), Basis(), Vector3(0.5, 0.5, 0.5)), 0.75, 0.001)
	_near("boxes apart have no depth", Check.box_depth(Vector3.ZERO, Basis(), Vector3(0.5, 0.5, 0.5), Vector3(1.5, 0, 0), Basis(), Vector3(0.5, 0.5, 0.5)), 0.0, 0.001)

	# The Kit's rig description template names only blocks it declares.
	var tpl = JSON.parse_string(FileAccess.get_file_as_string(_dir + "/../../../../templates/block-rig.json"))
	_check("block-rig.json template parses", tpl is Dictionary)
	if tpl is Dictionary:
		var tn: Array = []
		var tidx := {}
		for blk in tpl.blocks:
			tidx[blk.name] = tn.size()
			tn.append(blk.name)
		var tp := PackedInt32Array()
		var tb: Array = []
		var tc: Array = []
		var th: Array = []
		for blk in tpl.blocks:
			tp.append(-1 if blk.parent == null else int(tidx[blk.parent]))
			tb.append(Transform3D.IDENTITY)
			tc.append(Vector3.ZERO)
			var bh: Array = blk.box_half
			th.append(Vector3(bh[0], bh[1], bh[2]))
		var tcheck = Check.new()
		tcheck.setup_rig(tn, tp, tb, tc, th, tpl)
		_check("template names only known blocks %s" % str(tcheck.unknown), tcheck.unknown.is_empty())
		_check("template hinges load", tcheck.hinges.size() == 2)

	# Two-bone IK: an arm reaching forward (-Z) with the elbow hinted down
	# and back bends its elbow down and back, whichever hint kind is used.
	var root := Vector3(0, 0, 0)
	var target := Vector3(0, 0, -1.6)
	var by_dir: Array = Two.solve_toward_direction(root, target, 1.0, 1.0, Vector3(0, -1, 0.5))
	var by_point: Array = Two.solve_toward_point(root, target, 1.0, 1.0, root + Vector3(0, -4, 2))
	_check("elbow bends down (direction hint)", (by_dir[0] as Vector3).y < -0.3)
	_check("elbow bends down (point hint)", (by_point[0] as Vector3).y < -0.3)
	_near("upper arm stays rigid", (by_dir[0] as Vector3).distance_to(root), 1.0, 0.001)
	_near("forearm stays rigid", (by_dir[0] as Vector3).distance_to(by_dir[1]), 1.0, 0.001)
	_near("hand reaches the target", (by_dir[1] as Vector3).distance_to(target), 0.0, 0.002)
	var far_hint: Array = Two.solve_toward_point(Vector3(5, 0, 0), Vector3(5, 0, -1.6), 1.0, 1.0, Vector3(0, -1, 0.5))
	_check("a direction passed as a point bends somewhere else", (far_hint[0] as Vector3).y > -0.3 or (far_hint[0] as Vector3).x < 4.9)
	var h1: Vector3 = Two.hinge_axis(Vector3(0, -1, 0), Vector3(0, -1, 0.001), Vector3(0, 0, 1), Vector3(-1, 0, 0))
	_check("a straight limb keeps last frame's hinge", h1.dot(Vector3(-1, 0, 0)) > 0.99)

	# Uneven frame times are not acceleration: steady 10 m/s sampled at
	# 1/30 s then 1/60 s reads (near) zero.
	c.reset()
	var p0 := _leg(bind, 0.0)
	for step in [[0.0, 0.0], [1.0 / 30.0, 1.0 / 30.0], [1.0 / 30.0 + 1.0 / 60.0, 1.0 / 60.0]]:
		c.add(p0, Transform3D(Basis(), Vector3(10.0 * float(step[0]), 0, 0)), -1.0, float(step[1]), false, {})
	_near("steady motion at uneven frame times has no pop", c.report().pop_m_s2, 0.0, 1.0)

	# A step is measured from where the foot stood, not from the first
	# airborne frame: down at x=0, up at x=0.2, down at x=0.7 is a 0.7 m step.
	var sc = Check.new()
	sc.setup(["foot"], PackedInt32Array([-1]), PackedFloat32Array([180.0]), [Transform3D.IDENTITY],
		[Vector3.ZERO], [Vector3(0.1, 0.1, 0.1)], PackedInt32Array([0]), [], [])
	for fx in [[0.0, 0.1], [0.2, 1.0], [0.7, 0.1]]:
		sc.add([Transform3D(Basis(), Vector3(float(fx[0]), float(fx[1]), 0))], Transform3D.IDENTITY, 0.0, 1.0 / 60.0, false, {})
	_check("a 0.7 m step is not a shuffle", sc.report().steps == 1 and sc.report().shuffles == 0)
	sc.setup(["foot"], PackedInt32Array([-1]), PackedFloat32Array([180.0]), [Transform3D.IDENTITY],
		[Vector3.ZERO], [Vector3(0.1, 0.1, 0.1)], PackedInt32Array([0]), [], [0])
	sc.setup(["foot"], PackedInt32Array([-1]), PackedFloat32Array([180.0]), [Transform3D.IDENTITY],
		[Vector3.ZERO], [Vector3(0.1, 0.1, 0.1)], PackedInt32Array([0]), [], [])
	_check("setting up again forgets old soft blocks", sc.soft.is_empty())

	# A box rotated 45 deg cutting a ledge's corner: no corner is inside,
	# yet its edge goes 0.5 m deep (wall: solid where x < 0 and y < 1).
	var wc = Check.new()
	wc.setup(["block"], PackedInt32Array([-1]), PackedFloat32Array([180.0]), [Transform3D.IDENTITY],
		[Vector3.ZERO], [Vector3(0.7071, 0.7071, 0.2)], PackedInt32Array(), [], [])
	wc.walls = [[Vector3(1, 0, 0), 0.0, 1.0]]
	wc.add([Transform3D(Basis(Vector3.BACK, deg_to_rad(45.0)), Vector3(0, 1, 0))], Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_near("a box cutting a ledge corner reads its edge depth", wc.report().wall_m, 0.5, 0.01)

	# Rules 9b, 9c and 8c on a 2 m body and a small hand block beside it.
	var mk := func() -> RefCounted:
		var m = Check.new()
		m.setup(["body", "hand"], PackedInt32Array([-1, -1]), PackedFloat32Array([180.0, 180.0]),
			# The hand rests beside the body (a rest overlap would be allowed).
			[Transform3D.IDENTITY, Transform3D(Basis(), Vector3(1.0, 0.0, 0.0))], [Vector3.ZERO, Vector3.ZERO],
			[Vector3(0.5, 1.0, 0.3), Vector3(0.1, 0.1, 0.1)], PackedInt32Array(), [[1, 0]], [])
		return m
	var body_t := Transform3D.IDENTITY
	var mc = mk.call()
	_near("height comes from the bind boxes", mc.height, 2.0, 0.001)
	# 9b: 0.5 m a frame at 60 fps is 15 body heights a second.
	for f in 10:
		mc.add([body_t, Transform3D(Basis(), Vector3(1.0 + 0.5 * f, 0.0, 0.0))], Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_check("a block faster than speed_max is flagged (9b)", mc.report().fast_frames_pct > 50.0)
	mc = mk.call()
	mc.fast_ok = {"hand": true}
	for f in 10:
		mc.add([body_t, Transform3D(Basis(), Vector3(1.0 + 0.5 * f, 0.0, 0.0))], Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_check("and not when the move names it in fast_ok", mc.report().fast_frames_pct == 0.0)
	# 9c: a 5 cm wobble at 10 Hz shakes; the same at 1 Hz is a sway.
	for hz in [10.0, 1.0]:
		mc = mk.call()
		for f in 120:
			mc.add([body_t, Transform3D(Basis(), Vector3(1.0 + 0.05 * sin(TAU * hz * f / 60.0), 0.0, 0.0))], Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
		if hz > 5.0:
			_check("a 10 Hz wobble shakes (9c)", mc.report().shake_frames_pct > 20.0)
		else:
			_check("a 1 Hz sway does not", mc.report().shake_frames_pct == 0.0)
	mc = mk.call()
	mc.shake_ok = {"hand": true}
	for f in 120:
		mc.add([body_t, Transform3D(Basis(), Vector3(1.0 + 0.05 * sin(TAU * 10.0 * f / 60.0), 0.0, 0.0))], Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_check("and not when the move names it in shake_ok", mc.report().shake_frames_pct == 0.0)
	# 8c: a hand passing right through the body between two frames.
	mc = mk.call()
	mc.add([body_t, Transform3D(Basis(), Vector3(-1.5, 0.0, 0.0))], Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	mc.add([body_t, Transform3D(Basis(), Vector3(1.5, 0.0, 0.0))], Transform3D.IDENTITY, -5.0, 1.0 / 60.0, false, {})
	_check("a block tunnelling through another between frames is caught (8c)", mc.report().sweep_frames == 1)
	_check("though neither frame overlaps", mc.report().self_overlap_pct == 0.0)

	# Whole-chain reach: every segment keeps its length.
	var pts := PackedVector3Array([Vector3.ZERO, Vector3(0, 1, 0), Vector3(0, 2, 0), Vector3(0, 3, 0)])
	var lens := PackedFloat32Array([1.0, 1.0, 1.0])
	var cones := PackedFloat32Array([deg_to_rad(30.0), deg_to_rad(60.0), deg_to_rad(60.0)])
	var got: PackedVector3Array = Chain.reach(pts, Vector3(1.2, 2.4, 0), lens, cones)
	var rigid := true
	for i in 3:
		rigid = rigid and absf(got[i].distance_to(got[i + 1]) - 1.0) < 0.001
	_check("chain reach keeps every segment rigid", rigid)
	_near("chain reach gets to the target", got[3].distance_to(Vector3(1.2, 2.4, 0)), 0.0, 0.05)
	var eased: PackedVector3Array = Chain.ease_from(pts, got, lens, 15.0, 1.0 / 60.0)
	var rigid2 := true
	for i in 3:
		rigid2 = rigid2 and absf(eased[i].distance_to(eased[i + 1]) - 1.0) < 0.001
	_check("eased chain stays rigid", rigid2)
	_check("eased chain moves only part way", eased[3].distance_to(pts[3]) < got[3].distance_to(pts[3]))

	var line := PackedVector3Array([Vector3.ZERO, Vector3(0, 1, 0), Vector3(0, 2, 0)])
	var folded: PackedVector3Array = Chain.reach(line, Vector3(0, 1.5, 0), PackedFloat32Array([1.0, 1.0]),
		PackedFloat32Array([deg_to_rad(90.0), deg_to_rad(90.0)]), Vector3.ZERO, Vector3.ZERO, 12, 0.01, Vector3(0, 0, 1))
	_near("a straight chain folds to reach along its own line", folded[2].distance_to(Vector3(0, 1.5, 0)), 0.0, 0.02)
	_check("and folds toward the hint", folded[1].z > 0.1)

	var back: PackedVector3Array = Chain.reach(line, Vector3(0, -2, 0), PackedFloat32Array([1.0, 1.0]),
		PackedFloat32Array([PI, 0.0]))
	_near("a chain turned right round keeps its child's cone", back[2].distance_to(Vector3(0, -2, 0)), 0.0, 0.02)
	var fa = Plant.new()
	var fb = Plant.new()
	fa.other = fb
	fb.other = fa
	var wa: WeakRef = weakref(fa)
	fa = null
	fb = null
	_check("paired feet are freed with their rig", wa.get_ref() == null)
	var flip: PackedVector3Array = Chain.ease_from(PackedVector3Array([Vector3.ZERO, Vector3.UP]),
		PackedVector3Array([Vector3.ZERO, Vector3.DOWN]), PackedFloat32Array([1.0]), 15.0, 1.0 / 60.0)
	_check("an opposite solve is eased, not snapped (%s)" % str(flip[1]), flip[1].y > 0.5)

	# Stepper: nudges below a third of a leg do not step; a step that would
	# land where the foot stands is dropped.
	var f = Plant.new()
	f.configure(3.0)
	f.update(Vector3.ZERO, 0.0, 0.1)
	for k in 30:
		f.update(Vector3(0.3 * sin(k * 0.7), 0, 0), 0.0, 1.0 / 60.0)
	_check("small nudges do not step", not f.stepping() and f.at == Vector3.ZERO)
	f.update(Vector3(0.05, 0, 0), 0.0, 1.0 / 60.0)
	f.step_now()
	_check("a step that would land in place is dropped", not f.stepping())
	for k in 30:
		f.update(Vector3(2.0, 0, 0), 0.0, 1.0 / 60.0)
	_check("a real move steps and lands there", f.at.distance_to(Vector3(2.0, 0, 0)) < 0.01)
	var q = Plant.new()
	q.update(Vector3.ZERO, 0.0, 0.1)
	for k in 6:
		q.update(Vector3(0.1, 0, 0), 0.0, 1.0 / 60.0)
	q.step_now()   # queued: still resting
	for k in 18:
		q.update(Vector3.ZERO, 0.0, 1.0 / 60.0)
	_check("a queued step whose target came back is dropped", not q.stepping() and q.at == Vector3.ZERO)

	# Gait: a walk always has at least two feet down.
	var g = Gait.new()
	g.home = [Vector3(-0.5, 0, 1), Vector3(0.5, 0, 1), Vector3(-0.5, 0, -1), Vector3(0.5, 0, -1)]
	var least := 4
	for k in 120:
		g.step(Transform3D(Basis(), Vector3(0, 0, -k * 0.02)), Vector3(0, 0, -1.2), 0.0, 1.0, 1.0 / 60.0)
		var n := 0
		for i in 4:
			n += int(g.planted(i))
		least = mini(least, n)
	_check("walk keeps at least two feet down", least >= 2)
	for gm in [[1.0, "canter has a flight"], [2.0, "gallop has flights"]]:
		g.reset()
		var air := 0
		for k in 240:
			g.step(Transform3D(Basis(), Vector3(0, 0, -k * 0.05)), Vector3(0, 0, -3.0), float(gm[0]), 1.0, 1.0 / 60.0)
			air += int(g.airborne())
		_check("%s (%d of 240 frames)" % [gm[1], air], air > 0)

	# Two legs: a walk always has a foot down (double support), a run has
	# flights.
	var bp = Gait.new()
	bp.table = Gait.BIPED
	bp.home = [Vector3(-0.5, 0, 0), Vector3(0.5, 0, 0), Vector3(-0.5, 0, 0), Vector3(0.5, 0, 0)]
	var bp_least := 2
	var bp_double := 0
	for k in 240:
		bp.step(Transform3D(Basis(), Vector3(0, 0, -k * 0.02)), Vector3(0, 0, -1.2), 0.0, 1.0, 1.0 / 60.0)
		var n2 := int(bp.planted(0)) + int(bp.planted(1))
		bp_least = mini(bp_least, n2)
		bp_double += int(n2 == 2)
	_check("biped walk always has a foot down", bp_least >= 1)
	_check("biped walk has double support (%d of 240 frames)" % bp_double, bp_double > 0)
	bp.reset()
	var bp_air := 0
	for k in 240:
		bp.step(Transform3D(Basis(), Vector3(0, 0, -k * 0.06)), Vector3(0, 0, -3.6), 1.0, 1.7, 1.0 / 60.0)
		bp_air += int(not bp.planted(0) and not bp.planted(1))
	_check("biped run has flights (%d of 240 frames)" % bp_air, bp_air > 0)

	print("block_anim selftest: %s" % ("FAILED %d" % _fails if _fails > 0 else "all passed"))
	quit(1 if _fails > 0 else 0)


## The leg's pose with the knee turned `deg` about X (in the thigh frame).
func _leg(bind: Array, deg: float) -> Array:
	var thigh: Transform3D = bind[0]
	var shin := Transform3D(Basis(Vector3.RIGHT, deg_to_rad(deg)), (bind[1] as Transform3D).origin)
	return [thigh, shin]


func _near(what: String, got, want: float, tol: float) -> void:
	_check("%s (got %s)" % [what, str(got)], absf(float(got) - want) <= tol)


func _check(what: String, ok: bool) -> void:
	print(("ok    " if ok else "FAIL  ") + what)
	if not ok:
		_fails += 1
