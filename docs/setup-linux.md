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

## Install global Codex rules for unattended runs

The kit ships the overnight-run procedure as a director reference and a
paste-ready global block, [AGENTS-overnight](../references/codex/AGENTS-overnight.md).
Codex loads `~/.codex/AGENTS.md` on every session, so the block belongs
there, and a pointer skill makes the full procedure loadable on demand. Do
these once by hand, or let an authorized setup agent do them; never
overwrite existing global instructions, merge into them instead.

```bash
Kit=/path/to/game-studio-kit
Codex="$HOME/.codex"
mkdir -p "$Codex"
PointerPath="$Codex/skills/overnight-run/SKILL.md"
Marker='<!-- game-studio-kit overnight-run pointer -->'
if [ -f "$PointerPath" ] && ! grep -qF "$Marker" "$PointerPath"; then
  echo "Refusing to overwrite $PointerPath: it exists and is not a game-studio-kit pointer. Resolve the conflict by hand, then rerun." >&2
  exit 1
fi
AgentsPath="$Codex/AGENTS.md"
BlockPath="$Kit/references/codex/AGENTS-overnight.md"
python3 - "$AgentsPath" "$BlockPath" <<'PY'
import re
import sys
from pathlib import Path

agents_path, block_path = Path(sys.argv[1]), Path(sys.argv[2])
begin = "<!-- game-studio-kit overnight-rules begin -->"
end = "<!-- game-studio-kit overnight-rules end -->"
block = block_path.read_text(encoding="utf-8")
existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
has_begin, has_end = begin in existing, end in existing
if has_begin and has_end:
    pattern = re.escape(begin) + r".*?" + re.escape(end)
    updated = re.sub(pattern, lambda m: block, existing, count=1, flags=re.S)
elif has_begin or has_end:
    sys.exit(f"{agents_path} has only one game-studio-kit overnight-rules marker; resolve the conflict by hand before rerunning.")
elif existing:
    updated = existing + "\n" + block
else:
    updated = block
agents_path.parent.mkdir(parents=True, exist_ok=True)
agents_path.write_text(updated, encoding="utf-8")
PY
mkdir -p "$Codex/skills/overnight-run"
cat > "$PointerPath" <<EOF
---
name: overnight-run
description: Use when handed an overnight, unattended or production-contract run for a game project.
---
$Marker
Read and follow $Kit/skills/studio-director/references/overnight-run.md. Its commands are run through $Kit/scripts/studio.py.
EOF
```

The pointer-collision check runs before anything is written, including any
`AGENTS.md` change: it refuses to overwrite a `SKILL.md` some other skill or
a hand-authored file already occupies, and replaces it cleanly when the
marker shows it is this kit's own prior pointer. The inline `python3` block
(standard library only) looks for both `<!-- game-studio-kit overnight-rules
begin -->` / `end` markers in `AGENTS.md`: it replaces only the text between
them when both are present, appends the whole block when neither is, and
exits with an error if it finds only one — a sign the file was hand-edited
and needs manual resolution before rerunning. Confirm in a throwaway Codex
session by asking which rules apply to an overnight run. Update the pointer
when the kit checkout moves; the block itself carries no host paths.
