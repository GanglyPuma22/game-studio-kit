## A camera rig simulator for engine blockouts: every moving camera is flown
## by a simulated real rig instead of drawn as a free curve, so no move is
## faster, snappier or more impossible than real gear. Measured on one
## trailer (Nov 2026): the person called the flown version "a noticeable
## step up" in camera and shot quality. See ../../references/camera-rigs.md.
##
## The craft flies only through stick inputs, like a real multirotor: the
## sticks ask for a velocity, the flight controller leans the craft to get
## it (never past its tilt limit, so it cannot start, stop or turn faster
## than the real craft), and drag sets its top speed. The camera rides a
## gimbal that turns within rate limits, run by an operator who eases in and
## out of every move. Rigs other than the film drone reuse the same model
## with other limits.
##
##   "inspire3"  film drone, DJI Inspire 3 S mode (published: 26 m/s, 8 m/s
##               climb and descent, 40 deg tilt, 150 deg/s yaw, gimbal
##               120 deg/s tilt and 270 deg/s pan). Default.
##   "fpv"       chase drone: fast, hard banking, the camera rolls lightly
##               with the craft (bank_gain); fixed_cam = true for pure FPV
##   "crane"     crane arm or dolly: slow, eased, small rises
##   "handheld"  operator on foot or on a Steadicam: walking pace, lag, a
##               small seeded breathing drift (renders repeat)
## Only the Inspire 3 figures are published; the other rigs, the response
## times and the operator easing are approximate, tuned by eye.
##
## Three ways to drive it:
##   fly_toward() + aim_at() + step()  an autopilot chasing a timed target
##   set_sticks() + step()              raw sticks (a recorded human flight)
##   chase_drawn()                      fly an existing drawn camera: the
##                                      drawn move becomes the pilot's mark,
##                                      held on a leash (see camera-rigs.md)
## Static helpers: plan_speeds() times a path within limits (the pilot's
## plan), min_duration() says how long a path needs at the limits, and
## guard_lens() keeps a close camera out of walls and roofs.
##
## Self-test: godot --headless --script <this folder>/selftest.gd
extends RefCounted

const G := 9.81

# Published (Inspire 3, S mode).
var vmax_h := 26.0
var vmax_up := 8.0
var vmax_down := 8.0
var tilt_max := deg_to_rad(40.0)
var yaw_rate_max := deg_to_rad(150.0)
var gim_tilt_rate := deg_to_rad(120.0)
var gim_pan_rate := deg_to_rad(270.0)

# Assumed: how the flight controller and the operator respond.
var tilt_tau := 0.15                    # attitude reaches a new tilt in about this long
var tilt_rate := deg_to_rad(180.0)      # how fast the craft can change its tilt
var vel_gain := 1.5                     # flight controller: 1/s of velocity error
var vert_gain := 2.5
var vert_acc := 6.0                     # m/s^2 up or down
var gim_acc := deg_to_rad(300.0)        # operator easing: gimbal angular acceleration
var gim_gain := 4.0                     # operator: 1/s of aim error
var gim_tilt_min := deg_to_rad(-90.0)   # set per shot (e.g. never steeper than -30)
var gim_tilt_max := deg_to_rad(30.0)
var rig := "inspire3"
var fixed_cam := false                  # no gimbal: the camera is fixed to the craft
var cam_uptilt := 0.0                   # fpv: camera tilted up on the frame (radians)
var bank_gain := 0.0                    # fpv: how much the camera rolls with the lean
var sway := 0.0                         # handheld: drift amplitude (metres)
var drag_k := 0.0                       # set so full tilt holds exactly top speed
var _sway_t := 0.0
var _noise := FastNoiseLite.new()

# State.
var pos := Vector3.ZERO
var vel := Vector3.ZERO
var tilt := Vector2.ZERO                # horizontal lean as (x, z) angles, radians
var yaw := 0.0                          # craft heading (radians, 0 = -z)
var yaw_vel := 0.0
var pan := 0.0                          # gimbal heading, world (radians, 0 = -z)
var pitch := 0.0                        # gimbal tilt (radians, + up)
var pan_vel := 0.0
var pitch_vel := 0.0
var sticks := Vector4.ZERO              # roll, pitch, throttle, yaw in -1..1
var look_target := Vector3.INF          # fixed_cam: what the pilot points the nose at

