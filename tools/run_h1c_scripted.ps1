[CmdletBinding()]
param(
    [string]$Config = '',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Config) {
    $Config = Join-Path $projectRoot 'benchmarks\h1c-scripted-smoke.v1.json'
}
$resolvedConfig = (Resolve-Path -LiteralPath $Config).Path
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $arguments = @(
        '-m',
        'sts_harness.h1c_run',
        '--project-root',
        $projectRoot,
        '--config',
        $resolvedConfig
    )
    if ($SkipBuild) {
        $arguments += '--skip-build'
    }
    & python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "H1-C scripted suite failed with exit code $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
