# Building a synthetic-input harness

The kit cannot know a game's action names, scene layout or what a good route
looks like, so it ships structure rather than behaviour:
[playtest-harness.gd](../../../templates/playtest-harness.gd) is a skeleton to
copy into the project as `res://tests/<route>_harness.gd` and fill in. It
generalizes the fixed five-second walk-then-respond fixture in the bundled
Harbor Pocket example into a declared route with a frame-stamped event log and
its own assertions.

Only reach for one when a person cannot practicably drive the route by hand.
See [the route decision](../SKILL.md) for that boundary before writing any of
this.

## Filling it in

1. **`SCENE_PATH`** — usually the game's main scene. A script passed through
   `--script` must extend `SceneTree` or `MainLoop`, so the template
   instantiates the scene itself; an ordinary `Node` would never run at all.
   See [runner wiring](../../studio-godot/references/testing-and-performance.md).
2. **`ROUTE`** — the steps, each pressing one of the project's own input
   actions at `press_at` seconds and releasing it at `release_at`. Overlapping
   steps are how diagonal movement or walk-while-turning is expressed. The
   template refuses an action the project's `InputMap` does not define, because
   a typo there is otherwise indistinguishable from a game that ignores input.
3. **`_sample()`** — record discrete state changes: a landing, a slope
   rejection, a chunk streaming in. Not per-frame telemetry, which buries the
   one frame that mattered and inflates the combined log the kit captures.
4. **`_assertions()`** — the named booleans this route exists to check. Every
   one must be true for the report's `ok`. Name them for what they claim
   (`stayed_grounded`, `crossed_seam`), not for what they measure. A failed
   assertion is pushed to the engine log and quits with a non-zero code,
   because that is what the kit reads: `playtest` judges a driven run from the
   log and the exit status, so a harness that only wrote `"ok": false` into its
   own report would be recorded as a clean `completed`.
5. **`MAX_SECONDS`** — the harness quits itself. `--max-minutes` is the kit's
   backstop for a harness that hangs, not the plan for how long the run takes.
   Reaching the ceiling before every step is released fails the run through a
   built-in `route_completed` check, so a route truncated by a ceiling somebody
   forgot to extend cannot report a passing experiment it never finished.

Run it:

```text
python <KIT>/scripts/studio.py playtest start --project <GAME> --config <HOST> \
  --sha256 <engine sha256> --session driven \
  --script res://tests/seam_harness.gd --max-minutes 5
```

**Do not pass `--studio-playtest=` and do not declare the report with
`--result`.** The kit knows the run directory, so it supplies
`--studio-playtest=<run>/harness.json` itself, records that path in
`playtest.json`, and hashes the report into `exit.json`. Keeping those two
paths in sync by hand was a real trap: naming a different path in the
passthrough produced a bare "declared result missing" with nothing to say why.
An explicit `--studio-playtest=` in the passthrough is now refused. The
argument is absolute because that is what `OS.get_cmdline_user_args()` hands
the engine, matching the
[studio-smoke-v1 protocol](../../studio-godot/references/execution.md).

A report that is absent gives `harness_report_missing`, one that does not parse
gives `harness_report_unreadable`, and one whose `ok` is not true gives
`harness_failed`. That is a second reading of the same verdict the harness
already pushes to the log, not the only one. Use `--result` for anything *else*
the route is supposed to produce.

A driven session takes its scene from the harness's own `SCENE_PATH`, so
`--scene` is refused alongside `--script`: a scene named on the command line
would be hashed into the receipt as evidence of a route the harness never drove.

Re-running the emitted `relaunch` script for a driven session rewrites that
session's `harness.json`. The hash recorded in `exit.json` is what makes such a
rewrite visible.

## Drive the game's real input path

Press the project's actual action names. Do not call movement functions
directly.

The template drives each action both ways a game can read one.
`Input.action_press` sets the polled state `Input.is_action_pressed` reports,
which is what a game checking actions in `_process`/`_physics_process` sees; an
`InputEventAction` pushed through `Input.parse_input_event` feeds the event
pipeline that a game handling actions in `_input()` reads. Driving only the
first would make a perfectly working event-driven game look like it ignored
input a player's keyboard delivers fine. Neither form synthesises a raw key
event, so a game reading keycodes directly instead of named actions still needs
a person at the keyboard — which is the ordinary-controls route anyway.

A harness that calls `player.move(Vector3.FORWARD)` proves that `move()` works.
It proves nothing about whether the game is wired to it — whether the action
exists in the `InputMap`, whether the controller reads it, whether something
consumed the event first, whether a state machine was in a mode that ignores
it. That wiring is the most common thing to break and the thing a direct call
is structurally blind to. Pressing the action exercises the same
input -> intent -> simulation chain a player's keyboard does, which is the only
version of the chain worth testing.

## Never fork the movement policy

A harness or scene adapter may own its own body. It may not own its own
numbers.

The live example: a standalone `CharacterBody3D` written for a coastal test
scene borrows `MAX_SLOPE_ANGLE` and its speeds from the shared motion policy
class the real player uses. That is the right seam — a separate body, one
owner for every tunable value. Had it copied those constants instead, the two
would have drifted within a week, and "it walks well in the test scene" would
have become a statement about the test scene alone. Every tunable — speeds,
accelerations, slope limits, step heights, gravity — stays owned by one class
shared with the real game and is read from it here.

Any adapter that does exist carries a stated retirement condition in its own
header: the concrete thing that has to become true for it to be deleted. An
adapter without one stops being a test seam and becomes a second game.

## What a green harness establishes

Wiring, and only wiring. Injected input establishes that the chain is
connected and that the simulation does not fail along the route, which is
exactly what [acceptance](../../../references/acceptance.md) says it
establishes and no more. It does not establish that the walk feels right, that
the camera stayed comfortable, or that a player would ever go that way. The
report declares `ordinary_input_review`, `visual_review` and `listening` as
`not_run` for that reason.

A passing harness on a route no person has played is a reason to schedule a
`handoff` session, not a reason to skip one.
