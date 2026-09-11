# Physics and precision for Godot 4.x at planetary scale

Read alongside [studio-godot](../SKILL.md) when a project has real 3D physics and a world
large enough that floating-point precision itself becomes a gameplay risk (planetary
terrain, orbital distances, large open worlds). This file states in-engine physics and
precision facts; it does not change the import/smoke/run/export contract in
[execution.md](execution.md), and it does not duplicate heightfield authoring, which lives
in [studio-terrain](../../studio-terrain/SKILL.md).

## Body types, pick deliberately

| Body | Use for | Notes |
|---|---|---|
| `StaticBody3D` | Terrain, level geometry, anything that never moves at runtime | Cheapest to simulate; never scale its collision shape, resize the shape resource instead |
| `AnimatableBody3D` | A body driven by animation/script that should still push physics bodies (a moving platform) | Set `sync_to_physics` correctly or it will fight the physics tick |
| `CharacterBody3D` | Player and NPC locomotion | Drive with `move_and_slide()` (no positional arguments in Godot 4.x); do not also add a `RigidBody3D` under it |
| `RigidBody3D` | Anything the physics engine should fully own (debris, props, vehicles) | Prefer `_integrate_forces()` for direct force/impulse work over per-frame velocity edits, which fight the solver |
| `Area3D` | Detection, triggers, non-colliding gravity/force fields | No collision response by itself; use `body_entered`/`area_entered` or space overrides |

Never scale a `CollisionShape3D`'s parent node to resize a hitbox — scale drifts precision
and can break the physics engine's assumptions about shape geometry. Resize the shape
resource (radius, extents, points) instead.

## Physics tick vs. process

`_physics_process(delta)` runs on the fixed physics tick (`physics_ticks_per_second`,
default 60 Hz); `_process(delta)` runs once per rendered frame, which varies with framerate.
Rules that matter at scale:

- All physics reads/writes — movement, `move_and_slide()`, force/impulse application,
  raycasts used for gameplay logic — belong in `_physics_process`, not `_process`. Reading
  `global_position` from `_process` for camera-follow is fine; **writing** physics state from
  `_process` produces framerate-dependent behavior and desyncs from the physics solver.
- Camera smoothing and purely visual interpolation belong in `_process`, ideally using
  `Node3D`'s built-in physics interpolation (`physics_interpolation_mode`, project-wide toggle
  under Rendering) rather than a hand-rolled lerp keyed to a variable frame delta.
- Do not mix a manual velocity integration in `_process` with `move_and_slide()` in
  `_physics_process` on the same body; pick one authority for a given body's motion per tick
  type and keep it there.

## Jolt vs. GodotPhysics

Godot 4.4+ defaults new 3D projects to the Jolt physics backend; it has been non-experimental
since 4.6. Jolt generally gives better joint/character stability at scale than the built-in
GodotPhysics3D backend, but a project pinned to an older Godot 4.x minor may still default to
GodotPhysics3D — check `project.godot`'s `physics/3d/physics_engine` setting rather than
assuming. When certifying geometry/physics agreement between an authored asset and its
in-engine behavior (a collision mesh against its visual mesh, a terrain heightfield against
its walkable slope claims), confirm which backend produced the result being cited; the two
backends can disagree at the margins of contact tolerance, so a captured tolerance number is
only evidence for the backend it was measured on.

Recent-version deltas worth checking against the actual engine build in use, not assumed:
`Area3D`/`SoftBody3D` overlap behavior and `WorldBoundaryShape3D.plane.d` sign both changed
across 4.x minors, and one-way collision direction has shifted at least once. Treat any
physics tolerance or collision-agreement number captured on one engine build as unverified on
a different build until re-measured; do not carry a certified tolerance across an engine
version bump without rerunning the check that produced it.

## Large-world precision (the planetary-scale problem)

Godot's default build uses single-precision `float` (`real_t == float`) for `Transform3D`,
`Basis`, `Vector3` and related math. Precision loss becomes visible well before the numeric
type actually overflows: jitter, z-fighting, and physics instability in a single-precision
build become noticeable somewhere in the range of a few kilometers from world origin, and get
materially worse as position magnitude grows, because float mantissa precision is relative to
magnitude, not absolute. For a planetary game where the player can be tens or hundreds of
kilometers from `(0,0,0)`, this is not a hypothetical: it is the dominant source of visual
jitter, physics tunneling and audio-desync bugs that "worked fine near spawn."

Two independent strategies exist, and they solve different halves of the problem:

- **Floating origin (world-shift).** Periodically re-center the world around the player: when
  the player's distance from the engine origin crosses a threshold, translate every relevant
  node (terrain chunks, other actors, physics bodies) by the same offset so the player's local
  coordinates stay near zero, and track the cumulative offset separately for anything that
  needs a true planetary/world coordinate (save data, minimap, other players in a networked
  game). This keeps the numbers the physics/rendering pipeline actually operates on small,
  regardless of build precision, but it adds real complexity: every system that caches a
  `global_position`, every raycast target, every serialized coordinate has to account for the
  shift, and a shift performed mid-physics-tick can produce a one-frame glitch if not
  sequenced carefully (perform the shift outside `_physics_process`, or at its very start,
  never mid-step).
