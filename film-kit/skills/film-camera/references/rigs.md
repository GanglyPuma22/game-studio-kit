# Rigs: fly every moving camera

A drawn camera curve looks wrong when no real camera could fly it in the time given, and a video model copies the camera from the layout as is. So in the layout, every moving camera is **flown by a simulated real rig**: the drawn move becomes the pilot's target, and the rig reaches it within real limits. On one trailer (Nov 2026) the person called the re-flown clay film "a noticeable step up in camera and shot quality". The simulator is [scripts/camera_rig.py](../scripts/camera_rig.py) (plain Python, any engine; `selftest` built in), with [blender_key_camera.py](../scripts/blender_key_camera.py) to key a Blender camera from its output.

This is the same idea as virtual production: The Lion King (2019) was fully virtual but shot with real crane, dolly and Steadicam rigs fitted with trackers, so the virtual camera moved like physical gear.

## The rigs

| Rig | Moves it gives | Limits | Use for |
|---|---|---|---|
| Film drone (Inspire 3, S mode) | Reveals, flyovers, high slow drifts, swoops | 26 m/s, 8 m/s climb and descent, 40 deg tilt, 150 deg/s yaw, gimbal 120 deg/s tilt and 270 deg/s pan, one prime lens. Published figures | Establishing, reveals, map drifts, the end swoop |
| FPV chase drone | Riding beside a flier through a swing, dives and banks | 33 m/s, 60 deg lean, fast tilt gimbal, camera banks lightly with the craft (approximate) | Tethered swings, dives, chases |
| Crane / dolly | Slow push-ins, arcs round a pair, rises over a shoulder | 3 m/s, 1.5 m/s vertical, about 1.2 m/s² (approximate) | Two-shots, decisions, close-ups, endings |
| Handheld / Steadicam | Close coverage on foot | Walking pace, lag, a small seeded breathing drift, never a snap (approximate) | Close shots inside the action (trapped in a fist, a run on the ground) |

Only the drone's limits are published. Tune the others by eye, and say so wherever the numbers appear.

How the simulator flies, so the motion is honest:
- **Sticks only.** The sticks ask for a velocity, the flight controller leans the craft to get it (never past its tilt limit), drag sets top speed. The craft cannot start, stop or turn faster than the real one.
- **A pilot plan** times the path within comfortable limits (about 70% of the hard ones), leg by leg: along-path acceleration, cornering, climb and descent, top speed. The autopilot chases the plan a quarter second ahead, as a pilot anticipates.
- **A gimbal operator** eases between targets within the gimbal's rate and acceleration limits. Clamp the down-tilt per shot (a reveal never tips more than about 30-36 deg down).
- **One prime lens per move.** No zoom during a flown move. A tighter prime (40 deg vertical, about 33 mm) made a far subject read larger than the blockout's default.
- **Log every frame** of a flown hero move (position, speed, tilt, sticks, gimbal angles and rates, distance off the plan) to a CSV, so a claim like "within the drone's limits" can be checked.

## Two ways to use a rig

1. **Plan and fly a new move** (the hero reveal): place a pilot's waypoints, smooth them (Catmull-Rom, then a short moving average), lift any point that dips into a roof, split the path into legs at story anchors, `plan_speeds()` each leg into its slot with matching speeds at the joins, then fly it with `fly_toward()` + `aim_at()` + `step()` at 240 Hz sub-steps.
2. **Fly an existing drawn camera** (the rest of the film): `chase_drawn()` per frame. The drawn camera is the mark, chased 0.2 s ahead, and held on two leashes so a lagging rig never drifts into a character or off the action:
   - the lens stays within a few metres of the drawn lens (worked: drone 2.5, FPV 1.2, crane 0.5, handheld 0.35);
   - the aim lags the drawn aim by at most about 6 deg.
   A drawn jump (a hard cut inside a shot) restarts the rig on its new mark. Shots that become one move share one rig instance, so the flight carries across what used to be cuts.

Keep a flag that switches the flown cameras on (`--rigs` on the first film), so the drawn version stays renderable for a side-by-side.

## Rules that came out of it

- **Budget time for the move before drawing it.** Measure the path and check `min_duration()` against the story time. The first reveal path was 82 m with a 33 m drop: a real drone needs at least 8.2 s for it and about 10 s smoothly, and the story gave it 4.2 s, so every drawing of it read as too fast. Either hold the story where the camera needs time (a 4.5 s hold while she waits on her roof), or make the move shorter. **A move that doesn't fit becomes a shorter move, never a faster one.**
- **Anchor the move on story beats.** Split it into legs pinned to beats (on him, off her roof, the cut), each planned into its own slot. Then the camera arrives on the action, not merely somewhere near it.
- **Start a flown move on the frame the film is already on.** The reveal opens on the previous camera's exact frame and drift, so there is no switch to a new camera.
- **Keep close cameras out of the set.** A camera guard (`guard_lens()`): a ray from what the camera looks at back to the lens; when a wall or roof is in the way, the lens comes in in front of it at once and eases back out over later frames, as a game camera does. Skip the characters in the ray so a body crossing the lens doesn't yank it. Also push cameras clear of large characters' bodies and hands (on 16 m characters: 6 m from the body's axis, 3.5 m from a hand; scale with size).
- **Light FPV roll.** Strong roll with the lean read badly on screen; a bank gain of about 0.15 kept the energy without the nausea.
- **Clear big bodies by a margin at film scale.** A swoop that passes a 16 m character must clear its highest point (spikes included) with room to spare; one pass "quite close over the spikes" was the only rough spot the person might have noticed.
- **Drop the rig when it loses the subject.** One flown FPV shot lost her behind the action, so it stayed drawn. Check every flown shot for the subject at its framing size, and fall back per shot.
- **Watch for set crossing the lens on long moves.** A roof edge crossed frame during the reveal; scrub every flown move for foreground that cuts across the subject.

## Before video generation

A flown camera is only worth something if the next stage gets it. A direct render (Blender, engine) takes the camera as is. A video model given only painted first and last frames invents its own move between them, so camera-heavy shots need a camera-only guide clip; see [film-shots](../../film-shots/references/inputs.md) and the [lessons log](../../film-director/references/lessons.md).
