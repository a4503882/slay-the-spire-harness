[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9]+$')]
    [string]$Seed = 'AMIYA20260904',

    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 240,

    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gameRoot = 'F:\SteamLibrary\steamapps\common\SlayTheSpire'
$gameJar = Join-Path $gameRoot 'desktop-1.0.jar'
$gameJava = Join-Path $gameRoot 'jre\bin\java.exe'
$gameConfig = Join-Path $gameRoot 'config.json'
$steamManifest = 'F:\SteamLibrary\steamapps\appmanifest_646570.acf'
$workshopRoot = 'F:\SteamLibrary\steamapps\workshop\content\646570'
$mtsJar = Join-Path $workshopRoot '1605060445\ModTheSpire.jar'
$baseModJar = Join-Path $workshopRoot '1605833019\BaseMod.jar'
$bridgeJar = Join-Path $projectRoot 'vendor\CommunicationMod\target\CommunicationMod.jar'
$workerPath = Join-Path $PSScriptRoot 'm1_bridge_worker.py'
$pythonPath = python -c "import sys; print(sys.executable)"
if ($LASTEXITCODE -ne 0 -or -not $pythonPath) {
    throw 'Unable to resolve the real Python executable.'
}
$pythonPath = $pythonPath.Trim()

$requiredHashes = [ordered]@{
    $gameJar = 'CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673'
    (Join-Path $gameRoot 'SlayTheSpire.exe') = '44B8EACFD3843A8666E980DC9C71A50A069EF58610FB134464D1B606434C9603'
    $mtsJar = '541B5E8A875D2A404A5A6D54F4A6F814284B0CF71ACB9245239D9C5EF50EA604'
    $baseModJar = 'C3353C10E64C621B723E9FD7D0502DFA796F828B101B68513594A5F5EF83FBAF'
}

foreach ($entry in $requiredHashes.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Key)) {
        throw "Required M-1 target is missing: $($entry.Key)"
    }
    $actualHash = (Get-FileHash -LiteralPath $entry.Key -Algorithm SHA256).Hash
    if ($actualHash -ne $entry.Value) {
        throw "M-1 target hash mismatch for $($entry.Key): expected $($entry.Value), got $actualHash"
    }
}
foreach ($requiredPath in @($gameJava, $gameConfig, $steamManifest, $workerPath, $pythonPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required M-1 path is missing: $requiredPath"
    }
}

& (Join-Path $PSScriptRoot 'build_bridge.ps1')
if (-not (Test-Path -LiteralPath $bridgeJar)) {
    throw "Built bridge is missing: $bridgeJar"
}
$bridgeHash = (Get-FileHash -LiteralPath $bridgeJar -Algorithm SHA256).Hash

$active = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('java.exe', 'javaw.exe', 'SlayTheSpire.exe') -and (
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($gameRoot, [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and ($_.CommandLine -match 'SlayTheSpire|desktop-1\.0\.jar|ModTheSpire'))
    )
})
if ($active.Count -gt 0) {
    $description = $active | Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine | ConvertTo-Json -Depth 4 -Compress
    throw "A possibly related Slay the Spire process is already active. M-1 will not touch it: $description"
}

