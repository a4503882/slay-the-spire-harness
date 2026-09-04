[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9]+$')]
    [string]$Seed = 'AMIYA20260904',

    [ValidateRange(60, 900)]
    [int]$TimeoutSeconds = 300,

    [ValidateRange(16, 512)]
    [int]$MaxDecisions = 128,

    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gameRoot = 'F:\SteamLibrary\steamapps\common\SlayTheSpire'
$gameJar = Join-Path $gameRoot 'desktop-1.0.jar'
$gameExe = Join-Path $gameRoot 'SlayTheSpire.exe'
$gameJava = Join-Path $gameRoot 'jre\bin\java.exe'
$gameConfig = Join-Path $gameRoot 'config.json'
$steamManifest = 'F:\SteamLibrary\steamapps\appmanifest_646570.acf'
$workshopRoot = 'F:\SteamLibrary\steamapps\workshop\content\646570'
$mtsJar = Join-Path $workshopRoot '1605060445\ModTheSpire.jar'
$baseModJar = Join-Path $workshopRoot '1605833019\BaseMod.jar'
$bridgeJar = Join-Path $projectRoot 'vendor\CommunicationMod\target\CommunicationMod.jar'
$workerPath = Join-Path $PSScriptRoot 'h1_bridge_worker.py'
$pythonPath = python -c "import sys; print(sys.executable)"
if ($LASTEXITCODE -ne 0 -or -not $pythonPath) {
    throw 'Unable to resolve the real Python executable.'
}
$pythonPath = $pythonPath.Trim()

$requiredHashes = [ordered]@{
    $gameJar = 'CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673'
    $gameExe = '44B8EACFD3843A8666E980DC9C71A50A069EF58610FB134464D1B606434C9603'
    $mtsJar = '541B5E8A875D2A404A5A6D54F4A6F814284B0CF71ACB9245239D9C5EF50EA604'
    $baseModJar = 'C3353C10E64C621B723E9FD7D0502DFA796F828B101B68513594A5F5EF83FBAF'
}
foreach ($entry in $requiredHashes.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Key)) {
        throw "Required H1-A target is missing: $($entry.Key)"
    }
    $actualHash = (Get-FileHash -LiteralPath $entry.Key -Algorithm SHA256).Hash
    if ($actualHash -ne $entry.Value) {
        throw "H1-A target hash mismatch for $($entry.Key): expected $($entry.Value), got $actualHash"
    }
}
foreach ($requiredPath in @($gameJava, $gameConfig, $steamManifest, $workerPath, $pythonPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required H1-A path is missing: $requiredPath"
    }
}

& (Join-Path $PSScriptRoot 'build_bridge.ps1')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $bridgeJar)) {
    throw 'Reproducible bridge build failed or produced no JAR.'
}
$bridgeHash = (Get-FileHash -LiteralPath $bridgeJar -Algorithm SHA256).Hash
$javaHash = (Get-FileHash -LiteralPath $gameJava -Algorithm SHA256).Hash
$javaVersion = (& $gameJava -version 2>&1 | Out-String).Trim()

$active = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('java.exe', 'javaw.exe', 'SlayTheSpire.exe') -and (
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($gameRoot, [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and ($_.CommandLine -match 'SlayTheSpire|desktop-1\.0\.jar|ModTheSpire'))
    )
})
if ($active.Count -gt 0) {
    $description = $active | Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine | ConvertTo-Json -Depth 4 -Compress
    throw "A possibly related Slay the Spire process is already active. H1-A will not touch it: $description"
}