# chase_drawn() state.
var _drawn_pos := Vector3.INF
var _drawn_look := Vector3.INF


func _init(rig_name: String = "inspire3") -> void:
	_noise.seed = 9
	_noise.frequency = 0.35
	use_rig(rig_name)


## Swap in a rig's limits (see the header).
func use_rig(name: String) -> void:
	rig = name
	match name:
		"fpv":
			vmax_h = 33.0
			vmax_up = 15.0
			vmax_down = 15.0
			tilt_max = deg_to_rad(60.0)
			yaw_rate_max = deg_to_rad(400.0)
			tilt_tau = 0.06
			tilt_rate = deg_to_rad(600.0)
			vel_gain = 3.0
			vert_gain = 4.0
			vert_acc = 14.0
			# A cinewhoop with a fast tilt gimbal, so the framing holds; the
			# camera still banks a little with the craft. Strong roll read
			# badly on screen (Nov 2026): keep bank_gain near 0.15.
			gim_tilt_rate = deg_to_rad(300.0)
			gim_pan_rate = deg_to_rad(400.0)
			gim_acc = deg_to_rad(900.0)
			gim_gain = 8.0
			cam_uptilt = deg_to_rad(20.0)
			bank_gain = 0.15
		"crane":
			vmax_h = 3.0
			vmax_up = 1.5
			vmax_down = 1.5
			tilt_max = deg_to_rad(7.0)      # sets the arm's acceleration (about 1.2 m/s^2)
			yaw_rate_max = deg_to_rad(45.0)
			vel_gain = 0.9
			vert_gain = 1.2
			vert_acc = 0.8
			gim_tilt_rate = deg_to_rad(40.0)
			gim_pan_rate = deg_to_rad(60.0)
			gim_acc = deg_to_rad(60.0)
			gim_gain = 2.0
		"handheld":
			vmax_h = 4.0
			vmax_up = 1.0
			vmax_down = 1.0
			tilt_max = deg_to_rad(17.0)     # about 3 m/s^2 on foot
			yaw_rate_max = deg_to_rad(180.0)
			vel_gain = 2.0
			gim_tilt_rate = deg_to_rad(90.0)
			gim_pan_rate = deg_to_rad(150.0)
			gim_acc = deg_to_rad(200.0)
			gim_gain = 3.0
			sway = 0.04
		"inspire3":
			pass
		_:
			push_warning("camera_rig: unknown rig '%s', using inspire3 limits" % name)
			rig = "inspire3"
	drag_k = G * tan(tilt_max) / (vmax_h * vmax_h)


## The rig's limits as a plan_speeds() limits dictionary, with a smooth
## operator's margin (fraction of the hard limits, 0.7 flies well inside).
func plan_limits(margin: float = 0.7) -> Dictionary:
	return {
		"vmax": vmax_h * margin,
		"a_along": G * tan(tilt_max) * margin,
		"a_lat": G * tan(tilt_max) * margin * 0.9,
		"v_vert": minf(vmax_up, vmax_down) * margin,
	}


func start(p: Vector3, look_at: Vector3) -> void:
	pos = p
	vel = Vector3.ZERO
	tilt = Vector2.ZERO
	var d := (look_at - p).normalized()
	pan = atan2(-d.x, -d.z)
	pitch = asin(clampf(d.y, -1.0, 1.0))
	yaw = pan
	yaw_vel = 0.0
	pan_vel = 0.0
	pitch_vel = 0.0
	_drawn_pos = p
	_drawn_look = look_at


## Where the lens is: the craft, plus the handheld drift.
func lens_pos() -> Vector3:
	if sway <= 0.0:
		return pos
	var s := _sway_t * 7.0
	return pos + Vector3(_noise.get_noise_1d(s), _noise.get_noise_1d(s + 100.0) * 0.6, _noise.get_noise_1d(s + 200.0)) * sway * 2.0


func look_dir() -> Vector3:
	return Vector3(-sin(pan) * cos(pitch), sin(pitch), -cos(pan) * cos(pitch))


