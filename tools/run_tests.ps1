[CmdletBinding()]
param(
    [switch]$SkipBridge
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed with exit code $LASTEXITCODE"
    }
    python -m compileall -q (Join-Path $projectRoot 'src') (Join-Path $projectRoot 'tools') (Join-Path $projectRoot 'tests')
    if ($LASTEXITCODE -ne 0) {
        throw "compileall failed with exit code $LASTEXITCODE"
    }
    if (-not $SkipBridge) {
        & (Join-Path $PSScriptRoot 'build_bridge.ps1')
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
