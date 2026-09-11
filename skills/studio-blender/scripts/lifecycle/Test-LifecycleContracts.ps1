param([string]$ToolRoot = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
$required = @(
    'Ensure-SupervisedBlenderMCP.ps1',
    'Test-SupervisedBlenderMCP.ps1',
    'Stop-SupervisedBlenderMCP.ps1',
    'supervised_bootstrap.py',
    'probe_mcp.py'
)

foreach ($name in $required) {
    $path = Join-Path $ToolRoot $name
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing lifecycle component: $name"
    }
}

foreach ($name in $required | Where-Object { $_ -like '*.ps1' }) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $ToolRoot $name),
        [ref]$tokens,
        [ref]$parseErrors
    ) | Out-Null
    if ($parseErrors.Count) { throw "PowerShell parse failure in ${name}: $($parseErrors | Out-String)" }
}

$ensure = Get-Content -LiteralPath (Join-Path $ToolRoot 'Ensure-SupervisedBlenderMCP.ps1') -Raw
$test = Get-Content -LiteralPath (Join-Path $ToolRoot 'Test-SupervisedBlenderMCP.ps1') -Raw
$stop = Get-Content -LiteralPath (Join-Path $ToolRoot 'Stop-SupervisedBlenderMCP.ps1') -Raw
$bootstrap = Get-Content -LiteralPath (Join-Path $ToolRoot 'supervised_bootstrap.py') -Raw
$probe = Get-Content -LiteralPath (Join-Path $ToolRoot 'probe_mcp.py') -Raw

