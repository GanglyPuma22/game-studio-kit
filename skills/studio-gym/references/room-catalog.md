# Gym room catalogue

Read alongside [studio-gym](../SKILL.md). These are starting rooms grouped by family. Cut the ones the game has no verb for and add rooms for verbs this list does not know. Every value written as `<limit>` below comes from the game's inventory, read from source; the brackets are the geometry to build around it.

Studios publish few of their gym layouts; the rooms below follow the metrics-zoo practice in [sources](sources.md) and the limits engines expose by default, so treat them as recommended practice to adapt, not a standard.

Each entry gives the questions, the geometry, the metrics the HUD or harness reads, and the usual first gap it exposes.

## Hub

- **Questions.** Can every room be reached in one action? Does reset return to the same state every time?
- **Geometry.** A flat slab with the room list, the key registry and the 1.8 m scale marker. The parked vehicle, if the game has one, sits next to it.
- **Metrics.** Build identity (content digest or commit), active flags, frame time.
- **First gap.** Teleport that skips the game's own spawn logic leaves state behind (velocity, water state, vehicle authority). Reset must clear what a normal respawn clears.

## Movement

### Speed lanes
- **Questions.** Top walk, run and sprint speed; time to top speed; stopping distance; turn radius at speed.
- **Geometry.** Three straight lanes 100 m long with a marker every 5 m, a stop line, and a 180° turn circle at the end.
- **Metrics.** Horizontal speed, time from input to 90% of top speed, distance from release to stop.
- **Expected.** The inventory's speeds; when the controller has no acceleration curve, time to top speed is one tick, which is itself a design finding.

### Slope ladder
- **Questions.** Where does walkable stop? What happens just past it: slide, block, or fall?
- **Geometry.** Ramps at 10°, 20°, 30°, `<limit>`−5°, `<limit>`−1°, `<limit>`+1°, `<limit>`+5° and 60°, each long enough to reach full speed on it, labelled with its angle. Add one descending ramp set for snap and launch-off-crest behaviour.
- **Metrics.** Slope under the feet, grounded and the reason when not, speed on the slope.
- **Expected.** "`<limit>`−1° climbs; at `<limit>`+1° the controller does what its code says." Read that outcome (slide, block or fall) from the controller or the design; in Godot, `floor_max_angle` only decides whether a surface counts as floor or wall.

### Step ladder
- **Questions.** The highest step the player walks up without jumping; what snaps down; what blocks.
- **Geometry.** Steps at 0.1, 0.2, 0.3, 0.5, 0.75, 1.0 and 1.5 m, each as a single step and as a staircase run, plus the same heights going down.
- **Metrics.** Step height met, whether the player climbed, snapped, blocked or fell, vertical speed.
- **First gap.** Many controllers have floor snap for going down and no step-up for going up.

### Jump yard
- **Questions.** Standing and running jump distance and apex; what ledge height is reachable; how much air control there is.
- **Geometry.** Gaps from 1 m to the expected maximum plus 1 m in 0.5 m steps, ledges from 0.5 m to the apex plus 0.5 m, a landing grid marked every 0.25 m.
- **Metrics.** Apex height, horizontal distance, airtime, landing impact speed.
- **Expected.** Apex from jump speed and gravity (h = v²/2g); distance from apex time and run speed.
- **Bands.** Mark each gap and ledge as clear, borderline or impossible. A level built at exactly the maximum reads as a design error to players, so the yard shows where comfortable ends, not just where possible ends.

### Ceilings and tight spaces
- **Questions.** Crouch and stand clearances, head bump on jump, squeeze through gaps.
- **Geometry.** Ceilings and doorways from player height −0.2 m to +0.4 m.
- **Metrics.** Capsule clearance, whether the action was refused and why.

### Fall heights
- **Questions.** At what height does landing become hard, damaging or fatal?
- **Geometry.** Drops from 1 m to 30 m, labelled.
- **Metrics.** Impact speed, which landing state fired, sound and camera response.

## Physics

