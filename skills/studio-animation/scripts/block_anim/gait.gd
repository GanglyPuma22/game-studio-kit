## A four-legged gait from real footfall patterns (references/block-motion-rules.md,
## rules 6 and 10): which feet are down at each moment of the stride, where
## each planted foot holds still on the ground, and where each lifted foot
## swings to. It also gives the body's rhythm: how loaded the hind and fore
## ends are and how the spine flexes and extends.
##
## Limbs: 0 left hind, 1 right hind, 2 left fore, 3 right fore. The gait
## slides from walk (0) through canter (1) to rotary gallop (2); with
## `table = BIPED`, a two-legged walk (0) to run (1) on limbs 0 and 1.
##
## Feet plant where they land and stay there until they lift, so they never
## slide while down. Driven by the body's own speed on each screen: it adds
## no network data.
extends RefCounted

const LH := 0
const RH := 1
const LF := 2
const RF := 3

## Per gait: when each foot lands (share of the stride), how long it stays
## down (duty), the stride share where the spine flexes most, and how much.
## The gallop is shifted so it shares its timing with the canter as far as
## a rotary gallop can (the hind order flips through a bound).
const GAITS := [
	{"off": [0.0, 0.5, 0.25, 0.75], "duty": 0.65, "flex_at": 0.0, "flex": 0.0},   # walk
	{"off": [0.0, 0.3, 0.3, 0.6], "duty": 0.35, "flex_at": 0.85, "flex": 0.35},  # canter, right lead (flight 0.95..1)
	{"off": [0.1, 0.0, 0.5, 0.6], "duty": 0.28, "flex_at": 0.94, "flex": 1.0},   # rotary gallop
]
## Two legs (limbs 0 and 1; 2 and 3 copy them): a walk, whose feet overlap
## (double support), and a run, with a flight after each foot (duty under
## a half). A biped's walk and run share the alternating footfalls; the run
## comes from a shorter contact, not a different order.
const BIPED := [
	{"off": [0.0, 0.5, 0.0, 0.5], "duty": 0.6, "flex_at": 0.0, "flex": 0.0},    # walk
	{"off": [0.0, 0.5, 0.0, 0.5], "duty": 0.36, "flex_at": 0.0, "flex": 0.0},   # run
]

## The gaits step() blends through, by mix (GAITS, or BIPED for two legs).
var table: Array = GAITS

## Where each foot rests (body frame, on the ground), and how high it lifts.
var home: Array = [Vector3.ZERO, Vector3.ZERO, Vector3.ZERO, Vector3.ZERO]
var lift: Array = [1.0, 1.0, 1.0, 1.0]
## Now: stride phase, gait mix, stride length (m).
var phase := 0.0
var mix := 0.0
var stride := 1.0
var duty := 0.65
var _off: Array = [0.0, 0.5, 0.25, 0.75]
var _flex_at := 0.0
var _flex := 0.0
var _down: Array = [false, false, false, false]
var _plant: Array = [Vector3.ZERO, Vector3.ZERO, Vector3.ZERO, Vector3.ZERO]
var _from: Array = [Vector3.ZERO, Vector3.ZERO, Vector3.ZERO, Vector3.ZERO]
var _at: Array = [Vector3.ZERO, Vector3.ZERO, Vector3.ZERO, Vector3.ZERO]
var _u: Array = [0.0, 0.0, 0.0, 0.0]
var _live := false
## A planted foot this far (m) from where the stride wants it (the body
## turned hard over it) steps there quickly instead of crossing over.
var max_off := 2.0
var _q: Array = [1.0, 1.0, 1.0, 1.0]
var _qfrom: Array = [Vector3.ZERO, Vector3.ZERO, Vector3.ZERO, Vector3.ZERO]


## Forget the feet (they re-plant from the home pose next step).
func reset() -> void:
	_live = false
	for i in 4:
		_q[i] = 1.0
		_qfrom[i] = Vector3.ZERO


