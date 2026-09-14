# Playtest harness template — a bounded, self-quitting route driver.
#
# Fill in SCENE_PATH, ROUTE and _assertions(). Run it with:
#   playtest start --project <GAME> --config <HOST> --sha256 <engine sha256> \
#     --session driven --script res://tests/playtest_harness.gd \
#     --max-minutes 5 --result artifacts/playtests/route.json \
#     -- --studio-playtest=<absolute JSON path>
#
# A script passed through --script must extend SceneTree or MainLoop, so this
# instantiates the game scene itself; an ordinary Node would never run.
#
# TWO RULES, BOTH OF WHICH HAVE ALREADY GONE WRONG IN A REAL PROJECT:
#
# 1. Drive the game's real input path. Press the project's own action names
#    through Input.action_press/action_release so this exercises the same
#    input -> intent -> simulation chain a player does. Calling a movement
#    function directly proves that function works and nothing about whether
#    the game is wired to it, which is the failure this harness exists to
#    catch.
#
# 2. Never fork the movement policy. A harness or scene adapter may own its
#    own body, but every tunable value — speeds, accelerations, slope limits,
#    step heights — must stay owned by one class shared with the real game
#    and read from it here. A harness that copies those numbers proves only
#    that the copy walks well. Any adapter that does exist carries a stated
#    retirement condition in its own header: what has to become true for it
#    to be deleted.
#
# This harness establishes wiring, not usability. See
# skills/studio-playtest/references/harness.md and references/acceptance.md.

extends SceneTree

## The scene to drive. Usually the game's main scene.
const SCENE_PATH := "res://main.tscn"

## Hard ceiling. The harness quits itself; the kit's --max-minutes is a backstop,
## not the plan.
const MAX_SECONDS := 60.0

## The route. Each step presses one of the project's own input actions at
## `press_at` seconds and releases it at `release_at`. Overlapping steps are
## allowed and are how diagonal movement or walk-while-turning is expressed.
const ROUTE: Array = [
	{"action": "walk_forward", "press_at": 0.5, "release_at": 6.0},
	{"action": "turn_right", "press_at": 3.0, "release_at": 3.6},
]

var _output_path := ""
var _seconds := 0.0
var _events: Array = []
var _held := {}
var _scene: Node = null
var _finished := false

func _initialize() -> void:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--studio-playtest="):
			_output_path = argument.trim_prefix("--studio-playtest=")
	var packed := load(SCENE_PATH)
	if packed == null:
		_fail("Cannot load " + SCENE_PATH)
		return
	_scene = packed.instantiate()
	root.add_child(_scene)

func _physics_process(delta: float) -> bool:
	if _finished:
		return true
	_seconds += delta
	for step in ROUTE:
		var action: String = step["action"]
		if not InputMap.has_action(action):
			# A typo here would otherwise look like a game that ignores input.
			_fail("Project has no input action named " + action)
			return true
		if _seconds >= step["press_at"] and not _held.get(action, false):
			Input.action_press(action)
			_held[action] = true
			_record("press", action)
		elif _seconds >= step["release_at"] and _held.get(action, false):
			Input.action_release(action)
			_held[action] = false
			_record("release", action)
	_sample()
	if _seconds >= MAX_SECONDS or _route_complete():
		_report()
		return true
	return false

func _route_complete() -> bool:
	for step in ROUTE:
		if _seconds < step["release_at"]:
			return false
	return true

## Stamp every event with real time and the physics frame, so a defect that
## only appears on one tick can be pointed at rather than described.
func _record(kind: String, detail: String, extra: Dictionary = {}) -> void:
	var event := {
		"kind": kind,
		"detail": detail,
		"seconds": snappedf(_seconds, 0.001),
		"usec": Time.get_ticks_usec(),
		"physics_frame": Engine.get_physics_frames(),
	}
	event.merge(extra)
	_events.append(event)

## Fill in: record discrete state changes, not per-frame telemetry. A landing,
## a slope rejection, a stream-in. Per-frame output buries the frame that
## mattered and inflates the log the kit captures.
func _sample() -> void:
	pass

## Fill in: the assertions this route exists to make. Return a dictionary of
## named booleans; every one of them must be true for the run to be ok.
func _assertions() -> Dictionary:
	return {
		"route_ran": _events.size() > 0,
	}

func _report() -> void:
	for action in _held.keys():
		if _held[action]:
			Input.action_release(action)
	var checks := _assertions()
	var passed := true
	for name in checks.keys():
		passed = passed and bool(checks[name])
	var report := {
		"kind": "playtest_harness_route",
		"engine_version": Engine.get_version_info().string,
		"scene": SCENE_PATH,
		"seconds": snappedf(_seconds, 0.001),
		"physics_frames": Engine.get_physics_frames(),
		"route": ROUTE,
		"events": _events,
		"checks": checks,
		# Injected input cannot establish any of these, so they are declared
		# not_run here rather than left for a reader to assume.
		"ordinary_input_review": "not_run",
		"visual_review": "not_run",
		"listening": "not_run",
		"ok": passed,
	}
	_write(report)
	_finished = true

func _fail(message: String) -> void:
	push_error(message)
	_write({"kind": "playtest_harness_route", "ok": false, "error": message, "events": _events})
	_finished = true

func _write(report: Dictionary) -> void:
	if _output_path == "":
		push_error("No --studio-playtest=<path> user argument; nothing was written")
		return
	var file := FileAccess.open(_output_path, FileAccess.WRITE)
	if file == null:
		push_error("Cannot write harness report to " + _output_path)
		return
	file.store_string(JSON.stringify(report, "\t"))
	file.close()