$timestamp = [DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss')
$runId = "h1a-$timestamp-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$episodeId = "ep_$([Guid]::NewGuid().ToString('N'))"
$nativeSessionId = "native_$([Guid]::NewGuid().ToString('N'))"
$runRoot = Join-Path $projectRoot "artifacts\runs\$runId"
$workRoot = Join-Path $runRoot 'work'
$profileRoot = Join-Path $runRoot 'profile'
$isolatedLocalAppData = Join-Path $profileRoot 'LocalAppData'
$isolatedAppData = Join-Path $profileRoot 'AppData'
$isolatedUserHome = Join-Path $profileRoot 'UserHome'
$isolatedMods = Join-Path $workRoot 'mods'
foreach ($directory in @(
    $runRoot,
    $workRoot,
    $profileRoot,
    $isolatedLocalAppData,
    $isolatedAppData,
    $isolatedUserHome,
    $isolatedMods
)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$guardBeforePath = Join-Path $runRoot 'normal-guard-before.json'
$guardAfterPath = Join-Path $runRoot 'normal-guard-after.json'
$guardResultPath = Join-Path $runRoot 'normal-guard-result.json'
$localConfigRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ModTheSpire'
$steamLocalConfigs = @(Get-ChildItem -LiteralPath 'C:\Program Files (x86)\Steam\userdata' -Filter 'localconfig.vdf' -File -Recurse -ErrorAction SilentlyContinue)
$guardArguments = @(
    '-m', 'sts_harness.guard_cli', 'snapshot',
    '--root', "game_install=$gameRoot",
    '--root', "workshop_mods=$workshopRoot",
    '--root', "modthespire_config=$localConfigRoot",
    '--root', "steam_manifest=$steamManifest"
)
foreach ($localConfig in $steamLocalConfigs) {
    $guardArguments += @('--root', "steam_localconfig_$($localConfig.Directory.Parent.Name)=$($localConfig.FullName)")
}
$guardArguments += @('--output', $guardBeforePath)

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    & $pythonPath @guardArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Pre-run normal-data fingerprint failed with exit code $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

$gameCacheRoot = Join-Path $projectRoot '.tools\game-cache\CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673'
$cachedGameJar = Join-Path $gameCacheRoot 'desktop-1.0.jar'
New-Item -ItemType Directory -Path $gameCacheRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $cachedGameJar)) {
    Copy-Item -LiteralPath $gameJar -Destination $cachedGameJar
}
$cachedHash = (Get-FileHash -LiteralPath $cachedGameJar -Algorithm SHA256).Hash
if ($cachedHash -ne $requiredHashes[$gameJar]) {
    throw "Cached game JAR hash mismatch: expected $($requiredHashes[$gameJar]), got $cachedHash"
}
$materialization = 'hardlink-to-verified-cache'
New-Item -ItemType HardLink -Path (Join-Path $workRoot 'desktop-1.0.jar') -Target $cachedGameJar -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath $gameConfig -Destination (Join-Path $workRoot 'config.json')
Copy-Item -LiteralPath $baseModJar -Destination (Join-Path $isolatedMods 'BaseMod.jar')
Copy-Item -LiteralPath $bridgeJar -Destination (Join-Path $isolatedMods 'CommunicationMod.jar')
Copy-Item -LiteralPath (Join-Path $gameRoot 'preferences') -Destination $workRoot -Recurse
New-Item -ItemType Directory -Path (Join-Path $workRoot 'saves') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $workRoot 'betaPreferences') -Force | Out-Null

