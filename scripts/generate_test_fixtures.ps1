param(
    [string]$OutputDirectory = "build\test-fixtures"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Ffmpeg = Join-Path $Root "vendor\ffmpeg\bin\ffmpeg.exe"
$Ffprobe = Join-Path $Root "vendor\ffmpeg\bin\ffprobe.exe"
if (-not (Test-Path -LiteralPath $Ffmpeg -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Ffprobe -PathType Leaf)) {
    throw "Run scripts\bootstrap.ps1 first."
}

$Output = [IO.Path]::GetFullPath((Join-Path $Root $OutputDirectory))
New-Item -ItemType Directory -Force -Path $Output | Out-Null

function Invoke-Ffmpeg {
    param([string[]]$Arguments)
    & $Ffmpeg -hide_banner -loglevel error -y @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "FFmpeg fixture generation failed: $($Arguments -join ' ')"
    }
}

$Direct = Join-Path $Output "h264-aac.mp4"
Invoke-Ffmpeg @(
    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
    "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
    "-t", "3", "-shortest",
    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
    $Direct
)

Invoke-Ffmpeg @(
    "-i", $Direct, "-map", "0", "-c", "copy",
    (Join-Path $Output "h264-aac-remux.mkv")
)

Invoke-Ffmpeg @(
    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
    "-t", "3", "-shortest", "-c:v", "mpeg4", "-q:v", "4",
    "-c:a", "mp2", "-b:a", "192k",
    (Join-Path $Output "unsupported-codecs.avi")
)

Invoke-Ffmpeg @(
    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
    "-t", "2", "-vf", "format=yuv420p10le",
    "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
    "-color_primaries", "bt2020", "-color_trc", "smpte2084",
    "-colorspace", "bt2020nc", "-an",
    (Join-Path $Output "hdr10-hevc.mkv")
)

$ExternalSubtitle = Join-Path $Output "external.srt"
$UnicodeCaption = "Unicode path check: caf$([char]0x00E9) " +
    "$([char]0x65E5)$([char]0x672C)$([char]0x8A9E)"
Set-Content -LiteralPath $ExternalSubtitle -Encoding utf8 -Value @(
    "1",
    "00:00:00,300 --> 00:00:01,500",
    "Violet Relay external subtitle",
    "",
    "2",
    "00:00:01,700 --> 00:00:02,800",
    $UnicodeCaption,
    ""
)

Invoke-Ffmpeg @(
    "-i", $Direct, "-i", $ExternalSubtitle,
    "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt",
    "-metadata:s:s:0", "language=eng",
    (Join-Path $Output "embedded-subtitle.mkv")
)

$UnicodeSuffix = "$([char]0x65E5)$([char]0x672C)$([char]0x8A9E)"
$UnicodeDirectory = Join-Path $Output ("unicode path " + $UnicodeSuffix)
New-Item -ItemType Directory -Force -Path $UnicodeDirectory | Out-Null
Copy-Item -LiteralPath $Direct -Destination (
    Join-Path $UnicodeDirectory ("movie caf" + [char]0x00E9 + " with spaces.mp4")
) -Force

[IO.File]::WriteAllBytes(
    (Join-Path $Output "malformed-media.mp4"),
    [byte[]](0x00, 0x01, 0x02, 0x03, 0x04)
)

Get-ChildItem -LiteralPath $Output -File |
    Where-Object { $_.Name -ne "malformed-media.mp4" -and $_.Extension -ne ".srt" } |
    ForEach-Object {
        & $Ffprobe -v error -show_entries format=format_name,duration -of default=nw=1 $_.FullName
        if ($LASTEXITCODE -ne 0) {
            throw "Generated fixture could not be probed: $($_.FullName)"
        }
    }

Write-Host "Synthetic media fixtures created at $Output" -ForegroundColor Green