## The camera's up vector: level on a gimbal, rolled with the lean on FPV.
func cam_up() -> Vector3:
	if bank_gain <= 0.0 or tilt.length() < 0.0001:
		return Vector3.UP
	var fwd := look_dir()
	var lean := Vector3(tilt.x, 0, tilt.y)
	var side := fwd.cross(Vector3.UP).normalized()
	return Vector3.UP.rotated(fwd, -lean.dot(side) * bank_gain)


func tilt_deg() -> float:
	return rad_to_deg(tilt.length())


## Raw sticks (mode 2 style): roll right +, pitch forward +, throttle up +,
## yaw right +. Body frame: forward is the craft's heading.
func set_sticks(roll: float, pitch_fwd: float, throttle: float, yaw_s: float) -> void:
	sticks = Vector4(clampf(roll, -1, 1), clampf(pitch_fwd, -1, 1), clampf(throttle, -1, 1), clampf(yaw_s, -1, 1))


## Autopilot: the sticks a pilot would hold to follow a target moving at
## target_vel (feed-forward) and close the gap to target_pos. The nose
## follows the camera pan, as a one-operator crew flies.
func fly_toward(target_pos: Vector3, target_vel: Vector3, gap_gain: float = 1.2) -> void:
	var want := target_vel + (target_pos - pos) * gap_gain
	var fwd := Vector3(-sin(yaw), 0, -cos(yaw))
	var right := Vector3(cos(yaw), 0, -sin(yaw))
	var h := Vector2(want.dot(right) / vmax_h, want.dot(fwd) / vmax_h)
	if h.length() > 1.0:
		h = h.normalized()
	var thr := want.y / (vmax_up if want.y > 0 else vmax_down)
	var dy := wrapf(pan - yaw, -PI, PI)
	if fixed_cam and look_target != Vector3.INF:
		var dl := look_target - pos
		dy = wrapf(atan2(-dl.x, -dl.z) - yaw, -PI, PI)
	set_sticks(h.x, h.y, thr, dy * 2.0 / yaw_rate_max)


## The operator's aim: ease the gimbal toward a world point within its rate
## limits and an acceleration limit (no snaps).
func aim_at(target: Vector3, dt: float) -> void:
	if fixed_cam:
		var fwd := Vector3(-sin(yaw), 0, -cos(yaw))
		var lean_fwd := Vector3(tilt.x, 0, tilt.y).dot(fwd)
		pan = yaw
		pitch = clampf(cam_uptilt - lean_fwd, gim_tilt_min, gim_tilt_max)
		return
	var d := (target - pos).normalized()
	var want_pan := atan2(-d.x, -d.z)
	var want_pitch := clampf(asin(clampf(d.y, -1, 1)), gim_tilt_min, gim_tilt_max)
	var rp := clampf(wrapf(want_pan - pan, -PI, PI) * gim_gain, -gim_pan_rate, gim_pan_rate)
	var rt := clampf((want_pitch - pitch) * gim_gain, -gim_tilt_rate, gim_tilt_rate)
	pan_vel = move_toward(pan_vel, rp, gim_acc * dt)
	pitch_vel = move_toward(pitch_vel, rt, gim_acc * dt)
	pan = wrapf(pan + pan_vel * dt, -PI, PI)
	pitch = clampf(pitch + pitch_vel * dt, gim_tilt_min, gim_tilt_max)