$harnessFiles = [ordered]@{}
foreach ($relativePath in @(
    'src\sts_harness\canonical.py',
    'src\sts_harness\framing.py',
    'src\sts_harness\rpc_protocol.py',
    'src\sts_harness\client.py',
    'src\sts_harness\observation.py',
    'src\sts_harness\legal_actions.py',
    'src\sts_harness\action_verify.py',
    'src\sts_harness\transition.py',
    'src\sts_harness\runtime.py',
    'src\sts_harness\server.py',
    'src\sts_harness\h1_worker.py',
    'src\sts_harness\h1_baseline.py',
    'src\sts_harness\environment.py',
    'src\sts_harness\replay_verify.py',
    'src\sts_harness\h1_verify.py',
    'tools\h1_bridge_worker.py',
    'tools\run_h1_baseline.py',
    'tools\run_h1a_probe.ps1'
)) {
    $harnessFiles[$relativePath.Replace('\', '/')] = (Get-FileHash -LiteralPath (Join-Path $projectRoot $relativePath) -Algorithm SHA256).Hash
}
$environmentPath = Join-Path $runRoot 'environment.json'
$environment = [ordered]@{
    schema_version = 'sts-environment.v1'
    target = [ordered]@{
        steam_app_id = 646570
        steam_build = 10180494
        game_sha256 = $requiredHashes[$gameJar]
        executable_sha256 = $requiredHashes[$gameExe]
    }
    jvm = [ordered]@{
        sha256 = $javaHash
        version = $javaVersion
    }
    mod_the_spire = [ordered]@{
        version = '3.30.3'
        sha256 = $requiredHashes[$mtsJar]
    }
    base_mod = [ordered]@{
        version = '5.56.0'
        sha256 = $requiredHashes[$baseModJar]
    }
    bridge = [ordered]@{
        version = '1.2.1-sts-harness.1'
        protocol_version = 'communicationmod-harness.v1'
        upstream_commit = '5e417eb189530986b9047a3c9426889fb261d146'
        sha256 = $bridgeHash
    }
    harness = [ordered]@{
        version = '0.1.0'
        python = $pythonPath
        files = $harnessFiles
    }
    enabled_mods = @('basemod', 'CommunicationMod')
    observation_schema = 'sts-observation.v1'
    legal_actions_schema = 'sts-legal-actions.v1'
    transition_schema = 'sts-transition.v1'
    fairness_profile = 'player_visible.v1'
}
$environment | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $environmentPath -Encoding utf8NoBOM
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $environmentId = (& $pythonPath -m sts_harness.environment --path $environmentPath).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $environmentId.StartsWith('sha256:')) {
        throw 'Environment fingerprint sealing failed.'
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

$configPath = Join-Path $runRoot 'config.json'
[ordered]@{
    schema_version = 'sts-h1a-run-config.v1'
    run_id = $runId
    episode_id = $episodeId
    native_session_id = $nativeSessionId
    seed = $Seed.ToUpperInvariant()
    character_id = 'IRONCLAD'
    ascension = 0
    fairness_profile = 'player_visible.v1'
    policy_mode = 'scripted'
    max_episode_decisions = $MaxDecisions
    max_episode_seconds = $TimeoutSeconds
    environment_fingerprint_id = $environmentId
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding utf8NoBOM

$preflightPath = Join-Path $runRoot 'preflight.json'
[ordered]@{
    schema_version = 'sts-h1a-preflight.v1'
    run_id = $runId
    created_at = [DateTimeOffset]::UtcNow.ToString('o')
    seed = $Seed.ToUpperInvariant()
    game_root = $gameRoot
    work_root = $workRoot
    profile_root = $profileRoot
    game_jar_materialization = $materialization
    python = $pythonPath
    bridge_path = $bridgeJar
    bridge_sha256 = $bridgeHash
    environment_fingerprint_id = $environmentId
    guard_before = $guardBeforePath
    active_relevant_process_count = $active.Count
    steam_localconfig_count = $steamLocalConfigs.Count
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $preflightPath -Encoding utf8NoBOM

if ($PreflightOnly) {
    Write-Output 'H1A_PREFLIGHT=PASS'
    Write-Output "RUN_ROOT=$runRoot"
    Write-Output "ENVIRONMENT_FINGERPRINT_ID=$environmentId"
    Write-Output "BRIDGE_SHA256=$bridgeHash"
    exit 0
}

$stdoutPath = Join-Path $runRoot 'modthespire-stdout.log'
$stderrPath = Join-Path $runRoot 'modthespire-stderr.log'
$driverStdoutPath = Join-Path $runRoot 'driver-stdout.log'
$driverStderrPath = Join-Path $runRoot 'driver-stderr.log'
$driverSummaryPath = Join-Path $runRoot 'driver-summary.json'
$workerSummaryPath = Join-Path $runRoot 'worker-summary.json'
$descriptorPath = Join-Path $runRoot 'sidecar.json'
$process = $null
$driverProcess = $null
$stdoutTask = $null
$stderrTask = $null
$driverStdoutTask = $null
$driverStderrTask = $null
$timedOut = $false
$launchError = $null
$ownedJavaStopped = $false
$ownedDriverStopped = $false
$descriptorAclRestricted = $false
$driverExitCode = $null
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)

try {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $gameJava
    $startInfo.WorkingDirectory = $workRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in @(
        '-Xmx1G',
        '-Dsun.java2d.dpiaware=true',
        "-Duser.home=$isolatedUserHome",
        '-jar',
        $mtsJar,
        '--skip-launcher',
        '--skip-intro',
        '--mods',
        'basemod,CommunicationMod'
    )) {
        $startInfo.ArgumentList.Add($argument)
    }
    $startInfo.Environment['LOCALAPPDATA'] = $isolatedLocalAppData
    $startInfo.Environment['APPDATA'] = $isolatedAppData
    $startInfo.Environment['USERPROFILE'] = $isolatedUserHome
    $startInfo.Environment['STS_HARNESS_AUTOSTART'] = '1'
    $startInfo.Environment['STS_HARNESS_PYTHON'] = $pythonPath
    $startInfo.Environment['STS_HARNESS_WORKER'] = $workerPath
    $startInfo.Environment['STS_HARNESS_RUN_DIR'] = $runRoot
    $startInfo.Environment['STS_HARNESS_EPISODE_ID'] = $episodeId
    $startInfo.Environment['STS_HARNESS_NATIVE_SESSION_ID'] = $nativeSessionId
    $startInfo.Environment['STS_HARNESS_ENVIRONMENT_FINGERPRINT_ID'] = $environmentId
    $startInfo.Environment['STS_HARNESS_STATE_TIMEOUT_SECONDS'] = '30'
    $startInfo.Environment['PYTHONPATH'] = Join-Path $projectRoot 'src'

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw 'Owned native Java process did not start.'
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    while (-not (Test-Path -LiteralPath $descriptorPath)) {
        if ($process.HasExited) {
            throw "Owned Java process exited before sidecar descriptor (exit $($process.ExitCode))."
        }
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            $timedOut = $true
            throw 'Timed out waiting for H1-A sidecar descriptor.'
        }
        Start-Sleep -Milliseconds 100
    }

    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $descriptorPath '/inheritance:r' '/grant:r' "*$($currentSid):(F)" '/grant:r' '*S-1-5-18:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to restrict the sidecar descriptor ACL (icacls exit $LASTEXITCODE)."
    }
    $descriptorAclRestricted = $true

    $driverInfo = [Diagnostics.ProcessStartInfo]::new()
    $driverInfo.FileName = $pythonPath
    $driverInfo.WorkingDirectory = $projectRoot
    $driverInfo.UseShellExecute = $false
    $driverInfo.CreateNoWindow = $true
    $driverInfo.RedirectStandardOutput = $true
    $driverInfo.RedirectStandardError = $true
    foreach ($argument in @(
        '-m',
        'sts_harness.h1_baseline',
        '--descriptor',
        $descriptorPath,
        '--output',
        $driverSummaryPath,
        '--seed',
        $Seed.ToUpperInvariant(),
        '--max-decisions',
        $MaxDecisions.ToString(),
        '--timeout-seconds',
        $TimeoutSeconds.ToString()
    )) {
        $driverInfo.ArgumentList.Add($argument)
    }
    $driverInfo.Environment['PYTHONPATH'] = Join-Path $projectRoot 'src'
    $driverProcess = [Diagnostics.Process]::new()
    $driverProcess.StartInfo = $driverInfo
    if (-not $driverProcess.Start()) {
        throw 'Owned H1-A baseline process did not start.'
    }
    $driverStdoutTask = $driverProcess.StandardOutput.ReadToEndAsync()
    $driverStderrTask = $driverProcess.StandardError.ReadToEndAsync()
    while (-not $driverProcess.HasExited) {
        if ($process.HasExited) {
            throw "Owned Java process exited while the baseline was running (exit $($process.ExitCode))."
        }
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            $timedOut = $true
            throw 'H1-A baseline exceeded the run timeout.'
        }
        Start-Sleep -Milliseconds 100
    }
    $driverExitCode = $driverProcess.ExitCode
    $ownedDriverStopped = $true

    while (-not (Test-Path -LiteralPath $workerSummaryPath)) {
        if ($process.HasExited) {
            break
        }
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            $timedOut = $true
            break
        }
        Start-Sleep -Milliseconds 100
    }
} catch {
    $launchError = $_.Exception.Message
} finally {
    if ($null -ne $driverProcess -and -not $driverProcess.HasExited) {
        $driverProcess.Kill($true)
        $driverProcess.WaitForExit(10000) | Out-Null
        $ownedDriverStopped = $driverProcess.HasExited
    } elseif ($null -ne $driverProcess) {
        $ownedDriverStopped = $true
    }
    if ($null -ne $process -and -not $process.HasExited) {
        $process.Kill($true)
        $process.WaitForExit(10000) | Out-Null
        $ownedJavaStopped = $process.HasExited
    } elseif ($null -ne $process) {
        $ownedJavaStopped = $true
    }
    if ($null -ne $stdoutTask) {
        [IO.File]::WriteAllText($stdoutPath, $stdoutTask.Result, [Text.UTF8Encoding]::new($false))
    }
    if ($null -ne $stderrTask) {
        [IO.File]::WriteAllText($stderrPath, $stderrTask.Result, [Text.UTF8Encoding]::new($false))
    }
    if ($null -ne $driverStdoutTask) {
        [IO.File]::WriteAllText($driverStdoutPath, $driverStdoutTask.Result, [Text.UTF8Encoding]::new($false))
    }
    if ($null -ne $driverStderrTask) {
        [IO.File]::WriteAllText($driverStderrPath, $driverStderrTask.Result, [Text.UTF8Encoding]::new($false))
    }
}

