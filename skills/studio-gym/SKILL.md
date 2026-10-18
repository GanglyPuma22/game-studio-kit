---
name: studio-gym
description: Plan and build a gameplay gym for a specific game, inventorying every player verb and system with its current numbers, mapping each to a greybox room with a measurable expected value, laying the rooms out with a metrics HUD and teleport hub, and wiring automated room checks and playtest capture through `studio playtest start`, with `studio launch` only for project-owned scripts that write their own results.
---

# Studio gym

A gameplay gym is a project-owned test space where every player verb meets geometry built to measure it: ramps at labelled angles, gaps at labelled widths, a pool with a known depth curve, a strip of tagged surfaces. Studios also call parts of it a mechanics gym, physics gym, audio gym or sound zoo, test bed and greybox level; here they are rooms of one gym. It is the living specification of the game's systems. A design note that says "the player climbs 45°" becomes a room where 44° climbs and 46° slides, a number on screen, and a check that fails the day it stops being true.

Inputs: declared game root, host config, the expected engine SHA-256, the game's source, any existing lab or test scenes, and the question the gym must answer first (often "what can the player actually do today, and where does it break?"). Output a [gym plan](../../templates/gym-plan.json) recorded in the project, a gym entry behind a default-off launch flag, a metrics HUD, room checks that run without a person, and recorded playtest sessions on the gym route. A gym is tailored to one game. This skill is the method and the starting catalogue, not a fixed room list.

Run the absolute [helper entrypoint](../../scripts/studio.py) with an explicit game root. Read [acceptance](../../references/acceptance.md) before writing a verdict, and [studio-playtest](../studio-playtest/SKILL.md) for how sessions are driven and recorded.

## Rules that make a gym trustworthy

- **Run the real code.** The gym places geometry, measures and teleports. It never forks the player controller, ship, audio or interaction code to make a room work. A gym that tests a copy of the movement policy documents the copy.
- **Greybox must pass through the game's own rules.** If the game only treats certified or registered surfaces as floor, the gym registers its slabs through that same route. When plain geometry is not floor, not landable or has no surface tag, that is a finding about the game, recorded as a gap, not something the gym quietly special-cases.
- **Every room states its expected value before it is built.** The value comes from the inventory's current numbers ("walk limit 45°, so 44° climbs and 46° does not"). What happens past a limit (slide, block or fall) also comes from the controller, never from what games usually do. A room without an expected value is scenery.
- **Bracket every threshold.** Put geometry just below, at and just above each limit. The interesting behaviour lives at the edge, and a single "45° ramp" cannot tell a correct limit from one that is 10° off.
- **Gaps are the first deliverable.** The first build exposes what the game cannot do yet: no step-up, no swimming, one surface type for every footstep, no way to place a creature at a chosen spot. Each gap goes in the plan's `gaps` list with the room that exposed it. Game changes that close a gap are separate, default-off work, not part of the gym.
- **The gym is not the canonical route.** A feature observed in the gym runs; it is not installed until a person meets it on the canonical route ([studio-playtest](../studio-playtest/SKILL.md)). A gym observation can feed a review, but it never sets a feature row to `human_verdict: accepted` on its own.

## Step 1: inventory verbs and systems

List every player verb and every system a verb touches before designing a single room. For each row record:

| Field | What goes in it |
|---|---|
| `verb` | Walk, sprint, jump, climb, swim, grapple, interact, board, fly, land, crouch, attack. One row per verb the player triggers |
| `input` | The project's own input action names, read from the `InputMap` or equivalent |
| `owner` | The file and function that owns the behaviour, as `path:line` |
| `numbers` | Current tuning values read from code: speeds, accelerations, limits, timers, ranges. Copied from source with the location, never remembered or estimated |
| `states` | Entry condition, active, cooldown, exit, interruption. What stops it |
| `feedback` | Animation, sound, camera, VFX and UI events it fires |
| `touches` | Physics layers, water, surface types, streaming, AI perception, save state |
| `isolated_today` | Whether a person can reach and repeat it in a minute without the full game around it, and if not, why |

Then list systems that are not verbs but shape every verb: camera, time scale, day and night, weather, world streaming, large-world precision, frame budget. Cross-check the list against the input map, the controller's state machine and any existing debug or lab scenes; a verb that exists only in a debug scene still belongs in the inventory. Read numbers from source even when a design document states them, and record disagreements between the two as gaps.

## Step 2: map each row to rooms with measurable metrics

Every inventory row maps to at least one room, or carries an explicit `not_in_gym` reason. Each room answers a small cluster of related questions and names, for each question, the metric read on screen and the expected value. Start from the [room catalogue](references/room-catalog.md), which lists the standard rooms by family (movement, physics, water, surfaces and audio, camera, interaction, creatures and AI, vehicles and flight, streaming and performance) with their geometry and metrics, then cut and add rooms for this game.

Write each room into the gym plan as `id`, `family`, `questions` (each with `metric`, `expected`, `tolerance` and the inventory `source` it came from), `geometry`, `build_stage` and `check`. Group the rooms into three build stages:

1. **Rooms with live metrics.** The hub, the metrics HUD, and the rooms for verbs that work today. This stage exposes most of the gaps.
2. **Sound, environment, interactions and creatures.** Rooms that need content placed or a small game hook added behind a flag (a surface tag, a creature spawn call).
3. **Checks and the automatic run.** A pass/fail check per question, one driven route through every room, input record and replay.

