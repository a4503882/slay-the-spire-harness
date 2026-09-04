[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9]+$')]
    [string]$Seed = 'AMIYA20260904',

    [ValidateRange(60, 14400)]
    [int]$TimeoutSeconds = 1800,

    [ValidateRange(16, 10000)]
    [int]$MaxDecisions = 5000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    python -m sts_harness.h1b_run `
        --project-root $projectRoot `
        --seed $Seed `
        --timeout-seconds $TimeoutSeconds `
        --max-decisions $MaxDecisions
    if ($LASTEXITCODE -ne 0) {
        throw "H1-B corpus failed with exit code $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
