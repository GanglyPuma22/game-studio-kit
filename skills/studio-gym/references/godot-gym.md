# Godot gym tooling

Read alongside [studio-gym](../SKILL.md) when the game runs on Godot 4.x. This file covers how to build the gym in the engine. Launch and evidence rules stay those of [studio-godot](../../studio-godot/SKILL.md) and [studio-playtest](../../studio-playtest/SKILL.md): every run goes through the kit's `playtest`, `launch` or `batch` commands, never a raw engine shell-out.

## Structure

Keep the gym in its own folder (for example `res://scripts/gameplay_gym/`) with one entry node, one builder per room and one HUD. The game's entry script adds the gym node only when a launch flag is present:

```gdscript
const GYM := preload("res://scripts/gameplay_gym/gym_root.gd")

func _ready() -> void:
    if "--gameplay-gym" in OS.get_cmdline_user_args():
        var gym := GYM.new()
        gym.name = "GameplayGym"
        add_child(gym)
```

User arguments arrive after `--` on the engine command line, which is where a [launch profile](../../../templates/launch-profile.json)'s `feature_flags` put them. With no flag, nothing in the gym folder is instantiated.

Prefer `preload` of script paths over `class_name` for gym scripts when the project's play route does not rebuild the global class cache (an exported or pre-imported build launched without the editor). A new `class_name` that the cache never learned about fails only on that machine.

**Build rooms from data.** Write each room as a dictionary or JSON entry whose numbers are the gym plan's numbers (ramp angles, step heights, gap widths, pad slopes), and have one builder turn it into nodes. Then the geometry, the labels and the expected values come from one place, and changing a room means changing a number, not dragging a mesh.

## Greybox geometry

- **Bodies.** `StaticBody3D` with a `CollisionShape3D` (`BoxShape3D` for slabs, steps and rotated ramps; `ConvexPolygonShape3D` for wedges) and a `MeshInstance3D` of the same size. Size the shape resource; never scale the collision node ([physics and precision](../../studio-godot/references/physics-and-precision.md)).
- **CSG** (`CSGBox3D`, `CSGPolygon3D` with `use_collision`) is fast to sketch with but rebuilds its mesh and collision when changed and costs more at runtime. Use it for a first layout, then let the builder emit plain bodies.
- **Moving rooms.** On a world that moves (a rotating planet, a ship deck), parent the rooms to the frame the player stands in, or drive each slab as an `AnimatableBody3D` with `sync_to_physics` on so a `CharacterBody3D` standing on it is carried rather than left behind.
- **Grid material.** A `StandardMaterial3D` with world-space triplanar mapping (`uv1_triplanar`, `uv1_world_triplanar`) and a 1 m grid texture keeps 1 m squares on every box whatever its size. Fix one albedo per meaning (walkable, too steep, hazard, interactable, landing target) and reuse it across rooms.
- **Labels.** A `Label3D` with billboard on and `fixed_size` for each metric on the geometry ("44°", "0.30 m", "gap 3.5 m"). Generate the text from the room data so a label cannot disagree with the geometry it names.
- **Scale marker.** A 1.8 m capsule or post in every room. The kit's harbor fixture uses the same marker.

## Floors, surfaces and the game's own rules

- `CharacterBody3D` uses `floor_max_angle`, `floor_snap_length`, `floor_stop_on_slope` and `max_slides`. Read the values the game sets and put them in the inventory; the slope and step ladders bracket them.
- If the game decides ground through its own registry (certified terrain, a support owner, a landable flag) rather than `is_on_floor()` alone, register gym slabs through that registry. Plain greybox that the game refuses as floor is gap number one, and it is a fact about the game worth knowing.
- **Surface tags.** Put the tag on the collider: `body.set_meta("surface", "mud")`, or a named `PhysicsMaterial`. The controller reads it from `get_last_slide_collision().get_collider()` or a down ray. The HUD shows the tag even before the audio uses it.
- **Footstep cue table.** A dictionary from tag to an `AudioStreamRandomizer` per event (step, land, jump). Until the game has one, the sound zoo shows tags on the HUD and reports every cue as the single default.
- **Water.** Use the game's own water provider with a known depth function, not a separate `Area3D` the controller never reads.

## HUD, keys and teleport

- The HUD is a `CanvasLayer` with labels updated in `_process` from the game's own getters. It never recomputes grounded, slope or depth itself.
- Add gym input actions at runtime with `InputMap.add_action()` and `InputMap.action_add_event()` only when the gym flag is on, so `project.godot` stays unchanged and normal builds have no gym keys. Check each key against the plan's `key_registry` first.
- **Teleport and reset** happen in `_physics_process`: set the body's `global_transform`, zero its velocity, clear the states a respawn clears (water, vehicle authority, landing, interaction), then call `reset_physics_interpolation()` on the body and camera so interpolation does not smear the jump across the map.

## Engine settings that change results

- **Physics backend.** Check `physics/3d/physics_engine` in `project.godot`. Jolt is the default for new 3D projects since 4.4. Record the backend in every metric snapshot, because contact tolerances differ between backends. Under Jolt an `Area3D` does not detect static bodies unless `physics/jolt_physics_3d/simulation/areas_detect_static_bodies` is on, so a water or trigger area built over greybox can silently miss.
- **Tick rate.** `physics/common/physics_ticks_per_second` sets the step. Jump apex and stopping distance measured at 60 Hz differ slightly at 120 Hz; record it.
- **Large worlds.** A double-precision build (`precision=double`) keeps far coordinates stable. Rebuild one ladder far from the origin to prove it ([physics and precision](../../studio-godot/references/physics-and-precision.md)).

## Checks, replay and performance in the engine

- **Room checks.** Copy [the harness template](../../../templates/playtest-harness.gd) per room or stage. It already drives real input actions both as polled state and as `InputEventAction` events, stamps samples with `Engine.get_physics_frames()` and `Time.get_ticks_usec()`, and fails through the log and exit code. Teleport to the room's start, run the steps, and assert the room's questions. Run with `playtest start --session driven --script res://tests/<room>_harness.gd`.
- **Metric snapshot.** Write measured numbers to a JSON file declared with `--result`, next to the harness report the kit already supplies.
- **Poll, then time out.** Assert by checking each physics frame until the condition holds or a frame limit passes, not after a fixed delay or on the input's own frame. A check pinned to one frame breaks the first time the game moves its update later in the tick.
- **Test frameworks.** GUT and GdUnit4 both exist; GdUnit4's scene runner can simulate input actions. With GUT's input sender and `use_accumulated_input` on, assertions can run before the input lands; wait a few extra frames or call `Input.flush_buffered_events()`. Use whichever the project already runs, as [testing and performance](../../studio-godot/references/testing-and-performance.md) advises, and launch it through `launch --mode test`.
- **Input record and replay.** Record `InputEventAction` presses and releases with their physics frame number into JSON; replay by feeding the same events through `Input.parse_input_event()` on the same frames. Replay is only repeatable with a fixed physics tick, seeded random number generators and no wall-clock timers in gameplay code. Record the seed and tick with the recording.
- **Frame time per room.** `Performance.get_monitor(Performance.TIME_PROCESS)` and `TIME_PHYSICS_PROCESS`, plus `RenderingServer.get_rendering_info()` draw and primitive counts, sampled on entering and leaving each room and written as events, not per frame.
