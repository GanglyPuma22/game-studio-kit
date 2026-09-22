param(
    [Parameter(Mandatory=$true)][string]$SourceScene,
    [Parameter(Mandatory=$true)][string]$SessionId,
    [Parameter(Mandatory=$true)][string]$WorkingRoot,
    [Parameter(Mandatory=$true)][string]$BlenderExe,
    [Parameter(Mandatory=$true)][string]$ProbePython,
    [Parameter(Mandatory=$true)][string]$McpServerConfig,
    [Parameter(Mandatory=$true)][string]$OwnerIdentity,
    [string]$ExpectedSourceSha256 = '',
    [int]$Port = 9876,
    [int]$StartupTimeoutSeconds = 60,
    [switch]$PlanOnly,
    [switch]$Probe
)

$ErrorActionPreference = 'Stop'
$defaultPort = 9876
$ownerName = $OwnerIdentity
$rehandshakePolicy = 'ONE_READ_ONLY_RETRY_ON_10053'

function Set-ReceiptContentAtomic {
    # Write a receipt to a sibling temporary file and Move-Item -Force it over
    # the prior record, so a mid-write interruption never leaves a truncated
    # or partially written receipt behind for a later Ensure/Stop to trip on.
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)]$Value,
        [int]$Depth = 6
    )
    $directory = Split-Path -Parent $Path
    $tempPath = Join-Path $directory ('.' + (Split-Path -Leaf $Path) + '.tmp-' + [Guid]::NewGuid().ToString('N'))
    $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $tempPath -Encoding utf8
    Move-Item -LiteralPath $tempPath -Destination $Path -Force
}

function Invoke-LifecycleHealthCheck {
    # Judge success by Test-SupervisedBlenderMCP.ps1's own outcome, not a
    # bare $LASTEXITCODE comparison. It runs as another PowerShell script
    # (the & call operator), not a native program, so $LASTEXITCODE is only
    # ever set here when it internally invokes the native protocol probe.
    # A -SkipProtocolProbe reuse check runs no native program at all, which
    # leaves $LASTEXITCODE $null (or a stale value from an unrelated
    # earlier native call) in this process; `$null -ne 0` is true, so a
    # bare comparison would treat every such reuse as a failure. Treat
    # $LASTEXITCODE as meaningful only when it is an int a native program
    # actually just set. The script already throws a terminating error on
    # every real failure, including a nonzero native probe exit code it
    # checks internally right after that native call; $? is a second,
    # defense-in-depth signal for a failure that did not throw.
    param(
        [Parameter(Mandatory=$true)][string]$Script,
        [Parameter(Mandatory=$true)][hashtable]$Arguments,
        [Parameter(Mandatory=$true)][string]$FailureMessage
    )
    $global:LASTEXITCODE = $null
    $output = & $Script @Arguments
    if (!$? -or ($global:LASTEXITCODE -is [int] -and $global:LASTEXITCODE -ne 0)) {
        throw $FailureMessage
    }
    return $output
}

