param(
    [string]$DistRoot = "dist",
    [switch]$BundledFFmpeg,
    [switch]$Smoke
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ResolvedDistRoot = if ([IO.Path]::IsPathRooted($DistRoot)) {
    [IO.Path]::GetFullPath($DistRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $Root $DistRoot))
}
$Package = Join-Path $ResolvedDistRoot "xMediaPlayerx"
$Executable = Join-Path $Package "xMediaPlayerx.exe"
$Ffmpeg = Join-Path $Package "_internal\vendor\ffmpeg\bin\ffmpeg.exe"
$Ffprobe = Join-Path $Package "_internal\vendor\ffmpeg\bin\ffprobe.exe"
$Required = @(
    $Executable,
    (Join-Path $Package "_internal\qml\Main.qml"),
    (Join-Path $Package "_internal\qml\assets\xmediaplayerx-icon.png"),
    (Join-Path $Package "_internal\qml\assets\support-bitcoin.png"),
    (Join-Path $Package "_internal\qml\assets\support-ethereum.png"),
    (Join-Path $Package "LICENSE"),
    (Join-Path $Package "THIRD_PARTY_NOTICES.md"),
    (Join-Path $Package "FFMPEG_SOURCE.md"),
    (Join-Path $Package "licenses\Python\DEPENDENCY_LICENSES.json")
)
if ($BundledFFmpeg) {
    $Required += @(
        $Ffmpeg,
        $Ffprobe,
        (Join-Path $Package "licenses\FFmpeg\LICENSE.txt")
    )
}
$Missing = @($Required | Where-Object {
    -not (Test-Path -LiteralPath $_ -PathType Leaf)
})
if ($Missing.Count -gt 0) {
    throw "Portable package is incomplete. Missing: $($Missing -join ', ')"
}

if ($BundledFFmpeg) {
    $ExpectedFfmpeg = "1326dde4c84ff1f96fe6b8916c5bed29e163e9b5dccf995f6f3db069d143ec5e"
    $ExpectedFfprobe = "b49ccc7c6547b141ad5a2f6ec69cc04323d7133d7704d70b331b904c63eecb07"
    $ActualFfmpeg = (Get-FileHash -Algorithm SHA256 -LiteralPath $Ffmpeg).Hash.ToLowerInvariant()
    $ActualFfprobe = (Get-FileHash -Algorithm SHA256 -LiteralPath $Ffprobe).Hash.ToLowerInvariant()
    if ($ActualFfmpeg -ne $ExpectedFfmpeg) {
        throw "Packaged ffmpeg.exe does not match the pinned binary."
    }
    if ($ActualFfprobe -ne $ExpectedFfprobe) {
        throw "Packaged ffprobe.exe does not match the pinned binary."
    }
}
elseif ((Test-Path -LiteralPath $Ffmpeg) -or (Test-Path -LiteralPath $Ffprobe)) {
    throw "The public package unexpectedly contains FFmpeg executables."
}

if ($Smoke) {
    $PreviousPlatform = $env:QT_QPA_PLATFORM
    $PreviousSmoke = $env:XMEDIAPLAYERX_SMOKE_TEST
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        $env:XMEDIAPLAYERX_SMOKE_TEST = "1"
        $Process = Start-Process -FilePath $Executable -PassThru -Wait
        if ($Process.ExitCode -ne 0) {
            throw "Packaged application exited with code $($Process.ExitCode)."
        }
    }
    finally {
        $env:QT_QPA_PLATFORM = $PreviousPlatform
        $env:XMEDIAPLAYERX_SMOKE_TEST = $PreviousSmoke
    }
}

Write-Host "Portable package verified at $Package" -ForegroundColor Green
