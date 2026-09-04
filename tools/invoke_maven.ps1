[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$MavenArguments
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $projectRoot '.tools'
$mavenVersion = '3.9.16'
$archiveName = "apache-maven-$mavenVersion-bin.zip"
$archivePath = Join-Path $toolRoot $archiveName
$mavenRoot = Join-Path $toolRoot "apache-maven-$mavenVersion"
$mavenCommand = Join-Path $mavenRoot 'bin\mvn.cmd'
$downloadUrl = "https://dlcdn.apache.org/maven/maven-3/$mavenVersion/binaries/$archiveName"
$expectedSha512 = 'ed41650d42485cfc243fad22158caf9cbb5dc408ce7a09ddb94dd42a019de929ca43065bfa450612cf12bf78b5cafa3884b96c090de326ff590448c933454af3'

if (-not (Test-Path -LiteralPath $mavenCommand)) {
    New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
    if (-not (Test-Path -LiteralPath $archivePath)) {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath -TimeoutSec 120
    }
    $actualSha512 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA512).Hash.ToLowerInvariant()
    if ($actualSha512 -ne $expectedSha512) {
        throw "Maven archive SHA-512 mismatch: expected $expectedSha512, got $actualSha512"
    }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $toolRoot -Force
}

$jdkRoot = if ($env:STS_HARNESS_JDK) {
    $env:STS_HARNESS_JDK
} else {
    'C:\Users\a4503\.jdks\jbr-21.0.11'
}
$javac = Join-Path $jdkRoot 'bin\javac.exe'
if (-not (Test-Path -LiteralPath $javac)) {
    throw "Harness JDK compiler not found: $javac"
}

$previousJavaHome = $env:JAVA_HOME
$previousPath = $env:PATH
try {
    $env:JAVA_HOME = $jdkRoot
    $env:PATH = (Join-Path $jdkRoot 'bin') + [IO.Path]::PathSeparator + $previousPath
    & $mavenCommand @MavenArguments
    exit $LASTEXITCODE
} finally {
    $env:JAVA_HOME = $previousJavaHome
    $env:PATH = $previousPath
}