For a traversal-heavy game built on a grapple, rope or swing, read [swing and grapple traversal](references/swing-traversal.md): it adds anchor, rope, momentum and camera-at-speed rooms that a walking game does not need.

## Step 3: choose layout and tooling

Lay the gym out as a **hub and spokes**: a hub with a room menu, each room reachable by one keypress or click that teleports the player to the room's start, and a reset key that returns to the current room's start. The player arrives with the game's real character, camera and HUD. Decide early:

- **Where the gym lives.** A separate scene is simplest when the game has flat ground and a scene loader. When the world itself is unusual (a moving or spherical planet, a streamed open world, large-world coordinates), place the rooms inside the real world near the spawn on their own greybox slabs that follow the world's frame, so the same precision, gravity and streaming code runs. A gym in an empty flat scene beside such a world tests none of the code that makes the world hard.
- **How it starts.** One default-off launch flag and one [launch profile](../../templates/launch-profile.json) for the gym, so a person and a harness start the same build the same way. The gym never loads in a normal launch.
- **Greybox conventions.** A 1 m grid texture, colour meaning fixed across rooms (walkable, not walkable, hazard, interactable, landing target), every metric printed on the geometry itself ("40°", "3.0 m gap"), and a 1.8 m human-scale marker in every room.
- **The metrics HUD.** One toggle. It shows the inventory's numbers live: speed, vertical speed, grounded and why not, slope under the feet, the reason a jump or action was refused, water depth and its multiplier, surface tag, last landing impact, who has control (on foot, vehicle), frame time. It reads the game's own state; it never computes a parallel answer.
- **A debug key registry.** List every key the game, its labs and other debug scenes already use before choosing gym keys, and record the gym's keys in the plan. Labs that grow separately collide on single-letter keys.
- **Event log.** Discrete events only (landed, slope rejected, entered water, surface changed, action refused), each stamped with physics frame and time, so a capture and a log can be lined up later.

For Godot, read [Godot gym tooling](references/godot-gym.md): scene structure, CSG and `StaticBody3D` greybox, registering support with the game's own ground rules, `Label3D` metric markers, the HUD as a `CanvasLayer`, Jolt and large-world notes, and how the room checks run through the kit.

## Step 4: wire in automated checks and playtest capture

Turn each room question into a check and each room into a route. [Checks and capture](references/checks-and-capture.md) covers the full pattern; the essentials:

- **Room checks.** A driven harness from [the harness template](../../templates/playtest-harness.gd) per room or per stage, pressing the project's real input actions and asserting named booleans such as `climbs_44_deg` and `refused_46_deg`. Run it with `playtest start --session driven`, which supplies the report path the template needs. `studio launch` and `batch` do not supply that path, so use them only for a project-owned script that writes its own declared result. A check that passes has shown wiring, not feel.
- **Metric snapshots.** The harness also writes the measured numbers (jump apex, time to top speed, stopping distance, landing impact) in its report. Compare each against the plan's expected value and tolerance, and against the previous build's snapshot, so a tuning change shows up as a moved number instead of a vague "feels different".
- **One route through every room.** Stage 3 adds a driven route that visits each room in order and writes one report, so the whole gym runs as a regression check before a merge.
- **Performance per room.** Record frame time while each room runs. A gym room that costs 30 ms on its own will not cost less in the full game.
- **Human sessions on the gym route.** Play the gym with `playtest start --session handoff` or `attended` for feel, camera and sound. Capture video with the metrics HUD visible and the event log running, so a moment in the video can be matched to a logged event and a number.

Report each room as built, checked (automated check passing), and observed (a person played it), separately, each with the content digest of the build it was established on. A status from an older build is stale until it is run again. Return the plan, the gap list with the room that exposed each gap, the run directories and the question still open.

## Tailoring by game

| Game shape | Rooms to weight |
|---|---|
| On-foot exploration | Slope and step ladders, jump yard, surface strip with footsteps, water depth ramp, interaction room, camera rooms |
| Vehicle or ship flight | Speed lanes with distance markers, landing pads by slope, altitude bands, obstacle courses, boarding and exit, crash and recovery |
| Grapple, rope or swing traversal | Anchor field, swing arcs, momentum lanes, target-assist room, camera at speed ([swing and grapple traversal](references/swing-traversal.md)) |
| Combat | Target dummies with readable hit volumes, timing window room, enemy approach angles, crowd density room |
| Large or procedural world | Streaming edge room, precision far from origin, the seams between generated tiles |

## Where this hands off

| Next need | Read |
|---|---|
| Running sessions on the gym route, harness mechanics | [studio-playtest](../studio-playtest/SKILL.md) and its [harness](../studio-playtest/references/harness.md) |
| Probes, headless runners and performance budgets | [testing and performance](../studio-godot/references/testing-and-performance.md) |
| Physics bodies, tick discipline, large-world precision | [physics and precision](../studio-godot/references/physics-and-precision.md) |
| Footstep and surface cue mapping | [studio-audio](../studio-audio/SKILL.md) |
| The verb's intended design and feedback table | [studio-game-design](../studio-game-design/SKILL.md) |
| Acceptance verdicts and the evidence pack | [studio-review](../studio-review/SKILL.md) |
| Where the room designs and practices come from | [sources](references/sources.md) |

A passing room check is run health and wiring. It never establishes that a verb feels right, that the camera is comfortable or that the mix reads, and `acceptance` stays `not_established` until a person has played it.