## Advance the craft by dt (keep dt at 1/240 s or less; sub-step per frame).
func step(dt: float) -> void:
	var fwd := Vector3(-sin(yaw), 0, -cos(yaw))
	var right := Vector3(cos(yaw), 0, -sin(yaw))
	var v_cmd := (right * sticks.x + fwd * sticks.y) * vmax_h
	if v_cmd.length() > vmax_h:
		v_cmd = v_cmd.normalized() * vmax_h
	var vh := Vector3(vel.x, 0, vel.z)
	# Flight controller: lean for the acceleration it needs (drag included).
	var a_need := (v_cmd - vh) * vel_gain + vh * vh.length() * drag_k
	var lean := minf(atan(a_need.length() / G), tilt_max)
	var t_des := Vector2(a_need.x, a_need.z).normalized() * lean if a_need.length() > 0.0001 else Vector2.ZERO
	var t_step := (t_des - tilt) * minf(1.0, dt / tilt_tau)
	if t_step.length() > tilt_rate * dt:
		t_step = t_step.normalized() * tilt_rate * dt
	tilt += t_step
	if tilt.length() > tilt_max:
		tilt = tilt.normalized() * tilt_max
	# What the lean and the air actually do.
	var a_h := Vector3.ZERO
	if tilt.length() > 0.0001:
		var dir2 := tilt.normalized()
		a_h = Vector3(dir2.x, 0, dir2.y) * G * tan(tilt.length())
	a_h -= vh * vh.length() * drag_k
	var vy_cmd := sticks.z * (vmax_up if sticks.z > 0 else vmax_down)
	var a_y := clampf((vy_cmd - vel.y) * vert_gain, -vert_acc, vert_acc)
	vel += Vector3(a_h.x, a_y, a_h.z) * dt
	pos += vel * dt
	yaw_vel = move_toward(yaw_vel, sticks.w * yaw_rate_max, deg_to_rad(400.0) * dt)
	yaw = wrapf(yaw + yaw_vel * dt, -PI, PI)
	_sway_t += dt


## Fly an existing drawn camera for one frame of length dt: the drawn move is
## the pilot's mark, chased `lead` s ahead, then held on two leashes so a
## lagging rig never drifts into a character or off the action:
##   max_dev  metres the lens may stray from the drawn lens
##            (measured good: inspire3 2.5, fpv 1.2, crane 0.5, handheld 0.35)
##   max_aim  degrees the gimbal may lag the drawn aim (6 worked)
## A drawn jump (a hard cut inside the shot) restarts the rig there.
## Call start() first. Returns [lens, look_point, up].
func chase_drawn(drawn_pos: Vector3, drawn_look: Vector3, dt: float, lead: float = 0.2,
		max_dev: float = 1.0, max_aim: float = 6.0) -> Array:
	if _drawn_pos == Vector3.INF or _drawn_pos.distance_to(drawn_pos) > maxf(3.0, 60.0 * dt):
		start(drawn_pos, drawn_look)
		return [drawn_pos, drawn_look, Vector3.UP]
	var v_draw := (drawn_pos - _drawn_pos) / maxf(dt, 0.0001)
	var l_draw := (drawn_look - _drawn_look) / maxf(dt, 0.0001)
	_drawn_pos = drawn_pos
	_drawn_look = drawn_look
	var target := drawn_pos + v_draw * lead
	var aim := drawn_look + l_draw * lead
	look_target = aim
	var steps := maxi(1, roundi(dt * 240.0))
	var h := dt / steps
	for _i in steps:
		fly_toward(target, v_draw)
		aim_at(aim, h)
		step(h)
	var off := pos - drawn_pos
	if off.length() > max_dev:
		pos = drawn_pos + off.limit_length(max_dev)
	var lens := lens_pos()
	var gd := look_dir()
	var want := (aim - lens).normalized()
	var ang := gd.angle_to(want)
	var amax := deg_to_rad(max_aim)
	if ang > amax:
		gd = gd.slerp(want, 1.0 - amax / ang).normalized()
	return [lens, lens + gd * 10.0, cam_up()]


