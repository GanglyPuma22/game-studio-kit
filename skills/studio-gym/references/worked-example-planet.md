# Worked example: a gym on a moving planet

Read alongside [studio-gym](../SKILL.md). This is the first gym planned with this skill, for Salvage: a 3D Godot 4 game built with double precision, where the player walks a moving spherical planet, wades in water, boards a ship and flies it across the planet. It shows the four steps on a game where the easy answer (an empty flat level) does not work.

## Where the gym lives

There is no flat ground anywhere in the game. Gravity points to the planet's centre and the planet moves, so a separate empty scene would test none of the precision, gravity or streaming code the game actually runs. The gym instead places greybox rooms around the spawn on the real start planet, each room on its own flat slab that follows the planet every physics tick. The real player, ship, flight, foley and boarding code runs unchanged. The gym places, measures and teleports. It starts behind one default-off launch flag and reuses the existing flight lab's course instead of copying it.

## Step 1: the inventory

The inventory was written before any room, with every number read from source and its file and line recorded. A shortened version:

| Verb | Numbers today | Isolated today? |
|---|---|---|
| Walk, sprint | 5.0 and 8.5 m/s, full air control, no acceleration curve | On terrain only |
| Jump | 5.5 m/s up | On terrain only |
| Slopes | 45° walkable | Only where terrain happens to be steep |
| Steps | No step-up; floor snap 1.0 m | No |
| Wading | Starts at 0.06 m, speed ×0.90 down to ×0.75 at 0.45 m | Only in some launches |
| Swimming | None | n/a |
| Footsteps | Step every 1.8 m, hard landing at 4 m/s | Sounds yes, surface types no |
| Interact | Sensor 5 m, target range 3 m | Only next to real objects |
| Board and exit ship | Hatch 4.25 m, 0.8 s transition | Yes, near the parked ship |
| Assisted landing | Capture tilt ≤5°, lateral ≤0.75, descent ≤1 m/s | On terrain |
| Landing rules | Descent 4, drift 4 m/s, tilt 18.2°, slope 25.8° | Terrain only |
| Creatures react | Notice 9 m, scatter 3 m | No way to place one |

## The gaps it exposed before a room was built

1. **Plain boxes are not floors.** The game only counts the player as grounded on surfaces it has certified as standable (terrain or a registered model owner). A plain static body blocks like a wall, but the player slides on it with no jump and no footsteps. The gym registers its slabs through the game's own support route, with no change to game files.
2. **No surface materials.** Every footstep is "terrain".
3. **No swimming.** Deep water does nothing beyond wading.
4. **No step-up.** Small ledges either snap down or block.
5. **The ship lands on terrain only.** Props count as a non-terrain contact.
6. **No creature spawn call.** The creature room needs a small hook behind a flag.

Each gap names the room that shows it, and closing one is separate default-off game work.

## Steps 2 and 3: rooms, layout and keys

- **Stage 1, rooms with live metrics.** Hub and room menu, metrics HUD, slope ladder (10° to 60°, with 44° and 46° either side of the limit), step ladder (0.1 to 1.5 m), jump yard (gaps 1 to 6 m, ledges 0.5 to 2 m), wading pool (0.05 to 1.5 m deep), surface strip (tags shown on the HUD, sounds still the default), ship pad, and the flight course reused.
- **Stage 2, content and hooks.** Sound zoo, landing pads by slope, tree room (trunks on foot, crowns for the ship), interaction room, creature room.
- **Stage 3, checks.** A pass/fail check per room, one headless probe that walks every room and writes a report, input record and replay.

Three gym keys were chosen only after listing every key the game, its flight lab, an art test slice and a model lab already used. Two of those labs had picked the same letters independently, which is why the plan keeps a key registry.

## What carries over to other games

- When the world is unusual, put the gym in the world, not beside it.
- Write the inventory from code first; it found most of the gaps before any geometry existed.
- The gym's first deliverable is the list of what the game cannot do yet.
- Build in stages so the first build is useful the day it lands.