$timestamp = [DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss')
$runId = "m1-$timestamp-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$runRoot = Join-Path $projectRoot "artifacts\m1-runs\$runId"
$workRoot = Join-Path $runRoot 'work'
$profileRoot = Join-Path $runRoot 'profile'
$isolatedLocalAppData = Join-Path $profileRoot 'LocalAppData'
$isolatedAppData = Join-Path $profileRoot 'AppData'
$isolatedUserHome = Join-Path $profileRoot 'UserHome'
$isolatedMods = Join-Path $workRoot 'mods'
foreach ($directory in @($runRoot, $workRoot, $profileRoot, $isolatedLocalAppData, $isolatedAppData, $isolatedUserHome, $isolatedMods)) {
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

$preflight = [ordered]@{
    schema_version = 'sts-m1-preflight.v1'
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
    guard_before = $guardBeforePath
    active_relevant_process_count = $active.Count
    steam_localconfig_count = $steamLocalConfigs.Count
}
$preflightPath = Join-Path $runRoot 'preflight.json'
$preflight | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $preflightPath -Encoding utf8NoBOM

if ($PreflightOnly) {
    Write-Output 'M1_PREFLIGHT=PASS'
    Write-Output "RUN_ROOT=$runRoot"
    Write-Output "GAME_JAR_MATERIALIZATION=$materialization"
    Write-Output "BRIDGE_SHA256=$bridgeHash"
    exit 0
}

$stdoutPath = Join-Path $runRoot 'modthespire-stdout.log'
$stderrPath = Join-Path $runRoot 'modthespire-stderr.log'
$workerSummaryPath = Join-Path $runRoot 'worker-summary.json'
$process = $null
$stdoutTask = $null
$stderrTask = $null
$timedOut = $false
$ownedProcessStopped = $false
$launchError = $null

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
    $startInfo.Environment['STS_HARNESS_SEED'] = $Seed.ToUpperInvariant()
    $startInfo.Environment['STS_HARNESS_MAX_COMMANDS'] = '64'
    $startInfo.Environment['PYTHONPATH'] = Join-Path $projectRoot 'src'

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw 'Native Java process did not start.'
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not (Test-Path -LiteralPath $workerSummaryPath)) {
        if ($process.HasExited) {
            break
        }
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            $timedOut = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
} catch {
    $launchError = $_.Exception.Message
} finally {
    if ($null -ne $process -and -not $process.HasExited) {
        $process.Kill($true)
        $process.WaitForExit(10000) | Out-Null
        $ownedProcessStopped = $process.HasExited
    } elseif ($null -ne $process) {
        $ownedProcessStopped = $true
    }
    if ($null -ne $stdoutTask) {
        [IO.File]::WriteAllText($stdoutPath, $stdoutTask.Result, [Text.UTF8Encoding]::new($false))
    }
    if ($null -ne $stderrTask) {
        [IO.File]::WriteAllText($stderrPath, $stderrTask.Result, [Text.UTF8Encoding]::new($false))
    }
}

$workerSummary = if (Test-Path -LiteralPath $workerSummaryPath) {
    Get-Content -LiteralPath $workerSummaryPath -Raw | ConvertFrom-Json
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

$report = [ordered]@{
    schema_version = 'sts-m1-run-report.v1'
    run_id = $runId
    finished_at = [DateTimeOffset]::UtcNow.ToString('o')
    status = if (
        $null -ne $workerSummary -and
        $workerSummary.status -eq 'passed' -and
        $guardResult.unchanged -eq $true -and
        $ownedProcessStopped -and
        -not $timedOut -and
        $null -eq $launchError
    ) { 'passed' } else { 'failed' }
    timed_out = $timedOut
    launch_error = $launchError
    java_pid = if ($null -ne $process) { $process.Id } else { $null }
    java_exit_code = if ($null -ne $process -and $process.HasExited) { $process.ExitCode } else { $null }
    owned_process_stopped = $ownedProcessStopped
    worker = $workerSummary
    normal_guard = $guardResult
    bridge_sha256 = $bridgeHash
    game_jar_materialization = $materialization
    run_root = $runRoot
}
$reportPath = Join-Path $runRoot 'm1-report.json'
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding utf8NoBOM

Write-Output "M1_STATUS=$($report.status.ToUpperInvariant())"
Write-Output "RUN_ROOT=$runRoot"
Write-Output "WORKER_STATUS=$(if ($null -ne $workerSummary) { $workerSummary.status } else { 'missing' })"
Write-Output "NORMAL_GUARD_UNCHANGED=$($guardResult.unchanged)"
Write-Output "OWNED_PROCESS_STOPPED=$ownedProcessStopped"
Write-Output "TIMED_OUT=$timedOut"
Write-Output "REPORT=$reportPath"

if ($report.status -ne 'passed') {
    exit 2
}