- **Double-precision build (Large World Coordinates).** Godot can be compiled with
  `precision=double`, switching `real_t` to `double` throughout the engine's math types. This
  removes the need for a floating-origin shift for the numeric-precision problem specifically,
  at real costs: roughly double the memory footprint for every `Transform3D`/`Basis`/`Vector3`
  in the scene, custom shaders that assume `mat4`/`vec3` single-precision inputs need
  auditing (GPU-side rendering math is typically still single-precision even when CPU-side
  `real_t` is double, so a shader relying on the same precision as engine-side transforms can
  still show large-coordinate artifacts even in a double-precision build), and every binary
  Godot plugin/extension must be rebuilt against the double-precision ABI — a prebuilt
  single-precision GDExtension will not load. A double-precision build does not remove the
  benefit of keeping gameplay logic itself origin-relative where practical; it raises the
  distance at which precision becomes a problem, it does not make magnitude irrelevant.

For a project like Salvage (planetary terrain, physics-heavy, player routinely far from
origin), treat this as a design decision to make explicitly and record, not a default to
inherit silently: pick floating-origin, double-precision, or both (floating-origin to keep
render-side numbers small even inside a double-precision CPU build, since GPU precision is
usually still single), and verify the choice against an actual at-distance measurement rather
than a docs citation alone — capture a position tens of kilometers from origin, single- vs.
double-precision (or shifted vs. unshifted), and compare jitter/physics-agreement, the same
way any other geometry-agreement claim in this kit needs a measured tolerance, not an assumed
one.

## Collision layers

Use named layers/masks (Project Settings → Layer Names → 3D Physics) rather than raw bit
numbers in code or comments — `collision_layer = 4` communicates nothing on review, while a
named `Terrain` layer does. Keep the layer/mask matrix small and documented: a body's
`collision_layer` says what it *is*, its `collision_mask` says what it *notices*. A common
planetary-scale mistake is giving every dynamic body a mask that includes far-away terrain
chunks it will never actually reach that tick, inflating broad-phase cost; scope masks to
what a body can plausibly interact with given its current streamed/loaded radius.

## Point gravity and space overrides

`Area3D` supports a `gravity_space_override` mode with `gravity_point = true` for
radial/point-source gravity (a planet pulling toward its center, a black hole). Configure the
gravity point, gravity strength, and falloff (`gravity_point_unit_distance`) on the `Area3D`
in 3D — a 2D-authored recipe (`Area2D`, `Vector2` center) does not transfer to a 3D planetary
body as-is and needs rewriting against `Area3D`/`Vector3` before use; do not adapt a 2D point-
gravity example by search-and-replacing type names without re-deriving the falloff math for
three dimensions. For planetary gravity specifically, combine this with the floating-origin
or double-precision choice above: a point-gravity calculation performed against a
far-from-origin world position is exactly the kind of math that degrades first under
single-precision `float`.

## Jitter sources checklist

When a body jitters, check in this order before assuming it is a physics-engine bug:

1. **Distance from origin** — is this reproducible near `(0,0,0)` and only appearing far
   away? If so, it is precision (see above), not a collision or tick bug.
2. **Mixed-authority movement** — is something writing position in both `_process` and
   `_physics_process`, or mixing `move_and_slide()` with direct `global_position` sets?
3. **Interpolation mismatch** — is `physics_interpolation_mode` inconsistent between a moving
   platform (`AnimatableBody3D`) and the character riding it (`sync_to_physics` unset)?
4. **Scaled collision shapes** — is a parent `Node3D` scale non-1.0 above a `CollisionShape3D`?
5. **Engine-build mismatch** — was the tolerance that flagged this jitter measured on a
   different Godot build or physics backend than the one currently running?

Certifying that geometry/physics "agrees" between an authored asset and its runtime behavior
always means a measured tolerance against the actual running build, at the actual distances
the game uses, following the same evidence discipline as import verification in
[studio-godot](../SKILL.md) — a claim without a captured measurement is not evidence.

## Sources

Written for this kit after the 2026-09-11 audit of two community skill sets; the guidance is
restated in the kit's own words and no text or GDScript is copied from either:

- GodotPrompter, https://github.com/jame581/GodotPrompter (Superpowers-style skills; the
  `physics-system` and `scene-organization` skills were the research inputs).
- gd-agentic-skills, https://github.com/thedivergentai/gd-agentic-skills, LGPL-3.0 (the
  `godot-physics-3d`, `godot-3d-world-building`, `godot-genre-open-world`,
  `godot-performance-optimization` and `godot-debugging-profiling` skills were the research
  inputs). Under its licence, only the ideas are reused here, never its files.