function Resolve-ReparseTarget {
    # [IO.Path]::GetFullPath only normalizes a path lexically; it never
    # follows a symlink or junction. A WorkingRoot (or an ancestor of one
    # that does not exist yet) that is itself a reparse point pointing
    # inside the installed kit would otherwise pass a purely lexical
    # outside-kit comparison. Walk up to the nearest existing ancestor,
    # resolve any reparse point on it to its final real target, and
    # reattach the not-yet-created remainder.
    param([Parameter(Mandatory=$true)][string]$Path)
    $existing = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $remainder = @()
    while ($existing -and !(Test-Path -LiteralPath $existing)) {
        $remainder = @((Split-Path -Leaf $existing)) + $remainder
        $parent = Split-Path -Parent $existing
        if (!$parent -or $parent -eq $existing) { break }
        $existing = $parent
    }
    if (Test-Path -LiteralPath $existing) {
        $item = Get-Item -LiteralPath $existing -Force
        $resolved = $null
        try {
            # PowerShell 7.1+ / .NET 6+.
            $target = $item.ResolveLinkTarget($true)
            if ($target) { $resolved = $target.FullName }
        } catch {
            # PowerShell 5.1 has no ResolveLinkTarget; walk .Target by hand.
            $seen = @{}
            $current = $item
            while ($current.LinkType -and $current.Target -and $current.Target.Count -and !$seen.ContainsKey($current.FullName)) {
                $seen[$current.FullName] = $true
                $nextPath = $current.Target[0]
                if (!(Test-Path -LiteralPath $nextPath)) { break }
                $current = Get-Item -LiteralPath $nextPath -Force
            }
            if ($current.FullName -ne $item.FullName) { $resolved = $current.FullName }
        }
        $existing = [IO.Path]::GetFullPath($(if ($resolved) { $resolved } else { $item.FullName })).TrimEnd('\')
    }
    if ($remainder.Count) {
        return [IO.Path]::GetFullPath((Join-Path $existing ($remainder -join '\'))).TrimEnd('\')
    }
    return $existing
}
function Get-ExcludedPortRange {
    # Windows hands whole TCP ranges to Hyper-V/WinNAT and to its own dynamic
    # port reservations; a port inside one cannot be bound at all, and the
    # failure surfaces as a Blender that starts and then cannot listen. Read
    # the reservations first so the refusal happens before any launch.
    param([Parameter(Mandatory=$true)][int]$Candidate)
    $netsh = Get-Command -Name 'netsh.exe' -CommandType Application -ErrorAction SilentlyContinue
    if (!$netsh) { return $null }
    try {
        $text = & $netsh.Source int ipv4 show excludedportrange protocol=tcp 2>$null
    } catch {
        return $null
    }
    foreach ($line in @($text)) {
        $match = [regex]::Match([string]$line, '^\s*(\d+)\s+(\d+)\s*\*?\s*$')
        if ($match.Success) {
            $start = [int]$match.Groups[1].Value
            $end = [int]$match.Groups[2].Value
            if ($Candidate -ge $start -and $Candidate -le $end) { return "$start-$end" }
        }
    }
    return $null
}

function Assert-ParentStdioIsNotAPipe {
    # The owned Blender process inherits this PowerShell process's open
    # handles. When the parent's own stdout/stderr are *pipes* -- which is
    # what a caller capturing output through a pipe hands it -- the inherited
    # duplicates keep those pipes open for as long as Blender lives, and the
    # reader waits for an end-of-file that only arrives when the GUI is
    # closed. That is why `ensure` never returned while Blender stayed open.
    #
    # Only a pipe can do that, so only a pipe is refused. The handle type
    # comes from the Win32 API rather than from a .NET stream's seekability
    # property: on Windows PowerShell 5.1 that property reads false even for
    # a stdout redirected to a file, which would refuse the very packaged
    # entrypoint this check exists to permit. A file (FILE_TYPE_DISK), a
    # console nobody is reading (FILE_TYPE_CHAR) and a process with no
    # standard handle at all are all fine to inherit.
    if (-not ('GameStudioKit.NativeStdIo' -as [type])) {
        Add-Type -Namespace 'GameStudioKit' -Name 'NativeStdIo' -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
public static extern System.IntPtr GetStdHandle(int nStdHandle);

[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
public static extern uint GetFileType(System.IntPtr hFile);
'@
    }
    # STD_OUTPUT_HANDLE / STD_ERROR_HANDLE, and FILE_TYPE_PIPE.
    foreach ($standard in @(
        @{Name='stdout'; Id=-11},
        @{Name='stderr'; Id=-12}
    )) {
        $handle = [GameStudioKit.NativeStdIo]::GetStdHandle($standard.Id)
        # Null or INVALID_HANDLE_VALUE: this process has no such standard
        # handle, so there is nothing for Blender to inherit and hold open.
        if ($handle -eq [IntPtr]::Zero -or $handle.ToInt64() -eq -1) { continue }
        if ([GameStudioKit.NativeStdIo]::GetFileType($handle) -eq 3) {
            throw ("ensure_stdio_is_pipe: this script's $($standard.Name) is a pipe, which the " +
                   'launched Blender would inherit and hold open until the GUI is closed. Invoke ' +
                   'the packaged lifecycle through `studio blender-mcp ensure`, which redirects ' +
                   'both streams to files.')
        }
    }
}
if ($Port -lt 1024 -or $Port -gt 65535) { throw "Port must be between 1024 and 65535; got $Port" }
if ($SessionId -notmatch '^[A-Za-z0-9._-]{1,128}$') { throw 'SessionId must use 1-128 letters, digits, dots, underscores, or hyphens' }
if ($ownerName -notmatch '^[A-Za-z0-9._-]{1,128}$') { throw 'OwnerIdentity must use 1-128 letters, digits, dots, underscores, or hyphens' }
$sourcePath = (Resolve-Path -LiteralPath $SourceScene -ErrorAction Stop).Path
if (!(Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Source scene is not a file: $sourcePath" }
$sourceSha = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExpectedSourceSha256 -and $sourceSha -ne $ExpectedSourceSha256.ToLowerInvariant()) {
    throw "Source SHA-256 mismatch: expected $ExpectedSourceSha256, got $sourceSha"
}
if (!(Test-Path -LiteralPath $BlenderExe -PathType Leaf)) { throw "Blender executable missing: $BlenderExe" }
if (!(Test-Path -LiteralPath $ProbePython -PathType Leaf)) { throw "Probe Python missing: $ProbePython" }
if (!(Test-Path -LiteralPath $McpServerConfig -PathType Leaf)) { throw "MCP server config missing: $McpServerConfig" }
$hostMcp = (Get-Content -LiteralPath $McpServerConfig -Raw | ConvertFrom-Json).blender_mcp
if (!$hostMcp) { throw 'MCP server config has no blender_mcp object' }
if ($hostMcp.owner -ne $ownerName) { throw 'OwnerIdentity does not match the explicit host config' }
foreach ($pair in @(
    @{Configured=$hostMcp.working_root; Argument=$WorkingRoot; Name='WorkingRoot'},
    @{Configured=$hostMcp.blender_executable; Argument=$BlenderExe; Name='BlenderExe'},
    @{Configured=$hostMcp.probe_python; Argument=$ProbePython; Name='ProbePython'}
)) {
    if ([IO.Path]::GetFullPath($pair.Configured) -ne [IO.Path]::GetFullPath($pair.Argument)) {
        throw "$($pair.Name) does not match the explicit host config"
    }
}
$serverEnv = $hostMcp.server.env
$configuredPort = if ($null -ne $serverEnv.BLENDER_PORT -and "$($serverEnv.BLENDER_PORT)".Trim()) { [int]"$($serverEnv.BLENDER_PORT)".Trim() } else { $defaultPort }
if (!$hostMcp.server.command -or $serverEnv.BLENDER_HOST -ne '127.0.0.1' -or $serverEnv.DISABLE_TELEMETRY -ne 'true' -or $serverEnv.BLENDER_MCP_DISABLE_TELEMETRY -ne 'true') {
    throw 'MCP server config must select an explicit command, the loopback host 127.0.0.1 and telemetry off'
}
if ($configuredPort -ne $Port) {
    throw "Port does not match the explicit host config: argument $Port, config $configuredPort"
}
$kitRoot = Resolve-ReparseTarget -Path (Join-Path $PSScriptRoot '..\..\..\..')
$workingRootFull = Resolve-ReparseTarget -Path $WorkingRoot
if ($workingRootFull -eq $kitRoot -or $workingRootFull.StartsWith($kitRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'WorkingRoot must be outside the installed Game Studio Kit'
}

$plan = [ordered]@{
    status = 'PLAN_VALID'
    session_id = $SessionId
    source_scene = $sourcePath
    source_sha256 = $sourceSha
    working_root = [IO.Path]::GetFullPath($WorkingRoot)
    blender_executable = $BlenderExe
    probe_python = $ProbePython
    mcp_server_config = [IO.Path]::GetFullPath($McpServerConfig)
    owner = $ownerName
    listener = "127.0.0.1:$Port"
    port = $Port
    native_client_rehandshake_policy = $rehandshakePolicy
}
if ($PlanOnly) { $plan | ConvertTo-Json -Depth 5; return }

# One supervised session per host, whatever port it binds. The lock is not
# per-port: this lifecycle refuses to adopt or run beside a second Blender at
# all, and a per-port name would have let two of them start concurrently and
# then refuse each other halfway through.
$lifecycleMutex = [System.Threading.Mutex]::new($false, 'Global\GameStudioKit-BlenderMCP')
$mutexAcquired = $false
try {
    try {
        $mutexAcquired = $lifecycleMutex.WaitOne([TimeSpan]::FromSeconds(10))
    } catch [System.Threading.AbandonedMutexException] {
        # The previous owner terminated while holding the lock. .NET signals this
        # by throwing rather than returning true, but this wait still granted
        # ownership; treat the lifecycle mutex as acquired and continue under it.
        $mutexAcquired = $true
    }
    if (!$mutexAcquired) { throw 'Another agent is currently changing the supervised Blender MCP lifecycle' }

New-Item -ItemType Directory -Path $WorkingRoot -Force | Out-Null
$activePath = Join-Path $WorkingRoot 'active-receipt.json'
$testScript = Join-Path $PSScriptRoot 'Test-SupervisedBlenderMCP.ps1'
$bootstrap = Join-Path $PSScriptRoot 'supervised_bootstrap.py'
foreach ($dependency in @($testScript,$bootstrap,(Join-Path $PSScriptRoot 'probe_mcp.py'))) {
    if (!(Test-Path -LiteralPath $dependency -PathType Leaf)) { throw "Lifecycle dependency missing: $dependency" }
}

if (Test-Path -LiteralPath $activePath) {
    try {
        $active = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
        if (!$active.receipt_path) { throw 'Active lifecycle pointer has no receipt path' }
        $existing = Get-Content -LiteralPath $active.receipt_path -Raw | ConvertFrom-Json
        # Reuse never opens a second MCP bridge: the pinned add-on serves a
        # single active TCP connection, and the current app client may
        # already hold it. A full Test-SupervisedBlenderMCP.ps1 protocol
        # probe launches a competing stdio bridge that would contend for
        # that same connection and stall for its full read timeout. Validate
        # reuse only by owned-process identity, receipt fields and a
        # loopback-listener check (-SkipProtocolProbe) unless -Probe is
        # explicitly passed to force the full round-trip.
        # A receipt that names another port describes a listener this Ensure
        # is not asking for; reusing it would hand back a session bound
        # somewhere else and call it the configured one.
        if ($null -ne $existing.port -and [int]$existing.port -ne $Port) {
            throw "The active supervised Blender session owns port $($existing.port), not the configured port $Port; stop it with its ownership receipt first"
        }
        $reuseHealthArgs = @{
            OwnershipReceipt = $active.receipt_path
            WorkingRoot = $WorkingRoot
            ProbePython = $ProbePython
            McpServerConfig = $McpServerConfig
            OwnerIdentity = $ownerName
            Port = $Port
        }
        if (!$Probe) { $reuseHealthArgs['SkipProtocolProbe'] = $true }
        $healthJson = Invoke-LifecycleHealthCheck -Script $testScript -Arguments $reuseHealthArgs -FailureMessage 'Existing owned Blender session failed its health check'
        if ($existing.session_id -ne $SessionId) {
            throw "A healthy supervised Blender session is leased to another agent session: $($existing.session_id)"
        }
        $sameSourcePath = [string]::Equals(
            [IO.Path]::GetFullPath($existing.source_scene),
            $sourcePath,
            [StringComparison]::OrdinalIgnoreCase
        )
        if (!$sameSourcePath -or $existing.source_sha256 -ne $sourceSha) {
            throw "A healthy supervised Blender session owns port $Port for another source: $($existing.working_scene)"
        }
        $sameExecutable = [string]::Equals(
            [IO.Path]::GetFullPath($existing.executable),
            [IO.Path]::GetFullPath($BlenderExe),
            [StringComparison]::OrdinalIgnoreCase
        )
        if (!$sameExecutable) {
            throw "NEEDS_STOP: the active supervised Blender session was started from a different executable ($($existing.executable)); stop it with its ownership receipt before Ensure can start the currently configured Blender ($BlenderExe)"
        }
        $result = $healthJson | ConvertFrom-Json
        $result | Add-Member -NotePropertyName reused -NotePropertyValue $true
        $result | Add-Member -NotePropertyName native_client_rehandshake_policy -NotePropertyValue $rehandshakePolicy
        $result | ConvertTo-Json -Depth 6
        return
    } catch {
        $anyBlender = @(Get-Process -Name blender -ErrorAction SilentlyContinue)
        $anyListener = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
        if ($anyBlender.Count -or $anyListener.Count) { throw }
        Move-Item -LiteralPath $activePath -Destination ($activePath + '.stale-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    }
}

$excludedRange = Get-ExcludedPortRange -Candidate $Port
if ($excludedRange) { throw "port_excluded: port $Port lies inside the Windows excluded TCP range $excludedRange and cannot be bound; choose another BLENDER_PORT in the host config" }
$unownedBlender = @(Get-Process -Name blender -ErrorAction SilentlyContinue)
$unownedListener = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($unownedBlender.Count) { throw 'Blender is already running without a valid supervised ownership receipt; refusing to adopt it' }
if ($unownedListener.Count) { throw "port_occupied: port $Port is already occupied without a valid supervised ownership receipt" }
Assert-ParentStdioIsNotAPipe

$runDirectory = Join-Path $WorkingRoot ('runs\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $runDirectory | Out-Null
$workingScene = Join-Path $runDirectory 'working.blend'
Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runDirectory 'working.blend')
$workingCopySha = (Get-FileHash -LiteralPath $workingScene -Algorithm SHA256).Hash.ToLowerInvariant()
if ($workingCopySha -ne $sourceSha) { throw "Working-copy SHA-256 mismatch: expected $sourceSha, got $workingCopySha" }
$bootstrapReceipt = Join-Path $runDirectory 'bootstrap.json'
$ownershipReceipt = Join-Path $runDirectory 'ownership.json'
$stdout = Join-Path $runDirectory 'blender.stdout.log'
$stderr = Join-Path $runDirectory 'blender.stderr.log'
$arguments = @(
    '--disable-autoexec',
    ('"' + $workingScene + '"'),
    '--python',
    ('"' + $bootstrap + '"'),
    '--',
    ('"' + $bootstrapReceipt + '"'),
    ('"' + $workingScene + '"'),
    $sourceSha,
    $ownerName,
    $Port
)

$process = $null
try {
    $process = Start-Process -FilePath $BlenderExe -ArgumentList $arguments -WorkingDirectory $runDirectory -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $receipt = [ordered]@{
        owner = $ownerName
        session_id = $SessionId
        status = 'STARTING'
        pid = $process.Id
        process_start_utc = $process.StartTime.ToUniversalTime().ToString('o')
        executable = $BlenderExe
        port = $Port
        source_scene = $sourcePath
        source_sha256 = $sourceSha
        initial_working_sha256 = $workingCopySha
        working_scene = $workingScene
        run_directory = $runDirectory
        bootstrap_receipt = $bootstrapReceipt
        started_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    Set-ReceiptContentAtomic -Path $ownershipReceipt -Value $receipt
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "Owned Blender exited during bootstrap; inspect $runDirectory" }
        if (Test-Path -LiteralPath $bootstrapReceipt) {
            $bootstrapState = Get-Content -LiteralPath $bootstrapReceipt -Raw | ConvertFrom-Json
            if ($bootstrapState.status -eq 'PASS') { break }
            throw "Blender bootstrap failed; inspect $bootstrapReceipt"
        }
        Start-Sleep -Milliseconds 250
    }
    if (!(Test-Path -LiteralPath $bootstrapReceipt)) { throw "Blender bootstrap timed out; inspect $runDirectory" }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop)
    if ($listeners.Count -ne 1 -or $listeners[0].OwningProcess -ne $process.Id -or $listeners[0].LocalAddress -ne '127.0.0.1') {
        throw 'Blender MCP listener ownership or loopback assertion failed'
    }
    $receipt.status = 'RUNNING'
    $receipt.listener = "127.0.0.1:$Port"
    Set-ReceiptContentAtomic -Path $ownershipReceipt -Value $receipt
    $freshHealthArgs = @{
        OwnershipReceipt = $ownershipReceipt
        WorkingRoot = $WorkingRoot
        ProbePython = $ProbePython
        McpServerConfig = $McpServerConfig
        OwnerIdentity = $ownerName
        Port = $Port
    }
    # Publish the durable active pointer only after the initial protocol
    # probe has actually passed. The probe is always called with this exact
    # $ownershipReceipt (never falling back to $activePath), so publishing
    # it earlier would let a concurrent Ensure's reuse path adopt a session
    # that has not yet been verified to speak the protocol at all.
    $healthJson = Invoke-LifecycleHealthCheck -Script $testScript -Arguments $freshHealthArgs -FailureMessage 'New owned Blender session failed its protocol probe'
    Set-ReceiptContentAtomic -Path $activePath -Value @{receipt_path=[IO.Path]::GetFullPath($ownershipReceipt)} -Depth 2
    $result = $healthJson | ConvertFrom-Json
    $result | Add-Member -NotePropertyName reused -NotePropertyValue $false
    $result | Add-Member -NotePropertyName native_client_rehandshake_policy -NotePropertyValue $rehandshakePolicy
    $result | ConvertTo-Json -Depth 6
} catch {
    $startupFailure = $_
    if ($process) {
        $process.Refresh()
        if (!$process.HasExited) {
            if (![string]::Equals(
                [IO.Path]::GetFullPath($process.Path),
                [IO.Path]::GetFullPath($BlenderExe),
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw 'Startup failed; refusing cleanup because the owned process executable identity changed'
            }
            [void]$process.CloseMainWindow()
            if (!$process.WaitForExit(20000)) {
                $cleanupNote = 'Startup failed and the owned Blender process did not close after CloseMainWindow; save or dismiss the visible prompt manually. No force-kill was attempted.'
                if (Test-Path -LiteralPath $ownershipReceipt -PathType Leaf) {
                    try {
                        $failedReceipt = Get-Content -LiteralPath $ownershipReceipt -Raw | ConvertFrom-Json
                        $failedReceipt.status = 'NEEDS_USER_CLOSE'
                        $failedReceipt | Add-Member -NotePropertyName cleanup_note -NotePropertyValue $cleanupNote -Force
                        Set-ReceiptContentAtomic -Path $ownershipReceipt -Value $failedReceipt
                    } catch { }
                }
                throw $cleanupNote
            }
        }
    }
    if (Test-Path -LiteralPath $ownershipReceipt -PathType Leaf) {
        try {
            $failedReceipt = Get-Content -LiteralPath $ownershipReceipt -Raw | ConvertFrom-Json
            $failedReceipt.status = 'STARTUP_FAILED_CLOSED'
            $failedReceipt | Add-Member -NotePropertyName closed_utc -NotePropertyValue ([DateTimeOffset]::UtcNow.ToString('o')) -Force
            Set-ReceiptContentAtomic -Path $ownershipReceipt -Value $failedReceipt
        } catch { }
    }
    if (Test-Path -LiteralPath $activePath) {
        try {
            $failedActive = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
            if ([IO.Path]::GetFullPath($failedActive.receipt_path) -eq [IO.Path]::GetFullPath($ownershipReceipt)) {
                Remove-Item -LiteralPath $activePath
            }
        } catch { }
    }
    throw $startupFailure
}
} finally {
    if ($mutexAcquired) { $lifecycleMutex.ReleaseMutex() }
    $lifecycleMutex.Dispose()
}
