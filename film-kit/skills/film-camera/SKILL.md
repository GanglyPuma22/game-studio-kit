---
name: film-camera
description: Plan, fly and cut the camera for an animated or AI-generated film from a 3D layout. Fly every moving camera with a simulated real rig (film drone, FPV chase drone, crane or dolly, handheld) instead of drawing curves, then edit with fewer, better cuts. Works with any engine or Blender.
---

# Film camera

A drawn camera curve looks wrong when no real camera could fly it in the time given, and anything downstream (a render, a video model given a layout clip) copies that camera as is. So every moving camera is **flown by a simulated real rig**: the drawn move becomes the pilot's target and the rig reaches it within real limits. Then the edit uses the moving camera instead of extra cuts. Measured on one 80 s film (Nov 2026): the owner called the re-flown layout "a noticeable step up in camera and shot quality", and the cut count fell from about 37 to about 28.

Inputs: a 3D layout of the scene (any engine or Blender) with the story's timing, the drawn camera per shot (or waypoints for new moves), and the shot list.

## Steps

1. **Pick a rig per moving shot** ([rigs](references/rigs.md)): film drone for reveals, flyovers and swoops; FPV chase for riding beside fast fliers; crane or dolly for push-ins, arcs and rises; handheld for close coverage inside the action. Leave locked shots alone.
2. **Check the time before drawing the move.** Sample the path and run `scripts/camera_rig.py plan`. If the least flying time is longer than the story gives, hold the story there or shorten the move. Never speed it up.
3. **Anchor long moves on story beats.** Split the path into legs pinned to beats, and plan each leg into its own slot with matching speeds at the joins. Start a move on the exact frame the film is already on.
4. **Fly it.** Export each shot's drawn camera per frame (`t,px,py,pz,lx,ly,lz`), run `camera_rig.py fly --rig <rig>`, and bring the flown camera back. `scripts/blender_key_camera.py` keys a Blender camera from the result; any engine can read the CSV. Or port the `Rig` class into the engine and call `chase_drawn()` per frame. Keep a switch so the drawn version still renders for a side-by-side.
5. **Guard close cameras.** Each frame, cast a ray from the look point back to the lens against the set only, not the characters. If it hits, bring the lens in front of the hit at once and ease back out (`guard_lens()`). Keep cameras clear of large moving bodies by a margin at film scale.
6. **Cut less** ([editing](references/editing.md)). Audit the shot table, merge runs of cuts under 1.5 s apart into single flown moves, then re-time everything after a merge or a hold.
7. **Review** the whole re-flown layout with its cut list before anything costly. Scrub every flown move for the subject leaving its framing, foreground crossing it, roll, and close passes.

## Defaults that held up

- Leash the flown camera to the drawn one: the lens stays within 2.5 m (drone), 1.2 (FPV), 0.5 (crane) or 0.35 (handheld) of the drawn lens, and the aim lags the drawn aim by at most 6 deg. This keeps a lagging rig on the action.
- Keep FPV roll light, about 0.15 of the craft's lean. Strong roll reads badly on screen.
- Use one prime lens per move, with no zoom during a flown move. A tighter prime made a far subject read larger.
- Log every frame of a hero move (position, speed, tilt, gimbal angles) to a CSV, so "within the drone's limits" can be checked.
- If a rig loses the subject, fall back to the drawn camera for that shot.

## Check the tools

`python3 scripts/camera_rig.py selftest` must print PASS before you trust a flown camera. It checks each rig's limits, the FPV roll, repeatable handheld drift, the planner (an 82 m path with a 33 m drop needs about 8.2 s, not the 4.2 s once drawn for it), the leash, the restart on a cut and the guard.

Return: the flown layout render with its cut list, a drawn-vs-flown side-by-side for any shot in question, the shot table (shot, rig, change), and the moves that did not fit their story time with the choice made for each.
