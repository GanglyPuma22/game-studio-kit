# Harbor pocket — original functional fixture

This small original test scene verifies editable Blender source → hierarchical GLB with skin/clips → Godot import and interaction/audio. It is not a production art sample or another game's assets. All fixture source/geometry/cues were authored for this repository under MIT; no provider output or external art is used.

Copy this directory's contents to a **separate game directory** outside the toolkit before running it. Then use the absolute helper entrypoint with `godot import`, `godot smoke`, and `godot run`. See [Windows setup](../../docs/setup-windows.md) and [native smoke](../../docs/windows-smoke.md).

WASD/arrows move. Click and move the mouse to look; Escape releases the mouse. Approach the bell within 3 metres and press E: one one-second response clip and short cue play, then the two-second idle loop resumes. The ochre marker is 1.8 metres tall. Terrain is an original 16-bit procedural heightfield with a visible/collidable flanking mound.

`source/harbor-bell.blend` is editable, `assets/harbor-bell.glb` is explicit runtime data. `.gdignore` keeps source out of import. Rig: Root and Frond; four meshes, three simple materials; dimensions in Blender axes approximately 1.06 × 0.94 × 1.5 m. Source generation lives in [fixture.py](../../studio_tools/blender_scripts/fixture.py); regenerate in an empty project with `fixture`. WAV originals are separate from runtime copies.

Actual Blender 5.0.1 Windows background roundtrip and Godot 4.5.1 Linux headless smoke passed. The technical smoke injects the same action names used by ordinary play and uses Dummy audio. Native ordinary controls, audible mix, GPU performance and registered Windows plugin invocation remain **not_run**; see [compatibility](../../docs/compatibility.md). Asset stage stays exported until project-specific import evidence is attached.
