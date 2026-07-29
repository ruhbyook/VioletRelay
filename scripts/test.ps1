param(
    [switch]$SkipMediaIntegration
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run scripts\bootstrap.ps1 first."
}

$env:QT_QPA_PLATFORM = "offscreen"
& .venv\Scripts\python.exe -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Ffmpeg = "vendor\ffmpeg\bin\ffmpeg.exe"
$Ffprobe = "vendor\ffmpeg\bin\ffprobe.exe"
if (-not $SkipMediaIntegration -and
    (Test-Path -LiteralPath $Ffmpeg -PathType Leaf) -and
    (Test-Path -LiteralPath $Ffprobe -PathType Leaf)) {
    & "$PSScriptRoot\generate_test_fixtures.ps1"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & .venv\Scripts\python.exe "scripts\validate_media_pipeline.py"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
elseif (-not $SkipMediaIntegration) {
    Write-Warning "FFmpeg is unavailable; skipping synthetic media integration tests."
}
