# Native Windows lifecycle qualification

Use this card to qualify one exact Game Studio Kit revision with an existing compatible Blender MCP installation. The card does not authorize desktop control, installation, registration, cache replacement, or changes to a production game. Obtain a separate authorization window for the native stage and coordinate with the current desktop owner.

Keep KIT immutable. Put the host JSON, known saved `.blend` input, run state and evidence in declared external directories. Do not use an unrelated open Blender instance, close one to clear a conflict, or adopt its listener.

## Record the target

Record the KIT revision and hashes before starting:

```powershell
$Kit = "C:\Tools\game-studio-kit"
$HostConfig = "C:\Studio Host\host.json"
$Source = "C:\Qualification Inputs\small-known.blend"
$Evidence = "C:\Qualification Evidence\blender-mcp"
$Session = "blender-mcp-qualification-unique"
$env:PYTHONDONTWRITEBYTECODE = "1"
if (Test-Path (Join-Path $Kit ".git")) { git -C $Kit rev-parse HEAD }
Get-FileHash -Algorithm SHA256 -LiteralPath "$Kit\studio-kit.json"
Get-ChildItem -File -LiteralPath "$Kit\skills\studio-blender\scripts\lifecycle" | Get-FileHash -Algorithm SHA256
Get-FileHash -Algorithm SHA256 -LiteralPath $Source
python "$Kit\scripts\studio.py" check-package --root $Kit
python "$Kit\scripts\studio.py" doctor --config $HostConfig
& "$Kit\skills\studio-blender\scripts\lifecycle\Test-LifecycleContracts.ps1"
```

Record portable tests, package validation and the PowerShell static contracts separately. Static contracts do not qualify native lifecycle behavior. Confirm the host configuration points to the intended existing Blender executable, probe Python, MCP server command, loopback port `9876`, telemetry-off environment and an empty external working root.

## Native stage

Proceed only in the separately authorized desktop window after confirming no Blender process or port-9876 listener belongs to another task or user. Load the single host JSON and packaged scripts:

```powershell
$HostData = Get-Content -LiteralPath $HostConfig -Raw | ConvertFrom-Json
$Mcp = $HostData.blender_mcp
$Lifecycle = Join-Path $Kit "skills\studio-blender\scripts\lifecycle"
$EnsureArgs = @{
  SourceScene = $Source
  SessionId = $Session
  WorkingRoot = $Mcp.working_root
  BlenderExe = $Mcp.blender_executable
  ProbePython = $Mcp.probe_python
  McpServerConfig = $HostConfig
  OwnerIdentity = $Mcp.owner
}
$Current = & (Join-Path $Lifecycle "Ensure-SupervisedBlenderMCP.ps1") @EnsureArgs | ConvertFrom-Json
```

Qualify these behaviors and retain receipts:

1. Confirm cold Ensure returns `PASS`, `reused=false`, an external `working_scene`, and coherent owner, PID, process-start, executable, source hash, listener and protocol-probe evidence.
2. Run the same Ensure command again. Require `reused=true` with the same PID and working scene.
3. Change only `SessionId` to another safe ID and require refusal without changing or closing the owned Blender process.
4. Through the actual app client used for later work, call `get_addon_status`, `get_scene_info`, a read-only PID/file/owner identity check, and viewport capture. Require native protocol 5, matching expected protocol, telemetry false and the exact working scene. The fresh helper subprocess result from Ensure is separate evidence and cannot satisfy this step.
5. Through that app client, make one reversible named edit in the working copy, save it, inspect it and confirm the original input hash is unchanged. Never replay the mutation after an error. Run Ensure again and require the same PID/scene plus preservation of the named edit; assign that returned receipt to `$Current`.
6. If testing a controlled owned-Blender restart while retaining the same app MCP client, first stop the saved owned Blender using `$Current`, then run Ensure again and assign its new receipt to `$Current`. Preserve the app client's first and second addon-status results. Exactly one second read-only `get_addon_status` is allowed only after the new Ensure passed and the first status has `source=error` with `WinError 10053` or `Connection to Blender lost`. Require the second status and new scene/identity checks to pass. Any transport exception, different error or second failure stops the test.
7. Exercise stale-receipt and process-start mismatch refusal with copied synthetic receipts. For example, copy the current ownership JSON into `$Evidence`, change only its `process_start_utc`, then invoke `Test-SupervisedBlenderMCP.ps1` with the same working root, probe Python, host config and owner; require refusal before a protocol probe. Use another existing saved `.blend` in a separate copied receipt for a full read-only wrong-scene probe. Label synthetic results accurately and do not manipulate unrelated processes to claim PID-reuse coverage.
8. Stop only through the latest returned receipt:

```powershell
& (Join-Path $Lifecycle "Stop-SupervisedBlenderMCP.ps1") -OwnershipReceipt $Current.ownership_receipt -WorkingRoot $Mcp.working_root -OwnerIdentity $Mcp.owner
```

Require the owned Blender/listener to close while the app-owned MCP subprocess and unrelated applications remain untouched. If graceful close reports `NEEDS_USER_CLOSE`, retain the receipt and ask the desktop owner to handle the visible prompt. Do not force-kill.

## Evidence and decision

Return the exact KIT revision when available, package manifest and lifecycle file hashes, redacted configured paths, source and working-copy hashes, separate portable/static/helper-subprocess/app-client results, start/reuse/conflict/negative-test receipts, edit-save inspection, retry evidence when exercised, and cleanup state. Mark unexecuted native cases as pending. Qualification does not install or adopt the KIT; any plugin upgrade or registration is a separate explicit action.
