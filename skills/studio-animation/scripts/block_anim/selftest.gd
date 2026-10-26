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
