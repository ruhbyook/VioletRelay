param(
    [switch]$SkipPython,
    [switch]$SkipFFmpeg
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $SkipPython) {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        py -3.13 -m venv .venv
    }
    & .venv\Scripts\python.exe -m pip install --upgrade pip
    & .venv\Scripts\python.exe -m pip install -r requirements.lock
    & .venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
}

if (-not $SkipFFmpeg) {
    $Bin = Join-Path $Root "vendor\ffmpeg\bin"
    $Ffmpeg = Join-Path $Bin "ffmpeg.exe"
    $Ffprobe = Join-Path $Bin "ffprobe.exe"
    $ExpectedArchive = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
    $ExpectedFfmpeg = "1326dde4c84ff1f96fe6b8916c5bed29e163e9b5dccf995f6f3db069d143ec5e"
    $ExpectedFfprobe = "b49ccc7c6547b141ad5a2f6ec69cc04323d7133d7704d70b331b904c63eecb07"
    $ToolsValid = (Test-Path $Ffmpeg) -and (Test-Path $Ffprobe)
    if ($ToolsValid) {
        $ToolsValid = `
            ((Get-FileHash -Algorithm SHA256 $Ffmpeg).Hash.ToLowerInvariant() -eq $ExpectedFfmpeg) -and `
            ((Get-FileHash -Algorithm SHA256 $Ffprobe).Hash.ToLowerInvariant() -eq $ExpectedFfprobe)
    }
    if (-not $ToolsValid) {
        $Tools = Join-Path $Root ".tools"
        $Archive = Join-Path $Tools "ffmpeg-8.1.2-essentials_build.zip"
        $Extracted = Join-Path $Tools "ffmpeg-extracted"
        New-Item -ItemType Directory -Force -Path $Tools, $Bin | Out-Null

        $Actual = if (Test-Path $Archive) {
            (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLowerInvariant()
        } else { "" }
        if ($Actual -ne $ExpectedArchive) {
            $Uri = "https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/ffmpeg-8.1.2-essentials_build.zip"
            $Curl = Get-Command curl.exe -ErrorAction SilentlyContinue
            if ($Curl) {
                & $Curl.Source --fail --location --retry 4 --retry-delay 2 --continue-at - --output $Archive $Uri
                if ($LASTEXITCODE -ne 0) { throw "FFmpeg download failed with curl exit code $LASTEXITCODE." }
            } else {
                if (Test-Path $Archive) { Remove-Item -LiteralPath $Archive -Force }
                Invoke-WebRequest -Uri $Uri -OutFile $Archive
            }
        }
        $Actual = (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLowerInvariant()
        if ($ExpectedArchive -ne $Actual) {
            throw "FFmpeg SHA-256 verification failed. Expected $ExpectedArchive but received $Actual."
        }

        if (Test-Path $Extracted) { Remove-Item -LiteralPath $Extracted -Recurse -Force }
        Expand-Archive -LiteralPath $Archive -DestinationPath $Extracted -Force
        $SourceBin = Get-ChildItem -Path $Extracted -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1 -ExpandProperty DirectoryName
        if (-not $SourceBin) { throw "The verified FFmpeg archive did not contain ffmpeg.exe." }
        Copy-Item -LiteralPath (Join-Path $SourceBin "ffmpeg.exe") -Destination $Ffmpeg -Force
        Copy-Item -LiteralPath (Join-Path $SourceBin "ffprobe.exe") -Destination $Ffprobe -Force
        $License = Get-ChildItem -Path $Extracted -Recurse -Filter "LICENSE" | Select-Object -First 1
        if ($License) { Copy-Item -LiteralPath $License.FullName -Destination (Join-Path (Split-Path $Bin) "LICENSE.txt") -Force }
        if ((Get-FileHash -Algorithm SHA256 $Ffmpeg).Hash.ToLowerInvariant() -ne $ExpectedFfmpeg) {
            throw "The extracted ffmpeg.exe does not match the pinned SHA-256."
        }
        if ((Get-FileHash -Algorithm SHA256 $Ffprobe).Hash.ToLowerInvariant() -ne $ExpectedFfprobe) {
            throw "The extracted ffprobe.exe does not match the pinned SHA-256."
        }
    }
}

Write-Host "xMediaPlayerx development environment is ready." -ForegroundColor Green
Write-Host "Run: .venv\Scripts\python.exe -m xmediaplayerx"
