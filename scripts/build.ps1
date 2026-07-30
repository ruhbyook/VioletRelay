param(
    [string]$DistRoot = "dist",
    [switch]$WithoutBundledFFmpeg
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\bootstrap.ps1 first." }
if (-not $WithoutBundledFFmpeg -and -not (Test-Path "vendor\ffmpeg\bin\ffmpeg.exe")) {
    throw "Run scripts\bootstrap.ps1 to fetch verified FFmpeg tools."
}

$LicenseDir = "build\release-licenses"
& $Python "scripts\generate_licenses.py" $LicenseDir
if ($LASTEXITCODE -ne 0) { throw "Dependency license collection failed." }

$PyInstallerArguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--distpath", $DistRoot,
    "--name", "VioletRelay",
    "--icon", "assets\violetrelay.ico",
    "--version-file", "assets\violetrelay-version-info.txt",
    "--collect-submodules", "pyatv",
    "--add-data", "src\violetrelay\qml;qml"
)
if (-not $WithoutBundledFFmpeg) {
    $PyInstallerArguments += @(
        "--add-binary", "vendor\ffmpeg\bin\ffmpeg.exe;vendor\ffmpeg\bin",
        "--add-binary", "vendor\ffmpeg\bin\ffprobe.exe;vendor\ffmpeg\bin"
    )
}
$PyInstallerArguments += "src\violetrelay\app.py"

& $Python -m PyInstaller @PyInstallerArguments

if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$Dist = Join-Path $DistRoot "VioletRelay"
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md, FFMPEG_SOURCE.md -Destination $Dist -Force
New-Item -ItemType Directory -Force "$Dist\licenses\FFmpeg" | Out-Null
New-Item -ItemType Directory -Force "$Dist\licenses\Python" | Out-Null
if (-not $WithoutBundledFFmpeg) {
    Copy-Item "vendor\ffmpeg\LICENSE.txt" -Destination "$Dist\licenses\FFmpeg\LICENSE.txt" -Force
}
Copy-Item "$LicenseDir\*" -Destination "$Dist\licenses\Python" -Recurse -Force

& "$PSScriptRoot\verify_package.ps1" `
    -DistRoot $DistRoot `
    -BundledFFmpeg:(-not $WithoutBundledFFmpeg)
if ($LASTEXITCODE -ne 0) { throw "Portable package verification failed." }

Write-Host "Portable build created at $Dist\VioletRelay.exe" -ForegroundColor Green
