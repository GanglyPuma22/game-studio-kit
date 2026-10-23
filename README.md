# Game Studio Kit

Fifteen self-contained skills and a small Python helper library for producing and reviewing bounded game scenes. Local Blender, procedural audio/terrain and Godot form the functional baseline. Tripo, Meshy, Gaea, ElevenLabs and Blender MCP are optional routes. [Studio Tripo](skills/studio-tripo/SKILL.md) uses a verified official client or Studio UI; there is no `studio tripo` helper command yet.

Start by reading [studio-director](skills/studio-director/SKILL.md) in your capable local agent. Keep the **whole repository** together. It has no dependency on private agent folders, other installed skills, a daemon, or a paid account. You provide Python 3.11+, application installations, project inputs and your host's actual tools.

To have an agent set this up for you, ask it to clone this repository and follow [Agent startup: clone, integrate, verify, work](docs/agent-start.md). That guide covers registered-plugin setup, project-level pointers and direct-file execution when registration is deferred.

```powershell
$Kit = "C:\Tools\game-studio-kit"
$Game = "C:\Projects\Harbor Test"
python "$Kit\scripts\studio.py" check-package --root "$Kit"
python "$Kit\scripts\studio.py" doctor --config "C:\Studio Host\host.json"
python "$Kit\scripts\studio.py" fixture --project "$Game" --config "C:\Studio Host\host.json"
python "$Kit\scripts\studio.py" godot import --project "$Game" --config "C:\Studio Host\host.json"
python "$Kit\scripts\studio.py" godot smoke --project "$Game" --config "C:\Studio Host\host.json"
```

`fixture` needs an empty output directory and Blender. To try the already generated functional example, copy the **contents** of [examples/harbor-pocket](examples/harbor-pocket/README.md) to a separate game directory, then import and run it with Godot. The example includes original editable source, an exported rigged mesh, two clips, cues and terrain. This proves a pipeline, not a production art target.

- [Windows setup and registration](docs/setup-windows.md), [Linux setup](docs/setup-linux.md)
- [Optional provider setup](docs/provider-setup.md), [commands and records](references/production-contracts.md)
- [Testing and exact native smoke](docs/testing.md), [compatibility and remaining checks](docs/compatibility.md)
- [Contribution and archive recipe](docs/contributing.md), [third-party notices](THIRD_PARTY_NOTICES.md)

Codex uses [.codex-plugin/plugin.json](.codex-plugin/plugin.json); Claude Code uses [.claude-plugin/plugin.json](.claude-plugin/plugin.json). Both load the same skills and helper. See [Claude Code setup](docs/claude-code.md) for session-only testing and marketplace installation. Registration is opt-in and host-specific; it does not manufacture computer use or install Blender. A direct read of a skill is useful but does not prove plugin discovery. Follow the installed-coordinator test from a separate project directory.

New code, instructions and original example are MIT. Adapted upstream guidance retains its own license and exact provenance. Provider service/output rights remain separate. This repository is prepared for review; see the compatibility matrix before making a target-host or release-readiness claim.
