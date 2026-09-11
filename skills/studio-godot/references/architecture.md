# Scene and script architecture for Godot 4.x GDScript

Read this before wiring gameplay into an imported scene (see [studio-godot](../SKILL.md)) on
a large 3D project such as a planetary game with terrain, physics at world scale and many
subsystems. It states organization rules only; it does not change the import/smoke/run
contract in [execution.md](execution.md) or the material handoff in [materials.md](materials.md).

## Node tree and scene composition

Treat a scene tree as the primary architecture diagram, not decoration around a script.
Composition beats inheritance: prefer a small `Node3D` that owns child nodes and exported
resources over a deep custom-class hierarchy. A `Resource` (`.tres`) carries data and
tunables; a script attached to a node carries behavior. Keep the two separate so a designer
can retune values without touching code, and a code review can read behavior without
wading through data.

Use a rough budget, not a hard rule, to decide when a scene is doing too much: once a single
scene's own node count passes roughly fifteen direct children, or once the scene mixes more
than two concerns (say, movement, inventory UI and audio cues all on one root), split it.
Split along ownership, not file size — a `PlayerBody.tscn` that owns movement and a
`PlayerInventory.tscn` that owns items are two scenes with one clear job each, instantiated
under a shared `Player.tscn` root. Preserve the existing gameplay interface across a split:
the parent still exposes the same signals and exported properties it did before, so nothing
outside the split has to change on the same pass.

## When a script is too big

A single GDScript file crossing roughly a few hundred lines, or one that mixes input
handling, physics integration, animation state and networking in the same file, is a signal
to split by responsibility, not by arbitrary line count. Concrete split points:

- **Input vs. simulation.** Read input in one place (`_unhandled_input` or a small input
  script) and hand a normalized intent (a `Vector2`, an enum, a bool) to the simulation code.
  The simulation script should not know which key or button produced its input.
- **State machine extraction.** Once a script's behavior forks on more than three or four
  named states with different per-state logic, pull the state machine into its own script or
  a small set of state `Resource`/`Node` objects, one state per file if the per-state logic is
  non-trivial. The owning node keeps a thin `transition_to(state)` entry point and does not
  duplicate state-specific logic inline.
- **Subsystem boundary.** A 5,000-line script is almost always several subsystems sharing one
  file by accident (movement, combat, save/load, UI glue). Draw the boundary at the data each
  piece actually touches: if two blocks of the file never read or write the same fields, they
  are not one subsystem and belong in separate scripts wired together with signals or a small
  shared autoload, not copy-pasted state.
- **Keep the split shippable.** Do not split a script as a separate refactor pass with no
  behavior change to verify; pair every split with the existing smoke/run evidence in
  [execution.md](execution.md) so the split is proven behavior-preserving, not just
  structurally nicer.

## Signals vs. direct calls

Three communication shapes, used deliberately rather than picked at random:

1. **Direct call, parent to child.** A parent that owns and instantiates a child can call the
   child's methods directly (`$Weapon.fire()`). This is the cheapest and most traceable form;
   use it whenever ownership is already explicit in the tree.
2. **Signal, child to parent (or sideways).** A child never calls a method on its parent or a
   sibling directly — it does not know they exist. It emits a signal (`took_damage`,
   `item_picked_up`) and lets whoever is interested connect to it. This is what makes a scene
   reusable outside its current parent: drop the same `Enemy.tscn` into a different level and
   its signals still work with whatever connects to them there.
3. **Autoload / EventBus, for anything cross-tree.** When two nodes have no ownership
   relationship at all (a UI HUD reacting to a pickup that happens three scenes away), route
   through a small autoload singleton that only rebroadcasts named signals. Do not use the
   EventBus for things a direct call or a local signal already covers — an EventBus with
   dozens of ad hoc event names is as hard to trace as no architecture at all. A useful budget:
   if a single autoload is carrying more than roughly fifteen distinct signal names, that is a
   sign it is really two or three subsystems' buses merged into one, and splitting into
   `CombatEvents`, `WorldEvents`, and so on restores traceability.