$contracts = @(
    @{Name='ensure creates working copy'; Text=$ensure; Pattern='Copy-Item.+working\.blend'},
    @{Name='ensure checks immutable hash'; Text=$ensure; Pattern='ExpectedSourceSha256'},
    @{Name='ensure supports plan only'; Text=$ensure; Pattern='PlanOnly'},
    @{Name='ensure requires session identity'; Text=$ensure; Pattern='Parameter\(Mandatory=\$true\)\]\[string\]\$SessionId'},
    @{Name='ensure serializes startup'; Text=$ensure; Pattern='System\.Threading\.Mutex'},
    @{Name='ensure serializes across Windows sessions'; Text=$ensure; Pattern="Global\\GameStudioKit-BlenderMCP-"},
    @{Name='ensure requires explicit working root'; Text=$ensure; Pattern='Parameter\(Mandatory=\$true\)\]\[string\]\$WorkingRoot'},
    @{Name='ensure requires explicit Blender executable'; Text=$ensure; Pattern='Parameter\(Mandatory=\$true\)\]\[string\]\$BlenderExe'},
    @{Name='ensure requires explicit probe Python'; Text=$ensure; Pattern='Parameter\(Mandatory=\$true\)\]\[string\]\$ProbePython'},
    @{Name='ensure requires explicit server config'; Text=$ensure; Pattern='Parameter\(Mandatory=\$true\)\]\[string\]\$McpServerConfig'},
    @{Name='ensure requires explicit owner'; Text=$ensure; Pattern='Parameter\(Mandatory=\$true\)\]\[string\]\$OwnerIdentity'},
    @{Name='ensure refuses cross-session reuse'; Text=$ensure; Pattern='existing\.session_id -ne \$SessionId'},
    @{Name='ensure requires canonical source path for reuse'; Text=$ensure; Pattern='existing\.source_scene'},
    @{Name='ensure requires matching executable identity for reuse'; Text=$ensure; Pattern='existing\.executable'},
    @{Name='ensure refuses reuse of a different executable without force-stopping it'; Text=$ensure; Pattern='NEEDS_STOP'},
    @{Name='ensure reuse skips the protocol probe unless explicitly forced'; Text=$ensure; Pattern='if \(!\$Probe\) \{ \$reuseHealthArgs\[.SkipProtocolProbe.\] = \$true \}'},
    @{Name='ensure exposes a probe switch to force the full reuse round-trip'; Text=$ensure; Pattern='\[switch\]\$Probe'},
    @{Name='ensure judges health check by script outcome not a bare exit code'; Text=$ensure; Pattern='function Invoke-LifecycleHealthCheck'},
    @{Name='ensure treats exit code as meaningful only when a native program set it'; Text=$ensure; Pattern='\$global:LASTEXITCODE -is \[int\] -and \$global:LASTEXITCODE -ne 0'},
    @{Name='ensure checks dollar-question as a defense-in-depth failure signal'; Text=$ensure; Pattern='if \(!\$\? -or'},
    @{Name='ensure routes reuse health through the shared check helper'; Text=$ensure; Pattern='Invoke-LifecycleHealthCheck -Script \$testScript -Arguments \$reuseHealthArgs'},
    @{Name='ensure routes fresh-start health through the shared check helper'; Text=$ensure; Pattern='Invoke-LifecycleHealthCheck -Script \$testScript -Arguments \$freshHealthArgs'},
    @{Name='ensure guards active pointer parsing'; Text=$ensure; Pattern='if \(Test-Path -LiteralPath \$activePath\) \{\s*try \{\s*\$active = .+ConvertFrom-Json'},
    @{Name='ensure verifies working copy hash'; Text=$ensure; Pattern='workingCopySha'},
    @{Name='ensure closes owned startup failures without force'; Text=$ensure; Pattern='STARTUP_FAILED_CLOSED'},
    @{Name='ensure exposes bounded app rehandshake policy'; Text=$ensure; Pattern='ONE_READ_ONLY_RETRY_ON_10053'},
    @{Name='ensure uses active receipt'; Text=$ensure; Pattern='active-receipt\.json'},
    @{Name='health checks loopback'; Text=$test; Pattern="127\.0\.0\.1"},
    @{Name='health runs protocol probe'; Text=$test; Pattern='probe_mcp\.py'},
    @{Name='stop is receipt bound'; Text=$stop; Pattern='OwnershipReceipt'},
    @{Name='stop serializes lifecycle changes'; Text=$stop; Pattern='System\.Threading\.Mutex'},
    @{Name='stop requests graceful close'; Text=$stop; Pattern='CloseMainWindow'},
    @{Name='stop records manual-close state safely'; Text=$stop; Pattern='Add-Member -NotePropertyName cleanup_note'},
    @{Name='stop adds closure receipt fields safely'; Text=$stop; Pattern="Add-Member -NotePropertyName closed_utc"},
    @{Name='bootstrap binds loopback'; Text=$bootstrap; Pattern='host=["'']127\.0\.0\.1["'']'},
    @{Name='bootstrap disables telemetry'; Text=$bootstrap; Pattern='telemetry_consent = False'},
    @{Name='bootstrap records real exceptions'; Text=$bootstrap; Pattern='traceback\.format_exc\(\)'},
    @{Name='probe uses explicit server config'; Text=$probe; Pattern='--server-config'},
    @{Name='probe does not search user config'; Text=$probe; Pattern='require_current_native_status'},
    @{Name='probe checks addon'; Text=$probe; Pattern='["'']get_addon_status["'']'},
    @{Name='probe checks scene'; Text=$probe; Pattern='["'']get_scene_info["'']'},
    @{Name='probe captures viewport'; Text=$probe; Pattern='["'']get_viewport_screenshot["'']'},
    @{Name='probe checks process identity'; Text=$probe; Pattern='expected_pid'}
)

foreach ($contract in $contracts) {
    if ($contract.Text -notmatch $contract.Pattern) {
        throw "Lifecycle contract missing: $($contract.Name)"
    }
}

$forbidden = @(
    # `& $testScript ...` runs another PowerShell script, not a native
    # program, so a bare `$LASTEXITCODE -ne 0` afterward can misread a
    # $null or stale exit code as failure (see Invoke-LifecycleHealthCheck
    # above). This must never come back as the only guard on that call.
    @{Name='ensure never bare-compares $LASTEXITCODE to 0 after invoking another script'; Text=$ensure; Pattern='if \(\$LASTEXITCODE -ne 0\)'}
)

foreach ($contract in $forbidden) {
    if ($contract.Text -match $contract.Pattern) {
        throw "Forbidden lifecycle pattern present: $($contract.Name)"
    }
}

Write-Output "PASS: $($required.Count) components, $($contracts.Count) lifecycle contracts and $($forbidden.Count) forbidden patterns absent"
