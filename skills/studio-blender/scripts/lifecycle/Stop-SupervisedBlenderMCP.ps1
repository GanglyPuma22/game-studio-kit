param(
    [Parameter(Mandatory=$true)][string]$OwnershipReceipt,
    [Parameter(Mandatory=$true)][string]$WorkingRoot,
    [Parameter(Mandatory=$true)][string]$OwnerIdentity,
    [int]$CloseTimeoutSeconds = 20
)

$ErrorActionPreference = 'Stop'
$ownerName = $OwnerIdentity
$lifecycleMutex = [System.Threading.Mutex]::new($false, 'Global\GameStudioKit-BlenderMCP-127_0_0_1-9876')
$mutexAcquired = $false
try {
    $mutexAcquired = $lifecycleMutex.WaitOne([TimeSpan]::FromSeconds(10))
    if (!$mutexAcquired) { throw 'Another agent is currently changing the supervised Blender MCP lifecycle' }

$receiptPath = [IO.Path]::GetFullPath($OwnershipReceipt)
if (!(Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw "Missing ownership receipt: $receiptPath" }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.owner -ne $ownerName) { throw 'Refusing to stop a Blender process owned by another lifecycle' }

$process = Get-Process -Id $receipt.pid -ErrorAction SilentlyContinue
if ($process) {
    if ([IO.Path]::GetFullPath($process.Path) -ne [IO.Path]::GetFullPath($receipt.executable)) { throw 'Refusing cleanup: executable identity mismatch' }
    $expectedStartUtc = ([DateTimeOffset]$receipt.process_start_utc).UtcDateTime
    $startDelta = ($process.StartTime.ToUniversalTime() - $expectedStartUtc).Duration()
    if ($startDelta -gt [TimeSpan]::FromMilliseconds(10)) { throw "Refusing cleanup: process start-time mismatch ($($startDelta.TotalMilliseconds) ms)" }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 9876 -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1 -or $listeners[0].OwningProcess -ne $receipt.pid -or $listeners[0].LocalAddress -ne '127.0.0.1') {
        throw 'Refusing cleanup: loopback listener ownership is ambiguous'
    }
    [void]$process.CloseMainWindow()
    if (!$process.WaitForExit($CloseTimeoutSeconds * 1000)) {
        $receipt.status = 'NEEDS_USER_CLOSE'
        $receipt | Add-Member -NotePropertyName cleanup_note -NotePropertyValue 'Blender did not close after CloseMainWindow; save or dismiss the visible prompt manually. No force-kill was attempted.' -Force
        $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
        throw $receipt.cleanup_note
    }
}

$remainingListener = @(Get-NetTCPConnection -State Listen -LocalPort 9876 -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq $receipt.pid)
if ($remainingListener.Count) { throw 'Owned Blender exited but its listener remains unexpectedly' }
$receipt.status = 'CLOSED'
$receipt | Add-Member -NotePropertyName closed_utc -NotePropertyValue ([DateTimeOffset]::UtcNow.ToString('o')) -Force
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8

$activePath = Join-Path $WorkingRoot 'active-receipt.json'
if (Test-Path -LiteralPath $activePath) {
    $active = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
    if ([IO.Path]::GetFullPath($active.receipt_path) -eq $receiptPath) { Remove-Item -LiteralPath $activePath }
}
@{status='CLOSED'; ownership_receipt=$receiptPath; working_scene=$receipt.working_scene} | ConvertTo-Json
} finally {
    if ($mutexAcquired) { $lifecycleMutex.ReleaseMutex() }
    $lifecycleMutex.Dispose()
}
