## Keeps a foot (or paw) from sliding while it is down
## (references/block-motion-rules.md, rule 6). It follows its target, but once the
## foot is planted on the ground it holds still there; when the target has
## moved off by more than `tol`, the foot lifts and steps to it instead of
## sliding. Blends between poses (standing to running, a gait to the game's
## feet) then show as steps.
##
## Work in the world frame (so a planted foot stays put as the body moves).
##
## Give it a target the rig owns (the foot's stance under the hips), never
## a gameplay foot that has stepping logic of its own: following one makes
## the feet patter back and forth. Set `tol` to about a third of the leg
## (`configure(leg_length)` does), pair the two feet of a girdle with
## `other`, and keep `rest` above zero. With a tiny tolerance and no rest
## every small body nudge in a punch or a bite sets off another step.
extends RefCounted

## How far the target may wander from a planted foot before it steps (m).
## About a third of the leg; see configure().
var tol := 0.2
## How long a step takes (s) and how high it lifts (m).
var step_time := 0.22
var lift := 0.5
## How close to the ground counts as on it (m above the ground).
var near := 0.1
## A foot stays down at least this long (s) before it steps again, unless
## its target is `far` × `tol` away (a deliberate step, not a fidget).
var rest := 0.35
var far := 3.0


## Sizes the stepper to a leg `leg` metres long: steps when the stance has
## moved about a third of a leg, lifts about a fifth of one.
func configure(leg: float) -> void:
	tol = leg * 0.33
	lift = leg * 0.2
	near = leg * 0.05


## The other foot of the pair: one steps at a time (unless far off).
## Held weakly, so two feet paired with each other are still freed.
var other: RefCounted:
	set(v):
		_other = weakref(v) if v != null else null
	get:
		return _other.get_ref() if _other != null else null
var _other: WeakRef = null

var at := Vector3.INF
var planted := false
var _from := Vector3.ZERO
var _t := 1.0
var _lift_k := 1.0
var _down_t := 0.0
var _want := false
var _target := Vector3.INF


## The foot this frame, given where it should be (`target`, world), the
## ground height under it and the frame time.
func update(target: Vector3, ground_y: float, delta: float) -> Vector3:
	_target = target
	if at == Vector3.INF:
		at = target
		planted = target.y - ground_y < near
		return at
	var on_ground := target.y - ground_y < near
	if _t < 1.0:
		# Stepping: arc toward the (maybe moving) target.
		_t = minf(1.0, _t + delta / maxf(step_time, 0.01))
		var e := _t * _t * (3.0 - 2.0 * _t)
		at = _from.lerp(target, e) + Vector3.UP * lift * _lift_k * sin(PI * _t)
		if _t >= 1.0:
			at = target
			planted = on_ground
			_down_t = 0.0
		return at
	if not on_ground:
		# Lifted by its owner (a gait's swing, a reach): catch up with it
		# from where it was planted, the owner giving the lift.
		if planted and at.distance_to(target) > 0.01:
			_from = at
			_t = 0.0
			_lift_k = 0.0
			planted = false
			return at
		at = target
		planted = false
		return at
	if not planted:
		at = target
		planted = true
		_down_t = 0.0
		return at
	_down_t += delta
	var off := at.distance_to(target)
	if _want and off < tol * 0.25:
		_want = false   # the target came back: a queued step would land in place
	if (off > tol or _want) and (off > tol * far or _may_step()):
		_want = false
		_from = at
		_t = 0.0
		_lift_k = 1.0
		planted = false
	return at


## Down long enough, and the other foot is not mid-step.
func _may_step() -> bool:
	return _down_t >= rest and (other == null or other.stepping() == false)


func stepping() -> bool:
	return _t < 1.0


## Lift and step now (to the target, wherever it is), as when the body has
## turned too far over a planted foot.
func step_now() -> void:
	if at == Vector3.INF or _t < 1.0:
		return
	if _target != Vector3.INF and at.distance_to(_target) < tol * 0.25:
		return   # it would land where it stands: a shuffle, not a step
	if not _may_step():
		_want = true   # taken as soon as it may
		return
	_want = false
	_from = at
	_t = 0.0
	_lift_k = 1.0
	planted = false