- **Collision matrix room.** One object per layer, each placed so the player, vehicle, projectiles and creatures meet it. Expected: the layer table in the project, row by row.
- **High-speed tunnelling lane.** Thin walls at 0.1, 0.25 and 0.5 m thick hit at the game's top speeds. Expected: nothing passes through. A miss here needs continuous collision or thicker colliders.
- **Friction and moving platforms.** Low-friction, normal and high-friction patches; a platform that moves, rotates and carries the player. Expected: the player keeps relative position on the platform.
- **Stacks and pushables**, when the game has rigid bodies. Expected: stable stacks settle, pushed objects stop.
- **Far-from-origin room**, for large worlds. The same ladder rebuilt thousands of kilometres from the origin, to catch precision jitter that never appears near spawn.

## Water

- **Depth ramp.** A pool whose floor slopes from dry to well over head height, marked every 0.25 m.
- **Questions.** Where wading starts and how it slows the player; where swimming starts; buoyancy; what the camera does at the surface line; exit onto a bank.
- **Metrics.** Water depth at the feet, speed multiplier, swim state, breath or stamina if any.
- **First gap.** Wading tuned, swimming absent: deep water often does nothing at all.

## Surfaces and audio (sound zoo)

- **Surface strip.** Adjacent patches of every surface tag the game has or should have: grass, mud, rock, sand, metal, wood, shallow water, snow. Walk, run and land on each.
- **Questions.** Does the tag reach the controller? Does each tag pick its own footstep, landing and jump sound? Does the switch happen on the first step on a new patch?
- **Metrics.** Surface tag under the feet, cue played, step interval in metres.
- **Propagation and occlusion room.** A sound source behind a wall, through a doorway and in the open at marked distances. Expected: the attenuation and occlusion curve the mix intends.
- **Reverb zones.** Open, cave, interior and vehicle cabin zones in a row, crossed at walking speed. Expected: one clean transition per boundary.
- **Repeatable emitter.** A source that plays a fixed test signal (clicks, noise, a voice line) while moving on a saved path, so two builds are compared on the same sound.
- **Packaged build.** Walk the strip once in an exported build too: surface tags that resolve in the editor can fail to register after export.
- **First gap.** One surface type for everything, so the zoo shows tags on the HUD while every sound stays the same until the game adds a tag-to-cue table.

## Camera

- **Tight corridor and wall-hug.** Camera against walls, ceilings and terrain on descent. Expected: no clipping into geometry, no snap.
- **Speed run.** The camera at top movement and vehicle speeds. Expected: lag and field of view stay within the comfort numbers.
- **Look-at targets.** Markers at known angles and distances for aim, zoom and lock-on.

## Interaction

- **Target room.** Press, hold and repeat targets; two targets competing at equal distance; a target at the edge of range and one just beyond it; a target behind the player.
- **Questions.** Which one wins and why; repeated input during a response; walking away mid-hold; cooldown and reset ([studio-game-design](../../studio-game-design/SKILL.md) lists these cases).
- **Metrics.** Candidate list with priority, chosen target, hold progress, refusal reason.

## Creatures and AI

- **Creature pen.** Each creature placed at a chosen point with the player at marked distances from its notice, flee and attack ranges.
- **Questions.** Which stimulus moves it between states, and does it recover after the player leaves?
- **First gap.** No call to spawn a creature at a position, so the pen needs a small hook behind a flag.

## Vehicles and flight

- **Boarding pad.** Enter and exit from every side and at speed; exit onto a slope or into water.
- **Landing pads.** Pads at 0°, 10°, 20°, the landing slope limit −1° and +1°, and 30°, plus pads on props and on terrain. Expected: the landing rules in the inventory, including which surfaces count as landable.
- **Speed corridor and altitude bands.** Marked distances and altitude rings for top speed, acceleration, climb rate and the altitudes where the game changes behaviour.
- **Obstacle course.** Rings, gates and tree crowns at known clearances for control precision and collision.
- **Crash and recovery.** Impacts at marked speeds into terrain, props and water. Expected: the crash threshold and the recovery path.

## Streaming and performance

- **Streaming edge.** A straight run across a tile or chunk boundary at walking and vehicle speed. Metrics: frame time, hitches above the frame budget, pop-in events logged.
- **Density room.** The heaviest vegetation, creature and prop density the game will ship, so frame time can be read in one place.
- **Every room logs frame time.** A room is also a performance case.
