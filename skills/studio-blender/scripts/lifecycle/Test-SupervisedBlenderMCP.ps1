param(
    [string]$OwnershipReceipt = '',
    [Parameter(Mandatory=$true)][string]$WorkingRoot,
    [Parameter(Mandatory=$true)][string]$ProbePython,
    [Parameter(Mandatory=$true)][string]$McpServerConfig,
    [Parameter(Mandatory=$true)][string]$OwnerIdentity,
    [int]$Port = 9876,
    [switch]$SkipProtocolProbe
)

$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw "Port must be between 1024 and 65535; got $Port" }
$ownerName = $OwnerIdentity
$activePath = Join-Path $WorkingRoot 'active-receipt.json'
if (!$OwnershipReceipt) {
    if (!(Test-Path -LiteralPath $activePath)) { throw 'No active supervised Blender MCP receipt' }
    $OwnershipReceipt = (Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json).receipt_path
}
if (!(Test-Path -LiteralPath $OwnershipReceipt -PathType Leaf)) { throw "Missing ownership receipt: $OwnershipReceipt" }
$receipt = Get-Content -LiteralPath $OwnershipReceipt -Raw | ConvertFrom-Json
if ($receipt.owner -ne $ownerName) { throw 'Ownership receipt belongs to another lifecycle' }
if ($receipt.status -notin @('STARTING','RUNNING')) { throw "Receipt is not active: $($receipt.status)" }
if ($null -ne $receipt.port -and [int]$receipt.port -ne $Port) { throw "Ownership receipt names port $($receipt.port), not $Port" }

$process = Get-Process -Id $receipt.pid -ErrorAction Stop
if ([IO.Path]::GetFullPath($process.Path) -ne [IO.Path]::GetFullPath($receipt.executable)) { throw 'Blender executable identity mismatch' }
$expectedStartUtc = ([DateTimeOffset]$receipt.process_start_utc).UtcDateTime
$startDelta = ($process.StartTime.ToUniversalTime() - $expectedStartUtc).Duration()
if ($startDelta -gt [TimeSpan]::FromMilliseconds(10)) { throw "Blender process start-time mismatch ($($startDelta.TotalMilliseconds) ms)" }
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop)
if ($listeners.Count -ne 1) { throw "Expected one port-$Port listener; found $($listeners.Count)" }
if ($listeners[0].OwningProcess -ne $receipt.pid -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw "Port $Port is not owned by the expected loopback Blender process" }
if (!(Test-Path -LiteralPath $receipt.working_scene -PathType Leaf)) { throw 'Working Blender scene is missing' }
# Whether the PowerShell parent that started this Blender has already exited.
# Reported, never enforced: Ensure calls this script in-process while it is
# still running, so a live parent is normal there. It is the observation the
# documented ensure-returns regression reads, because `ensure` returning while
# the owned GUI stays open is exactly a live Blender with a dead parent.
$parentPid = $null
$parentAlive = $null
try {
    $parentPid = (Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $($receipt.pid)" -ErrorAction Stop).ParentProcessId
    if ($null -ne $parentPid) {
        $parentAlive = [bool](Get-Process -Id $parentPid -ErrorAction SilentlyContinue)
    }
} catch {
    $parentPid = $null
}

$result = [ordered]@{
    status = 'PASS'
    owner = $receipt.owner
    session_id = $receipt.session_id
    pid = $receipt.pid
    ownership_receipt = [IO.Path]::GetFullPath($OwnershipReceipt)
    working_scene = $receipt.working_scene
    source_sha256 = $receipt.source_sha256
    listener = "127.0.0.1:$Port"
    port = $Port
    parent_pid = $parentPid
    parent_alive = $parentAlive
    protocol_probe = 'SKIPPED'
}

if (!$SkipProtocolProbe) {
    if (!(Test-Path -LiteralPath $ProbePython -PathType Leaf)) { throw "Missing repaired MCP Python: $ProbePython" }
    if (!(Test-Path -LiteralPath $McpServerConfig -PathType Leaf)) { throw "Missing explicit MCP server config: $McpServerConfig" }
    $evidence = Join-Path (Split-Path -Parent $OwnershipReceipt) ('health-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    & $ProbePython (Join-Path $PSScriptRoot 'probe_mcp.py') --server-config $McpServerConfig --expected-pid $receipt.pid --expected-scene $receipt.working_scene --owner $ownerName --evidence $evidence
    if ($LASTEXITCODE -ne 0) { throw "Native MCP protocol probe failed; inspect $evidence" }
    $probeResult = Get-Content -LiteralPath (Join-Path $evidence 'probe-result.json') -Raw | ConvertFrom-Json
    if ($probeResult.status -ne 'PASS') { throw "Native MCP protocol probe did not pass; inspect $evidence" }
    $result.protocol_probe = 'PASS'
    $result.evidence_directory = $evidence
}

$result | ConvertTo-Json -Depth 5
