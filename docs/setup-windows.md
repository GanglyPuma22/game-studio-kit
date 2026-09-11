# Native Windows setup

For an agent performing setup and then a game task, begin with [the agent startup guide](agent-start.md). It explains cloning, clean integration and how to continue through the coordinator.

Use native Windows Python 3.11+, Blender 5.0.x and Godot 4.5.1 standard for the initial profile. Obtain installers/portable executables from [Python](https://www.python.org/downloads/windows/), [Blender](https://www.blender.org/download/) and [Godot](https://godotengine.org/download/archive/4.5.1-stable/). No studio command installs them. Reuse existing compatible installations; do not replace another project's tools.

Keep the complete package at a location such as `C:\Tools\game-studio-kit` and an empty game destination elsewhere. Create a host-local JSON file outside the package; replace example executable paths with actual ones:

```json
{
  "executables": {
    "blender": "C:\\Program Files\\Blender Foundation\\Blender 5.0\\blender.exe",
    "godot": "C:\\Tools\\Godot\\Godot_v4.5.1-stable_win64.exe"
  },
  "blender_mcp": {
    "working_root": "C:\\Studio Host\\blender-mcp-runs",
    "blender_executable": "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe",
    "probe_python": "C:\\Studio Host\\blender-mcp-1.9.1\\Scripts\\python.exe",
    "owner": "game-studio-kit-blender-mcp-v1",
    "server": {
      "command": "C:\\Studio Host\\blender-mcp-1.9.1\\Scripts\\blender-mcp.exe",
      "args": [],
      "env": {"BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": "9876", "DISABLE_TELEMETRY": "true", "BLENDER_MCP_DISABLE_TELEMETRY": "true"}
    }
  },
  "timeout": 300,
  "credentials": {"meshy": "MESHY_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY", "fish": "FISH_AUDIO_API_KEY"}
}
```

The optional `blender_mcp` block is needed only for the [interactive lifecycle](../skills/studio-blender/references/mcp.md); omit it when using the independent background route. Its working root must stay outside KIT. The JSON should contain escaped backslashes exactly as normal Windows JSON requires. `--config` or `STUDIO_CONFIG` selects it. Keys live only in environment variables. Path discovery is an alternative, not a reason to edit global PATH automatically. `doctor` probes versions offline and `setup` prints missing actions; configured lifecycle paths do not establish version or interactive readiness.

```powershell
$Kit = "C:\Tools\game-studio-kit"
$Game = "C:\Projects\Harbor Test"
$HostConfig = "C:\Studio Host\host.json"
python "$Kit\scripts\studio.py" check-package --root "$Kit"
python "$Kit\scripts\studio.py" doctor --config "$HostConfig" --output "C:\Studio Host\doctor.json"
python "$Kit\scripts\studio.py" setup --report "C:\Studio Host\doctor.json"
python "$Kit\scripts\studio.py" fixture --project "$Game" --config "$HostConfig"
python "$Kit\scripts\studio.py" godot import --project "$Game" --config "$HostConfig"
python "$Kit\scripts\studio.py" godot smoke --project "$Game" --config "$HostConfig"
```

A direct skill start is: ask the host to read `C:\Tools\game-studio-kit\skills\studio-director\SKILL.md` with GAME declared. This needs no registration and tests the package route, but not plugin discovery.

For **registered plugin** use the host's local plugin development/install flow with the complete tree and `.codex-plugin/plugin.json`. See [official packaging](https://developers.openai.com/plugins/build/plugins) and [build/install guidance](https://learn.chatgpt.com/docs/build-plugins). Do not copy only the ten folders into a global skills directory; that breaks shared references. In Codex CLI, the verified command surface is `codex plugin marketplace add <local-marketplace-root>` then `codex plugin add game-studio-kit@<marketplace-name>`; check the installed CLI's help if it differs.

A local marketplace can be staged in a separate host-owned directory with this layout:

If a distinct cache version is needed, follow [version staging](plugin-staging.md)
to update both declarations and retain the packaging receipt before registration.

```text
StudioLocal/
  .agents/plugins/marketplace.json
  plugins/game-studio-kit/             complete copy of this repository
```

Its marketplace JSON is:

```json
{
  "name": "studio-local",
  "plugins": [{
    "name": "game-studio-kit",
    "source": {"source": "local", "path": "./plugins/game-studio-kit"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

Register that directory only when authorized; do not overwrite an existing marketplace. This repository does not alter marketplaces or user profiles. Start a **new native host conversation**, switch working directory to GAME, invoke the actually registered `studio-director`, and follow [windows-smoke](windows-smoke.md). The agent must resolve a sibling skill and shared helper from its installed package location. Listing the plugin or reading a file manually does not pass this acceptance test.

Host computer use is a separate capability with actual tool/app permissions: [official computer-use guidance](https://learn.chatgpt.com/docs/computer-use). Preserve user-open applications, save a checkpoint and own only the test window/process. Windows native plugin invocation, ordinary controls, GPU rendering and audible mix remain pending until this procedure is demonstrated on the target host.

For exports, add `godot_export_templates` to the host JSON with the installed `export_templates` root. The helper copies its version subdirectories into an isolated temporary profile; see [export setup and smoke protocol](../skills/studio-godot/references/execution.md). Installing templates into the normal editor profile alone does not configure this isolated route.

## Unattended windows: host preflight and apply

Before an overnight or otherwise unattended run, check the host without changing it:

```powershell
python "$Kit\scripts\studio.py" host preflight --window-start 2026-09-15T05:00:00Z --window-end 2026-09-15T15:00:00Z --output "C:\Studio Host\receipts\preflight.json"
```

It reports whether Windows Update is paused past the window end, whether a
reboot is pending, whether active hours cover every hour of the window (local
time, at most 18 hours), the power scheme and AC state. A window that has
already ended is refused outright — readiness is a claim about a window that
can still be run — while a window already under way is still judged. When
Windows answers that it does not know the AC line status, that is recorded as
the limit "AC line status unknown" rather than as a host on battery. A planned Windows
Update restart inside an unattended window has already cost one production run
more than four hours.

To make the host ready, run the packaged script once by hand from an elevated
PowerShell with `-WhatIf` and read the receipt, then without it:

```powershell
python "$Kit\scripts\studio.py" host apply --receipt "C:\Studio Host\receipts\apply-whatif.json" --what-if
python "$Kit\scripts\studio.py" host apply --receipt "C:\Studio Host\receipts\apply.json" --pause-days 3 --active-start 18 --active-end 12
```

`host apply --restore` clears the pause and returns to the Balanced scheme.
The script changes only Windows Update pause values, active hours and the power
scheme; it never stops a process. Agents may call `host apply` only after this
manual validation has been recorded.

`host apply` refuses an active-hours span longer than 18 hours before it
launches PowerShell, so a mistake costs no elevated process. The script itself
refuses before touching anything when a reboot is already pending or when the
High performance scheme is absent from `powercfg /list` (`refused` in the
receipt, exit 2), and `--restore` reports a pause value it could not remove
instead of silently skipping it. If a change fails once the registry writes have begun it
records `failure` with `partial: true` and exits 3, still writing the receipt
first, because the host is already part-changed by then. `host apply` reads
that receipt and returns it with `ok: false` instead of raising, so the
half-applied state is visible; it raises only when the script left no receipt
at all. Read `refused`, `failure` and `partial` before treating a host as
prepared.

Before any of that, the script proves its `-ReceiptPath` destination is
writable: it resolves the path, creates its parent directory and writes a
`status: starting` receipt, all before touching the host. If that write fails
— a bad drive letter, a directory it cannot create — it exits 4 with no host
change attempted, and `host apply` raises "receipt destination unwritable; no
host changes were made" instead of reading a receipt that was never written.

The `--what-if` run writes its receipt too: the receipt is the evidence that
the run happened, so it is written through .NET calls that `-WhatIf` does not
suppress, as UTF-8 without a byte-order mark. Give `--output` and `--receipt`
paths outside the installed kit; both refuse a destination inside it.

## Install global Codex rules for unattended runs

The kit ships the overnight-run procedure as a director reference and a
paste-ready global block, [AGENTS-overnight](../references/codex/AGENTS-overnight.md).
Codex loads `%USERPROFILE%\.codex\AGENTS.md` on every session, so the block
belongs there, and a pointer skill makes the full procedure loadable on demand.
Do these once by hand, or let an authorized setup agent do them; never overwrite
existing global instructions, append after them.

```powershell
$Kit = "C:\Tools\game-studio-kit"
$Codex = Join-Path $env:USERPROFILE ".codex"
New-Item -ItemType Directory -Force -Path $Codex | Out-Null
$PointerPath = Join-Path $Codex "skills\overnight-run\SKILL.md"
$Marker = "<!-- game-studio-kit overnight-run pointer -->"
if ((Test-Path $PointerPath) -and -not (Select-String -Path $PointerPath -Pattern ([regex]::Escape($Marker)) -Quiet)) {
    throw "Refusing to overwrite $PointerPath: it exists and is not a game-studio-kit pointer. Resolve the conflict by hand, then rerun."
}
$AgentsPath = Join-Path $Codex "AGENTS.md"
$BlockBegin = "<!-- game-studio-kit overnight-rules begin -->"
$BlockEnd = "<!-- game-studio-kit overnight-rules end -->"
$Block = Get-Content -Raw (Join-Path $Kit "references\codex\AGENTS-overnight.md")
if (Test-Path $AgentsPath) {
    $Existing = Get-Content -Raw $AgentsPath
    $HasBegin = $Existing.Contains($BlockBegin)
    $HasEnd = $Existing.Contains($BlockEnd)
    if ($HasBegin -and $HasEnd) {
        $Pattern = [regex]::Escape($BlockBegin) + ".*?" + [regex]::Escape($BlockEnd)
        $Options = [System.Text.RegularExpressions.RegexOptions]::Singleline
        $Updated = [regex]::Replace($Existing, $Pattern, { $Block }, $Options)
        Set-Content -Path $AgentsPath -Value $Updated -Encoding UTF8 -NoNewline
    } elseif ($HasBegin -or $HasEnd) {
        throw "$AgentsPath has only one game-studio-kit overnight-rules marker; resolve the conflict by hand before rerunning."
    } else {
        Add-Content -Path $AgentsPath -Value ("`n" + $Block)
    }
} else {
    Set-Content -Path $AgentsPath -Value $Block -Encoding UTF8
}
New-Item -ItemType Directory -Force -Path (Join-Path $Codex "skills\overnight-run") | Out-Null
@"
---
name: overnight-run
description: Use when handed an overnight, unattended or production-contract run for a game project.
---
$Marker
Read and follow $Kit\skills\studio-director\references\overnight-run.md. Its commands are run through $Kit\scripts\studio.py.
"@ | Set-Content -Path $PointerPath -Encoding UTF8
```

The pointer-collision check runs before anything is written, including any
`AGENTS.md` change: it refuses to overwrite a `SKILL.md` some other skill or
a hand-authored file already occupies, and replaces it cleanly when the
marker shows it is this kit's own prior pointer. `AGENTS-overnight.md` is
itself wrapped in `<!-- game-studio-kit overnight-rules begin -->` /
`end` marker lines; the snippet looks for both in `AGENTS.md`, replaces only
the text between them with a singleline regex when both are present, appends
the whole block when neither is, and throws if it finds only one — a sign
the file was hand-edited and needs manual resolution before rerunning.
Confirm in a throwaway Codex session by asking which rules apply to an
overnight run. Update the pointer when the kit checkout moves; the block
itself carries no host paths.