The general shape: **signals travel up and sideways, direct calls travel down.** A node
should never need to know who is listening to its signals, and a parent should never need a
signal to talk to a child it directly owns.

## Autoload discipline

Autoloads (`project.godot` singletons) are global state and global coupling; every one added
makes the project harder to reason about and harder to test headlessly, because tests now
carry hidden global dependencies. Before adding an autoload, check whether the same problem
is solvable with a `Resource` passed down through `@export`, or a signal connected at scene
setup instead. Reasonable autoload candidates: a small number of genuinely singleton concerns
— a save/load manager, an audio bus router, a scene/level loader, an event bus per the rule
above. Unreasonable candidates: anything that only one scene actually needs, or state that
would be cleaner as an exported resource on the node that owns it.

Keep autoload scripts thin. An autoload that has grown its own several-hundred-line
subsystem is a subsystem that deserves its own non-global home (a node instantiated once at
the game root, referenced by the systems that need it), not a permanent global.

## Subsystem boundaries in a large project

For a project the size of a full 3D game with terrain, physics, inventory, dialogue, save
state and more, decide subsystem boundaries by data ownership, then keep every
cross-subsystem read or write going through a signal, an exported reference, or an explicit
autoload call — never a reach-in (`get_node("/root/Game/Player/Inventory")` from unrelated
code, or a raw `global_position` mutation from outside the node that owns movement). A useful
test: can this subsystem's headless probe run without spinning up the whole game? If a
"terrain" test needs the player, inventory and dialogue subsystems all loaded and ticking to
pass, the terrain subsystem has an undeclared dependency worth naming and narrowing.

For heightfield and mesh/mask generation specifically, that boundary already lives in
[studio-terrain](../../studio-terrain/SKILL.md) as an asset-pipeline step outside the running
game; do not fold in-engine terrain-streaming or LOD logic into the same file as the
authoring pipeline, and do not duplicate the terrain skill's dimension/mask contract here —
this file covers in-engine scene/script organization, not heightfield authoring.

## Composition-over-inheritance in one table

| Situation | Prefer | Avoid |
|---|---|---|
| Sharing behavior across unrelated node types | A reusable child scene/component node, or a shared `Resource` script | A deep custom base-class hierarchy every gameplay object inherits from |
| Per-instance tuning (speed, health, range) | `@export` fields or a data `Resource` | Hardcoded constants duplicated per subclass |
| Cross-node communication with no ownership link | Signal + autoload EventBus | Direct `get_node()` reach-through paths |
| A scene that has grown multiple unrelated concerns | Split into owned child scenes, each with one job | One script handling input, physics, UI and audio together |
| A state-heavy object (more than a few states) | An explicit state machine (own script/nodes) | A wall of `if`/`elif` on a state enum inline in `_process` |

None of this changes what counts as evidence for a change: a reorganized scene or split
script still needs the same smoke/run verification and native review described in
[studio-godot](../SKILL.md) and [execution-evidence.md](../../../references/execution-evidence.md)
before it is considered proven, not just tidier.

## Sources

Written for this kit after the 2026-09-11 audit of two community skill sets; the guidance is
restated in the kit's own words and no text or GDScript is copied from either:

- GodotPrompter, https://github.com/jame581/GodotPrompter (Superpowers-style skills; the
  `physics-system` and `scene-organization` skills were the research inputs).
- gd-agentic-skills, https://github.com/thedivergentai/gd-agentic-skills, LGPL-3.0 (the
  `godot-physics-3d`, `godot-3d-world-building`, `godot-genre-open-world`,
  `godot-performance-optimization` and `godot-debugging-profiling` skills were the research
  inputs). Under its licence, only the ideas are reused here, never its files.