## A pilot's speed plan along a sampled path (dense points, a few per metre
## or finer): limits on along-path acceleration, cornering, climb/descent and
## top speed, with start speed v0 and end speed v1 (so legs join at matching
## speeds). The cruise speed is searched so the flight takes `dur` seconds.
## limits: {vmax, a_along, a_lat, v_vert} (plan_limits() gives a rig's).
## Returns {times, dist, top, total, fits}: fits is false when the path
## cannot be flown in `dur` within the limits (it then takes `total`).
static func plan_speeds(pts: Array, dur: float, v0: float, v1: float, limits: Dictionary) -> Dictionary:
	var n := pts.size()
	var cum: Array[float] = [0.0]
	for k in range(1, n):
		cum.append(cum[k - 1] + (pts[k] as Vector3).distance_to(pts[k - 1]))
	var vmax: float = limits.get("vmax", 18.0)
	var a_along: float = limits.get("a_along", 5.5)
	var a_lat: float = limits.get("a_lat", 5.0)
	var v_vert: float = limits.get("v_vert", 7.0)
	var lim: Array[float] = []
	for k in n:
		var a: Vector3 = pts[maxi(k - 6, 0)]
		var b: Vector3 = pts[k]
		var c: Vector3 = pts[mini(k + 6, n - 1)]
		var d1 := b - a
		var d2 := c - b
		var curv := 0.0
		if d1.length() > 0.01 and d2.length() > 0.01:
			curv = d1.normalized().angle_to(d2.normalized()) / maxf(0.01, 0.5 * (d1.length() + d2.length()))
		var dir := (c - a).normalized()
		var v := vmax
		if curv > 0.0001:
			v = minf(v, sqrt(a_lat / curv))
		if absf(dir.y) > 0.01:
			v = minf(v, v_vert / absf(dir.y))
		lim.append(v)
	var lo := 0.3
	var hi := vmax
	var best := {}
	for _it in 40:
		var vc := 0.5 * (lo + hi)
		var vs := _speeds(lim, cum, vc, v0, v1, a_along)
		var ts: Array[float] = [0.0]
		var top := 0.0
		for k in range(1, n):
			ts.append(ts[k - 1] + (cum[k] - cum[k - 1]) / maxf(0.05, 0.5 * (vs[k] + vs[k - 1])))
			top = maxf(top, vs[k])
		best = {"times": ts, "dist": cum, "top": top, "total": ts[n - 1]}
		if ts[n - 1] > dur:
			lo = vc
		else:
			hi = vc
	best["fits"] = (best["total"] as float) <= dur * 1.02
	return best


## The least time the path can be flown in within the limits (cruise at
## vmax). Compare it with the story time before drawing any move.
static func min_duration(pts: Array, v0: float, v1: float, limits: Dictionary) -> float:
	return plan_speeds(pts, 0.0, v0, v1, limits)["total"]


static func _speeds(lim: Array[float], cum: Array[float], vc: float, v0: float, v1: float, a_along: float) -> Array[float]:
	var n := lim.size()
	var vs: Array[float] = []
	for k in n:
		vs.append(minf(lim[k], vc))
	vs[0] = minf(vs[0], v0)
	for k in range(1, n):
		vs[k] = minf(vs[k], sqrt(vs[k - 1] * vs[k - 1] + 2.0 * a_along * (cum[k] - cum[k - 1])))
	vs[n - 1] = minf(vs[n - 1], v1)
	for k in range(n - 2, -1, -1):
		vs[k] = minf(vs[k], sqrt(vs[k + 1] * vs[k + 1] + 2.0 * a_along * (cum[k + 1] - cum[k])))
	return vs


## Camera guard: a close camera (within max_dist of what it looks at) never
## sits inside a wall or roof. A ray from the look point back to the lens;
## when the set is in the way the lens comes in in front of it at once, then
## eases back out over later frames, as a game camera does. Characters are
## skipped (pass their RIDs in `movers`) so a body crossing the lens does
## not yank the camera. Keep `prev_frac` per shot (start at 1.0).
## Returns [lens, frac]; pass frac back as prev_frac next frame.
static func guard_lens(space: PhysicsDirectSpaceState3D, lens: Vector3, look: Vector3, movers: Array[RID],
		prev_frac: float = 1.0, max_dist: float = 14.0, ease_out: float = 0.08) -> Array:
	var to_cam := lens - look
	var dist := to_cam.length()
	if dist < 0.5 or dist > max_dist:
		return [lens, 1.0]
	var dir := to_cam / dist
	var ex: Array[RID] = movers.duplicate()
	var frac := 1.0
	for _i in 8:
		var q := PhysicsRayQueryParameters3D.create(look + dir * 0.3, lens + dir * 0.4)
		q.exclude = ex
		var h := space.intersect_ray(q)
		if h.is_empty():
			break
		frac = clampf(((h.position as Vector3) - look).length() / dist - 0.5 / dist, 0.15, 1.0)
		break
	frac = minf(frac, lerpf(prev_frac, 1.0, ease_out))
	return [look + to_cam * frac, frac]
