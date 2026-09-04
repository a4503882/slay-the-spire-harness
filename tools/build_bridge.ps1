[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$bridgeRoot = Join-Path $projectRoot 'vendor\CommunicationMod'
$pomPath = Join-Path $bridgeRoot 'pom.xml'
$artifactPath = Join-Path $bridgeRoot 'target\CommunicationMod.jar'
$buildRoot = Join-Path $projectRoot 'artifacts\build'
$reportPath = Join-Path $buildRoot 'bridge-build.json'

$targets = @(
    @{
        Name = 'game'
        Path = 'F:\SteamLibrary\steamapps\common\SlayTheSpire\desktop-1.0.jar'
        Sha256 = 'CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673'
    },
    @{
        Name = 'modthespire'
        Path = 'F:\SteamLibrary\steamapps\workshop\content\646570\1605060445\ModTheSpire.jar'
        Sha256 = '541B5E8A875D2A404A5A6D54F4A6F814284B0CF71ACB9245239D9C5EF50EA604'
    },
    @{
        Name = 'basemod'
        Path = 'F:\SteamLibrary\steamapps\workshop\content\646570\1605833019\BaseMod.jar'
        Sha256 = 'C3353C10E64C621B723E9FD7D0502DFA796F828B101B68513594A5F5EF83FBAF'
    }
)

$verified = @()
foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target.Path)) {
        throw "Required $($target.Name) input is missing: $($target.Path)"
    }
    $actual = (Get-FileHash -LiteralPath $target.Path -Algorithm SHA256).Hash
    if ($actual -ne $target.Sha256) {
        throw "Required $($target.Name) hash mismatch: expected $($target.Sha256), got $actual"
    }
    $verified += [ordered]@{
        name = $target.Name
        path = $target.Path
        sha256 = $actual
        bytes = (Get-Item -LiteralPath $target.Path).Length
    }
}

$env:STS_GAME_JAR = $targets[0].Path
$env:STS_MTS_JAR = $targets[1].Path
$env:STS_BASEMOD_JAR = $targets[2].Path

$invokeMaven = Join-Path $PSScriptRoot 'invoke_maven.ps1'
& $invokeMaven @('-f', $pomPath, '--batch-mode', 'clean', 'package')
if ($LASTEXITCODE -ne 0) {
    throw "Bridge Maven build failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $artifactPath)) {
    throw "Bridge build did not produce $artifactPath"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($artifactPath)
try {
    $manifestEntry = $zip.GetEntry('ModTheSpire.json')
    if ($null -eq $manifestEntry) {
        throw 'Built bridge does not contain ModTheSpire.json'
    }
    $reader = [IO.StreamReader]::new($manifestEntry.Open())
    try {
        $modInfo = $reader.ReadToEnd() | ConvertFrom-Json
    } finally {
        $reader.Dispose()
    }
} finally {
    $zip.Dispose()
}
if ($modInfo.version -ne '1.2.1-sts-harness.2') {
    throw "Unexpected bridge version in ModTheSpire.json: $($modInfo.version)"
}

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$report = [ordered]@{
    schema_version = 'sts-bridge-build.v1'
    built_at = [DateTimeOffset]::UtcNow.ToString('o')
    upstream_commit = '5e417eb189530986b9047a3c9426889fb261d146'
    bridge_version = $modInfo.version
    mod_id = $modInfo.modid
    artifact_path = $artifactPath
    artifact_bytes = (Get-Item -LiteralPath $artifactPath).Length
    artifact_sha256 = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash
    inputs = $verified
}
$temporaryReport = Join-Path $buildRoot '.bridge-build.json.tmp'
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryReport -Encoding utf8NoBOM
Move-Item -LiteralPath $temporaryReport -Destination $reportPath -Force

Write-Output "BRIDGE_BUILD=PASS"
Write-Output "BRIDGE_VERSION=$($report.bridge_version)"
Write-Output "BRIDGE_PATH=$artifactPath"
Write-Output "BRIDGE_BYTES=$($report.artifact_bytes)"
Write-Output "BRIDGE_SHA256=$($report.artifact_sha256)"
Write-Output "BUILD_REPORT=$reportPath"