for ($index = 0; $index -lt 30 -and (Test-Path -LiteralPath $descriptorPath); $index++) {
    Start-Sleep -Milliseconds 100
}
$sidecarDescriptorRemoved = -not (Test-Path -LiteralPath $descriptorPath)
$workerSummary = if (Test-Path -LiteralPath $workerSummaryPath) {
    Get-Content -LiteralPath $workerSummaryPath -Raw | ConvertFrom-Json
} else {
    $null
}
$driverSummary = if (Test-Path -LiteralPath $driverSummaryPath) {
    Get-Content -LiteralPath $driverSummaryPath -Raw | ConvertFrom-Json
} else {
    $null
}

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $afterArguments = @($guardArguments)
    $afterArguments[$afterArguments.Count - 1] = $guardAfterPath
    & $pythonPath @afterArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Post-run normal-data fingerprint failed with exit code $LASTEXITCODE"
    }
    & $pythonPath -m sts_harness.guard_cli compare --before $guardBeforePath --after $guardAfterPath --output $guardResultPath
    if ($LASTEXITCODE -ne 0) {
        throw "Normal-data guard comparison failed with exit code $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
$guardResult = Get-Content -LiteralPath $guardResultPath -Raw | ConvertFrom-Json

$replayPath = Join-Path $runRoot 'replay.json'
$replay = $null
if (Test-Path -LiteralPath (Join-Path $runRoot 'transitions.jsonl')) {
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $projectRoot 'src'
        & $pythonPath -m sts_harness.replay_verify --run-dir $runRoot --output $replayPath | Out-Null
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
    if (Test-Path -LiteralPath $replayPath) {
        $replay = Get-Content -LiteralPath $replayPath -Raw | ConvertFrom-Json
    }
}

$report = [ordered]@{
    schema_version = 'sts-h1a-run-report.v1'
    run_id = $runId
    episode_id = $episodeId
    finished_at = [DateTimeOffset]::UtcNow.ToString('o')
    status = if (
        $null -ne $workerSummary -and
        $workerSummary.status -eq 'passed' -and
        $null -ne $driverSummary -and
        $driverSummary.status -eq 'passed' -and
        $driverSummary.one_combat_completed -eq $true -and
        $null -ne $replay -and
        $replay.status -eq 'REPLAY_VALID' -and
        $guardResult.unchanged -eq $true -and
        $ownedJavaStopped -and
        $ownedDriverStopped -and
        $sidecarDescriptorRemoved -and
        -not $timedOut -and
        $null -eq $launchError
    ) { 'passed' } else { 'failed' }
    timed_out = $timedOut
    launch_error = $launchError
    java_pid = if ($null -ne $process) { $process.Id } else { $null }
    java_exit_code = if ($null -ne $process -and $process.HasExited) { $process.ExitCode } else { $null }
    driver_pid = if ($null -ne $driverProcess) { $driverProcess.Id } else { $null }
    driver_exit_code = $driverExitCode
    owned_java_stopped = $ownedJavaStopped
    owned_driver_stopped = $ownedDriverStopped
    sidecar_descriptor_removed = $sidecarDescriptorRemoved
    descriptor_acl_restricted = $descriptorAclRestricted
    worker = $workerSummary
    driver = $driverSummary
    replay = $replay
    normal_guard = $guardResult
    environment_fingerprint_id = $environmentId
    bridge_sha256 = $bridgeHash
    game_jar_materialization = $materialization
    run_root = $runRoot
}
$reportPath = Join-Path $runRoot 'h1-report.json'
$report | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $reportPath -Encoding utf8NoBOM

$verificationPath = Join-Path $runRoot 'h1-independent-verification.json'
$verification = $null
if ($report.status -eq 'passed') {
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $projectRoot 'src'
        & $pythonPath -m sts_harness.h1_verify --run-dir $runRoot --output $verificationPath | Out-Null
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
    if (Test-Path -LiteralPath $verificationPath) {
        $verification = Get-Content -LiteralPath $verificationPath -Raw | ConvertFrom-Json
    }
    if ($null -eq $verification -or $verification.valid -ne $true) {
        $report['status'] = 'failed'
        $report['independent_verification'] = $verification
        $report | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $reportPath -Encoding utf8NoBOM
    }
}

Write-Output "H1A_STATUS=$($report.status.ToUpperInvariant())"
Write-Output "RUN_ROOT=$runRoot"
Write-Output "WORKER_STATUS=$(if ($null -ne $workerSummary) { $workerSummary.status } else { 'missing' })"
Write-Output "DRIVER_STATUS=$(if ($null -ne $driverSummary) { $driverSummary.status } else { 'missing' })"
Write-Output "ONE_COMBAT_COMPLETED=$(if ($null -ne $driverSummary) { $driverSummary.one_combat_completed } else { $false })"
Write-Output "REPLAY_STATUS=$(if ($null -ne $replay) { $replay.status } else { 'missing' })"
Write-Output "NORMAL_GUARD_UNCHANGED=$($guardResult.unchanged)"
Write-Output "OWNED_JAVA_STOPPED=$ownedJavaStopped"
Write-Output "OWNED_DRIVER_STOPPED=$ownedDriverStopped"
Write-Output "SIDECAR_DESCRIPTOR_REMOVED=$sidecarDescriptorRemoved"
Write-Output "REPORT=$reportPath"
Write-Output "VERIFICATION=$verificationPath"

if ($report.status -ne 'passed') {
    exit 2
}