## Advances the gait by `delta`. `gx` is the body's transform (world),
## `vel` its velocity (world), `gait_mix` 0 walk .. 2 gallop, `cadence`
## strides per second.
func step(gx: Transform3D, vel: Vector3, gait_mix: float, cadence: float, delta: float) -> void:
	var last := table.size() - 1
	mix = clampf(gait_mix, 0.0, float(last))
	var lo := mini(int(mix), last - 1)
	var a: Dictionary = table[lo]
	var b: Dictionary = table[lo + 1]
	var k := mix - float(lo)
	for i in 4:
		var d := wrapf(float(b.off[i]) - float(a.off[i]), -0.5, 0.5)
		_off[i] = fposmod(float(a.off[i]) + d * k, 1.0)
	duty = lerpf(a.duty, b.duty, k)
	_flex_at = lerpf(a.flex_at, b.flex_at, k)
	_flex = lerpf(a.flex, b.flex, k)
	var flat := Vector3(vel.x, 0.0, vel.z)
	var speed := flat.length()
	cadence = maxf(cadence, 0.05)
	stride = maxf(speed / cadence, 0.01)
	phase = fposmod(phase + cadence * delta, 1.0)
	var inv := gx.affine_inverse()
	var travel: Vector3 = inv.basis * flat
	travel = travel.normalized() if travel.length() > 0.01 else Vector3.FORWARD
	var ground := gx.origin.y
	for i in 4:
		var f := fposmod(phase - float(_off[i]), 1.0)
		var down := f < duty
		var land: Vector3 = home[i] + travel * (0.5 * duty * stride)
		if not _live:
			# Start mid-stride: planted feet where they would be by now.
			var w: Vector3
			if down:
				w = gx * (home[i] + travel * (duty * stride * (0.5 - f / duty)))
			else:
				var su := (f - duty) / maxf(1.0 - duty, 0.01)
				w = gx * (home[i] + travel * (duty * stride * (su - 0.5)))
			w.y = ground
			_plant[i] = w
			_from[i] = w
			_at[i] = w
			_down[i] = down
		if down:
			if not _down[i]:
				var p: Vector3 = gx * land
				p.y = ground
				_plant[i] = p
				_q[i] = 1.0
			var ideal: Vector3 = home[i] + travel * (duty * stride * (0.5 - f / maxf(duty, 0.01)))
			if (inv * (_plant[i] as Vector3)).distance_to(ideal) > max_off and _q[i] >= 1.0:
				var p2: Vector3 = gx * ideal
				p2.y = ground
				_qfrom[i] = _at[i]
				_plant[i] = p2
				_q[i] = 0.0
			if _q[i] < 1.0:
				_q[i] = minf(1.0, float(_q[i]) + delta / 0.18)
				var qe: float = _q[i] * _q[i] * (3.0 - 2.0 * _q[i])
				var pq: Vector3 = (_qfrom[i] as Vector3).lerp(_plant[i], qe)
				pq.y = ground + float(lift[i]) * 0.6 * sin(PI * float(_q[i]))
				_at[i] = pq
			else:
				_at[i] = _plant[i]
			_u[i] = f / maxf(duty, 0.01)
		else:
			if _down[i]:
				_from[i] = _at[i]
				_q[i] = 1.0   # a corrective step still in the air hands over to the swing
			var u := (f - duty) / maxf(1.0 - duty, 0.01)
			var left := (1.0 - u) * (1.0 - duty) / cadence
			var to: Vector3 = gx * land + flat * left
			to.y = ground
			var e := u * u * (3.0 - 2.0 * u)
			var p2: Vector3 = (_from[i] as Vector3).lerp(to, e)
			# Start from the foot's height at liftoff (above ground when a
			# corrective step was cut short), so the swing does not drop it.
			p2.y = maxf(ground + float(lift[i]) * sin(PI * u), lerpf((_from[i] as Vector3).y, ground, e))
			_at[i] = p2
			_u[i] = u
		_down[i] = down
	_live = true


## Where limb i's foot is now (world).
func foot(i: int) -> Vector3:
	return _at[i]


## True while limb i's foot is down (and not stepping round).
func planted(i: int) -> bool:
	return _down[i] and float(_q[i]) >= 1.0


## How far through its stance (down) or swing (up) limb i is, 0..1.
func progress(i: int) -> float:
	return _u[i]


## How hard the hind (fore) end is pressing down now: 0 in the air, about 1
## at mid-stance of one foot.
func load(fore: bool) -> float:
	var t := 0.0
	for i in ([LF, RF] if fore else [LH, RH]):
		if _down[i]:
			t += sin(PI * float(_u[i]))
	return t


## No foot down: the body is in flight.
func airborne() -> bool:
	return not (_down[0] or _down[1] or _down[2] or _down[3])


## The spine now: + flexed (gathered, back arched, legs under), -
## extended (legs reaching fore and aft). Flexion is about twice extension.
func spine() -> float:
	var c := cos(TAU * (phase - _flex_at))
	return _flex * (c if c > 0.0 else c * 0.5)
