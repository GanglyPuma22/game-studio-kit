## Golden checks for camera_rig.gd, run before trusting a flown camera:
##   godot --headless --script <kit>/skills/studio-cinematic/scripts/camera_rigs/selftest.gd
## Prints one line per check and exits 1 if any fails. Also prints what each
## rig manages on the same 40 m test leg, as a sanity read.
extends SceneTree

var _fails := 0


func _init() -> void:
	var dir := (get_script() as Script).resource_path.get_base_dir()
	var Rig = load(dir + "/camera_rig.gd")
	var h := 1.0 / 240.0

	# Every rig stays inside its own limits on a leg that asks for more.
	for name in ["inspire3", "fpv", "crane", "handheld"]:
		var r = Rig.new(name)
		r.start(Vector3.ZERO, Vector3(0, 0, -10))
		var vtop := 0.0
		var ltop := 0.0
		var t := 0.0
		while t < 8.0:
			var goal := Vector3(0, 2.0, -minf(200.0, 40.0 * t))
			r.look_target = goal + Vector3(0, 0, -10)
			r.fly_toward(goal, Vector3(0, 0, -40.0))
			r.aim_at(goal + Vector3(0, 0, -10), h)
			r.step(h)
			var vh := Vector3(r.vel.x, 0, r.vel.z).length()
			vtop = maxf(vtop, vh)
			ltop = maxf(ltop, r.tilt_deg())
			t += h
		_check("%s top speed %.1f <= %.1f m/s" % [name, vtop, r.vmax_h], vtop <= r.vmax_h * 1.01)
		_check("%s lean %.1f <= %.1f deg" % [name, ltop, rad_to_deg(r.tilt_max)], ltop <= rad_to_deg(r.tilt_max) + 0.01)

	# The FPV camera banks only lightly, even at full lean.
	var f = Rig.new("fpv")
	f.start(Vector3.ZERO, Vector3(0, 0, -10))
	var roll_top := 0.0
	var t2 := 0.0
	while t2 < 3.0:
		var goal := Vector3(30.0 * sin(t2 * 2.0), 0, -20.0 * t2)
		f.fly_toward(goal, Vector3(60.0 * cos(t2 * 2.0), 0, -20.0))
		f.aim_at(goal + Vector3(0, 0, -10), h)
		f.step(h)
		roll_top = maxf(roll_top, rad_to_deg(f.cam_up().angle_to(Vector3.UP)))
		t2 += h
	_check("fpv camera roll %.1f deg stays under 10" % roll_top, roll_top < 10.0)

	# Handheld drift is seeded: two runs give the same lens.
	var a = Rig.new("handheld")
	var b = Rig.new("handheld")
	a.start(Vector3.ZERO, Vector3(0, 0, -5))
	b.start(Vector3.ZERO, Vector3(0, 0, -5))
	for _i in 480:
		a.step(h)
		b.step(h)
	_check("handheld drift repeats", a.lens_pos().is_equal_approx(b.lens_pos()) and a.lens_pos() != a.pos)

	# The pilot plan: an 82 m reveal with a 33 m drop (the case that taught
	# the method). Flown smoothly it needs far more than the 4.2 s a drawn
	# curve was given; a long enough slot fits and is used in full.
	var pts: Array = []
	for i in 401:
		var k := float(i) / 400.0
		pts.append(Vector3(-30.0 * sin(k * PI * 0.5), 40.0 - 33.0 * k * k, -70.0 * k))
	var lim: Dictionary = Rig.new("inspire3").plan_limits(0.7)
	var need: float = Rig.min_duration(pts, 3.0, 3.0, lim)
	_check("82 m reveal needs %.1f s smoothly, more than 4.2" % need, need > 4.2 * 1.5)
	var short: Dictionary = Rig.plan_speeds(pts, 4.2, 3.0, 3.0, lim)
	_check("4.2 s slot does not fit (takes %.1f s)" % short["total"], not short["fits"])
	var roomy: Dictionary = Rig.plan_speeds(pts, need + 3.0, 3.0, 3.0, lim)
	_check("a %.1f s slot fits and is used (%.2f s)" % [need + 3.0, roomy["total"]], roomy["fits"] and absf(roomy["total"] - (need + 3.0)) < 0.1)
	_check("plan top speed %.1f within the limit %.1f" % [roomy["top"], lim["vmax"]], roomy["top"] <= lim["vmax"] + 0.01)

	# chase_drawn: the leash holds a slow rig near a fast drawn move, and a
	# drawn jump (a cut) restarts the rig at the new mark.
	var c = Rig.new("crane")
	c.start(Vector3.ZERO, Vector3(0, 0, -10))
	var dev_top := 0.0
	var aim_top := 0.0
	var dt := 1.0 / 30.0
	var prev_dl := Vector3(0, 0, -10)
	for i in 60:
		var dp := Vector3(0, 0, -0.5 * i)
		var dl := dp + Vector3(5.0 * sin(i * 0.3), 0, -10)
		var o: Array = c.chase_drawn(dp, dl, dt, 0.2, 0.5, 6.0)
		dev_top = maxf(dev_top, (o[0] as Vector3).distance_to(dp))
		# (The leash holds the aim to the drawn look point led 0.2 s ahead.)
		var aim := dl + (dl - prev_dl) / dt * 0.2
		prev_dl = dl
		var want := (aim - (o[0] as Vector3)).normalized()
		aim_top = maxf(aim_top, rad_to_deg(((o[1] as Vector3) - (o[0] as Vector3)).normalized().angle_to(want)))
	_check("crane leash: lens within %.2f m of the drawn lens (<= 0.5)" % dev_top, dev_top <= 0.51)
	_check("crane leash: aim within %.1f deg of the drawn aim (<= 6)" % aim_top, aim_top <= 6.01)
	var jump: Array = c.chase_drawn(Vector3(100, 5, 0), Vector3(100, 5, -10), dt)
	_check("a drawn cut restarts the rig on its mark", (jump[0] as Vector3).is_equal_approx(Vector3(100, 5, 0)))

	print("camera_rig selftest: %s" % ("PASS" if _fails == 0 else "%d FAILED" % _fails))
	quit(1 if _fails > 0 else 0)


func _check(label: String, ok: bool) -> void:
	print("%s  %s" % ["ok  " if ok else "FAIL", label])
	if not ok:
		_fails += 1
