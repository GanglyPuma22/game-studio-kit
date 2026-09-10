<#
.SYNOPSIS
  Prepare a Windows host for an unattended agent window: pause Windows Update,
  set active hours, select the High performance scheme, write a JSON receipt.

.DESCRIPTION
  Motivated by an overnight run that lost more than four hours to a planned
  Windows Update restart inside the window. This script changes only:
    1. Windows Update pause values under HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings
       (the same values the Settings app writes), for -PauseDays.
    2. Active hours (-ActiveStart/-ActiveEnd, local hours, maximum 18-hour span).
    3. The active power scheme (High performance; -Restore returns to Balanced).
  It refuses to continue when a reboot is already pending. It never stops a
  process. -WhatIf prints intended changes without writing; the receipt is
  still written, through .NET calls that ShouldProcess does not suppress, so
  the -WhatIf run itself is evidence. The receipt is UTF-8 without a byte-order
  mark under both PowerShell 7 and Windows PowerShell 5.1, because the caller
  reads it as strict UTF-8. Registry writes require an elevated PowerShell. The
  receipt object is also printed as JSON on stdout.

.NOTES
  Run once by hand with -WhatIf before any agent is allowed to call it through
  `studio host apply`. Read-only readiness checks live in `studio host preflight`.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [Parameter(Mandatory=$true)][string]$ReceiptPath,
  [ValidateRange(1, 35)][int]$PauseDays = 3,
  [ValidateRange(0, 23)][int]$ActiveStart = 18,
  [ValidateRange(0, 23)][int]$ActiveEnd = 12,
  [switch]$Restore
)

$ErrorActionPreference = 'Stop'
$ux = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
$balanced = '381b4222-f694-41f0-9685-ff5bb260df2e'
$highPerf = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
$pauseNames = @('PauseUpdatesStartTime','PauseUpdatesExpiryTime','PauseFeatureUpdatesStartTime','PauseFeatureUpdatesEndTime','PauseQualityUpdatesStartTime','PauseQualityUpdatesEndTime')

function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PendingReboot {
  [ordered]@{
    cbs = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
    wu = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
    pending_file_rename = [bool](Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue)
  }
}

function Get-HostState {
  $p = Get-ItemProperty $ux -ErrorAction SilentlyContinue
  [ordered]@{
    at_utc = (Get-Date).ToUniversalTime().ToString('o')
    pause_start = $p.PauseUpdatesStartTime
    pause_expiry = $p.PauseUpdatesExpiryTime
    pause_feature_end = $p.PauseFeatureUpdatesEndTime
    pause_quality_end = $p.PauseQualityUpdatesEndTime
    active_hours_start = $p.ActiveHoursStart
    active_hours_end = $p.ActiveHoursEnd
    power_scheme = [string](powercfg /getactivescheme)
    pending_reboot = Get-PendingReboot
    battery = (Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object BatteryStatus, EstimatedChargeRemaining)
    is_admin = Test-Admin
  }
}

if ($ActiveStart -eq $ActiveEnd) { throw 'ActiveStart and ActiveEnd must differ.' }
$span = ($ActiveEnd - $ActiveStart + 24) % 24
if ($span -gt 18) { throw "Active hours span $span h exceeds the 18 h Windows maximum." }
if (-not $WhatIfPreference -and -not (Test-Admin)) { throw 'Run from an elevated PowerShell; registry writes under HKLM require it.' }

$before = Get-HostState
$refused = $null

if ($Restore) {
  if ($PSCmdlet.ShouldProcess('Windows Update pause and power scheme', 'restore defaults')) {
    foreach ($n in $pauseNames) { Remove-ItemProperty -Path $ux -Name $n -ErrorAction SilentlyContinue }
    powercfg /setactive $balanced | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'powercfg rejected the scheme change' }
  }
} else {
  $pending = Get-PendingReboot
  if ($pending.cbs -or $pending.wu -or $pending.pending_file_rename) {
    $refused = 'A reboot is already pending; restart before the window, then re-run.'
  } else {
    $start = (Get-Date).ToUniversalTime()
    $end = $start.AddDays($PauseDays)
    if ($PSCmdlet.ShouldProcess('Windows Update', "pause until $($end.ToString('o')) and set active hours $ActiveStart-$ActiveEnd")) {
      New-Item -Path $ux -Force | Out-Null
      Set-ItemProperty -Path $ux -Name PauseUpdatesStartTime -Value $start.ToString('yyyy-MM-ddTHH:mm:ssZ')
      Set-ItemProperty -Path $ux -Name PauseUpdatesExpiryTime -Value $end.ToString('yyyy-MM-ddTHH:mm:ssZ')
      Set-ItemProperty -Path $ux -Name PauseFeatureUpdatesStartTime -Value $start.ToString('yyyy-MM-ddTHH:mm:ssZ')
      Set-ItemProperty -Path $ux -Name PauseFeatureUpdatesEndTime -Value $end.ToString('yyyy-MM-ddTHH:mm:ssZ')
      Set-ItemProperty -Path $ux -Name PauseQualityUpdatesStartTime -Value $start.ToString('yyyy-MM-ddTHH:mm:ssZ')
      Set-ItemProperty -Path $ux -Name PauseQualityUpdatesEndTime -Value $end.ToString('yyyy-MM-ddTHH:mm:ssZ')
      Set-ItemProperty -Path $ux -Name ActiveHoursStart -Value $ActiveStart -Type DWord
      Set-ItemProperty -Path $ux -Name ActiveHoursEnd -Value $ActiveEnd -Type DWord
    }
    if ($PSCmdlet.ShouldProcess('Power scheme', 'set High performance')) {
      powercfg /setactive $highPerf | Out-Null
      if ($LASTEXITCODE -ne 0) { throw 'powercfg rejected the scheme change' }
    }
  }
}

$after = Get-HostState
$receipt = [ordered]@{
  schema_version = 1
  kind = 'overnight-host-preparation'
  what_if = [bool]$WhatIfPreference
  restore = [bool]$Restore
  refused = $refused
  requested = [ordered]@{ pause_days = $PauseDays; active_start = $ActiveStart; active_end = $ActiveEnd }
  before = $before
  after = $after
}
# The receipt is evidence of the run itself, a -WhatIf run included, so it is
# written through .NET rather than the file-writing cmdlets: those honour
# ShouldProcess and under -WhatIf would write nothing, leaving `studio host
# apply --what-if` reporting a receipt path that does not exist. WriteAllText
# with a BOM-less UTF8Encoding also keeps Windows PowerShell 5.1 from prefixing
# the JSON with a byte-order mark, which the caller reads as strict UTF-8 only
# after the host has already been changed.
if (-not [System.IO.Path]::IsPathRooted($ReceiptPath)) {
  $ReceiptPath = Join-Path (Get-Location).ProviderPath $ReceiptPath
}
$receiptDir = [System.IO.Path]::GetDirectoryName($ReceiptPath)
if ($receiptDir) { [System.IO.Directory]::CreateDirectory($receiptDir) | Out-Null }
$json = $receipt | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($ReceiptPath, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output $json
if ($refused) { exit 2 }
