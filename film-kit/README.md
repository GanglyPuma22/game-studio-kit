# Film kit

Three portable skills for making short animated or AI-generated films (cinematic shorts, trailers, social clips) from a 3D layout in any engine or Blender. Any agent can use them. They have no dependency on a game engine, on this repository's helpers, or on a paid account.

| Skill | Use it to |
|---|---|
| [film-director](skills/film-director/SKILL.md) | Run the whole film: purpose and story, pipeline gates, spend, working with the person, lessons |
| [film-camera](skills/film-camera/SKILL.md) | Fly every moving camera with a simulated real rig, guard close cameras, cut less |
| [film-shots](skills/film-shots/SKILL.md) | Generate video shot by shot: frames, sheets, guide clips, specs, checks, vetting, edit |

Start with film-director. Copy the whole `film-kit` folder, because the skills link to each other. To register the skills with an agent, point it at `film-kit/skills/` or copy the three folders into its skills directory together.

Tools: `skills/film-camera/scripts/camera_rig.py` (Python 3.9+, standard library only) flies, plans and guards cameras, with a built-in `selftest`. `blender_key_camera.py` keys a Blender camera from its output.

In the Game Studio Kit, [studio-cinematic](../skills/studio-cinematic/SKILL.md) is the adapter. It adds the Godot blockout side (a GDScript port of the rig) and game-trailer specifics, and points here for the method.

MIT, like the rest of the repository. Measured on one film in Nov 2026, so re-test the model-specific numbers before relying on them.
