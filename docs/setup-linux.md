# Linux / WSL setup

Use Python 3.11+ and explicit Blender/Godot executables. The helpers use only the standard library. From a complete source checkout, `python -m studio_tools` works; from another working directory use the absolute `scripts/studio.py` entrypoint. No Bash scripts or global Python package install are required by the package.

```json
{"executables":{"blender":"/opt/blender/blender","godot":"/opt/godot/godot"},"timeout":300}
```

```text
python /path/to/game-studio-kit/scripts/studio.py doctor --config /path/to/host.json
python /path/to/game-studio-kit/scripts/studio.py fixture --project "/path/to/Harbor Test" --config /path/to/host.json
python /path/to/game-studio-kit/scripts/studio.py godot import --project "/path/to/Harbor Test" --config /path/to/host.json
python /path/to/game-studio-kit/scripts/studio.py godot smoke --project "/path/to/Harbor Test" --config /path/to/host.json
```

Godot gets project-owned `artifacts/godot-profile` config/data/cache directories. Its editor import may need permission for its local editor socket in restrictive sandboxes. A failed permission is not an import pass; inspect the log and retry only the owned process under the host's authorized execution route. Headless runtime uses Dummy audio and does not establish audible output.

WSL and native Windows are different execution contexts. For an intentional WSL→Windows Blender route, set the executable to its mounted `.exe` path and configure explicit `path_mappings` from a Linux prefix to the Windows/UNC equivalent verified by `wslpath -w`. The helper applies those mappings only to Windows executables; a Linux Godot executable still gets Linux paths. Paths containing spaces remain one process argument.

Do not pass Linux paths directly to a Windows app, assume that a foreground desktop is available, or use another user's SSH/path settings. [Native Windows verification](windows-smoke.md) remains separate from Linux headless validation. macOS and other engine routes are extension targets, not tested claims.
