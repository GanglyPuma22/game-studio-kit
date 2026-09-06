# Package, project and host boundaries

Resolve `KIT` from the physical location of the skill being read: two directory levels above its skill folder, where `studio-kit.json` lives. Resolve sibling skills and references against this location. Do not search the game's current directory for `studio_tools`.

Call `python "<KIT>/scripts/studio.py" <command> --project "<GAME>" ...`. Use `python -m studio_tools` only when the repository is on Python's module path or installed in that interpreter. An editable pip install is optional; a helper wheel alone is not a complete skill/plugin distribution. Distribute the full repository archive for skill use.

Generated work belongs in GAME or another declared output root outside KIT. `source/` holds editable originals and `.gdignore` keeps them out of Godot's import scan; `assets/` holds runtime inputs; `artifacts/` holds logs/captures/candidates. Toolkit caches and vendored files are read-only during production. Portable record paths use forward slashes and cannot traverse outside GAME. External sources are deliberately copied into project-owned source storage after rights review.

For a distinct local plugin version, use a separate [staging copy and receipt](../docs/plugin-staging.md). Keep plugin and studio-kit versions equal. Record actual installed package hashes; staging changes workflow identity even when source revision is unchanged.

Host configuration is an explicitly passed JSON file (`--config`) or `STUDIO_CONFIG`; command overrides in the Python API take precedence, followed by that config and executable discovery. There is no home-folder search. Keep host files ignored and never put keys in them. Default credential variables are `MESHY_API_KEY` and `ELEVENLABS_API_KEY`; config can rename variables, not carry their secret values.

Native Windows uses Windows Python and native executable paths. WSL is a distinct host. If consciously using WSL to launch Windows apps, provide `path_mappings` from exact Linux prefixes to their verified Windows/UNC equivalent. Longest prefix wins. Do not guess drive mappings. Native GUI access, audio routing and GPU rendering still need independent verification.

Only the PID/process group created by a helper is stopped on its timeout. No close-by-process-name, addon enable, global install or desktop cleanup is performed. The foreground operator saves a checkpoint before switching between structured commands and computer use, and owns only the app instance launched for this task.
