[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SuiteDir
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedSuite = (Resolve-Path -LiteralPath $SuiteDir).Path
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    & python -m sts_harness.h1c_verify --suite-dir $resolvedSuite
    if ($LASTEXITCODE -ne 0) {
        throw "H1-C scripted verification failed with exit code $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
