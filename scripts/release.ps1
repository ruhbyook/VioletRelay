param(
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$Public,
    [string]$FfmpegSourceArchive,
    [string]$DistRoot = "dist"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\bootstrap.ps1 first." }

if ($Public) {
    $GitStatus = & git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw "A Git checkout is required for a public source release." }
    if ($GitStatus) {
        throw "Commit all source and release metadata before making a public build. The working tree is not clean."
    }
}
if ($FfmpegSourceArchive -and -not (Test-Path -LiteralPath $FfmpegSourceArchive -PathType Leaf)) {
    throw "FFmpeg source archive not found: $FfmpegSourceArchive"
}

if (-not $SkipTests) {
    & "scripts\test.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
}
if (-not $SkipBuild) {
    & "scripts\build.ps1" `
        -DistRoot $DistRoot `
        -WithoutBundledFFmpeg:$Public
    if ($LASTEXITCODE -ne 0) { throw "Build failed." }
}
if (-not (Test-Path (Join-Path $DistRoot "ReelFerry\ReelFerry.exe"))) {
    throw "Portable build is missing. Run scripts\build.ps1."
}

$Version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
$ReleaseDir = Join-Path $Root "release"
New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
$Suffix = if ($Public) { "" } else { "-local-beta" }
$ZipName = "ReelFerry-$Version-windows-x64$Suffix.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
$ZipCreated = $false
for ($Attempt = 1; $Attempt -le 5; $Attempt++) {
    try {
        Compress-Archive `
            -Path (Join-Path $DistRoot "ReelFerry") `
            -DestinationPath $ZipPath `
            -CompressionLevel Optimal `
            -Force `
            -ErrorAction Stop
        $ZipCreated = $true
        break
    }
    catch {
        Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
        if ($Attempt -eq 5) { throw }
        Write-Warning "Portable files are still being released by Windows; retrying archive creation ($Attempt/5)."
        Start-Sleep -Seconds 2
    }
}
if (-not $ZipCreated) { throw "Portable archive creation failed." }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$Archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    $Entries = @($Archive.Entries)
    $RequiredArchiveEntries = @(
        "ReelFerry\ReelFerry.exe",
        "ReelFerry\LICENSE",
        "ReelFerry\THIRD_PARTY_NOTICES.md",
        "ReelFerry\FFMPEG_SOURCE.md"
    )
    if (-not $Public) {
        $RequiredArchiveEntries += @(
            "ReelFerry\_internal\vendor\ffmpeg\bin\ffmpeg.exe",
            "ReelFerry\_internal\vendor\ffmpeg\bin\ffprobe.exe"
        )
    }
    $Names = @($Entries | ForEach-Object { $_.FullName })
    $MissingEntries = @($RequiredArchiveEntries | Where-Object {
        $_ -notin $Names
    })
    if ($MissingEntries.Count -gt 0) {
        throw "Release archive is incomplete. Missing: $($MissingEntries -join ', ')"
    }
    if ($Public) {
        $BundledTools = @($Names | Where-Object {
            $_ -like "*\vendor\ffmpeg\bin\ffmpeg.exe" -or
            $_ -like "*\vendor\ffmpeg\bin\ffprobe.exe"
        })
        if ($BundledTools.Count -gt 0) {
            throw "Public releases must acquire FFmpeg directly after user consent; bundled tools were found."
        }
    }

    $ExecutableEntry = $Entries | Where-Object {
        $_.FullName -eq "ReelFerry\ReelFerry.exe"
    } | Select-Object -First 1
    $Hasher = [Security.Cryptography.SHA256]::Create()
    $Stream = $ExecutableEntry.Open()
    try {
        $ArchiveExecutableHash = [BitConverter]::ToString(
            $Hasher.ComputeHash($Stream)
        ).Replace("-", "")
    }
    finally {
        $Stream.Dispose()
        $Hasher.Dispose()
    }
    $BuiltExecutableHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath (
            Join-Path $DistRoot "ReelFerry\ReelFerry.exe"
        )
    ).Hash
    if ($ArchiveExecutableHash -ne $BuiltExecutableHash) {
        throw "Archived executable does not match the verified portable build."
    }
}
finally {
    $Archive.Dispose()
}

$Artifacts = @($ZipPath)
if ($Public) {
    $SourceZip = Join-Path $ReleaseDir "ReelFerry-$Version-source.zip"
    Remove-Item -LiteralPath $SourceZip -Force -ErrorAction SilentlyContinue
    & git archive --format=zip --output=$SourceZip HEAD
    if ($LASTEXITCODE -ne 0) { throw "Application source archive creation failed." }
    $Artifacts += $SourceZip
}
if ($FfmpegSourceArchive) {
    $SourceTarget = Join-Path $ReleaseDir (Split-Path -Leaf $FfmpegSourceArchive)
    Copy-Item -LiteralPath $FfmpegSourceArchive -Destination $SourceTarget -Force
    $Artifacts += $SourceTarget
}
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md, FFMPEG_SOURCE.md -Destination $ReleaseDir -Force
$Artifacts += @(
    (Join-Path $ReleaseDir "LICENSE"),
    (Join-Path $ReleaseDir "THIRD_PARTY_NOTICES.md"),
    (Join-Path $ReleaseDir "FFMPEG_SOURCE.md")
)

$ChecksumPath = Join-Path $ReleaseDir "SHA256SUMS.txt"
$Lines = foreach ($Artifact in $Artifacts) {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact).Hash.ToLowerInvariant()
    "$Hash  $(Split-Path -Leaf $Artifact)"
}
Set-Content -LiteralPath $ChecksumPath -Value $Lines -Encoding utf8

Write-Host "Release package created at $ZipPath" -ForegroundColor Green
if (-not $Public) {
    Write-Warning "This is labeled local-beta and is not a complete public release because matching FFmpeg source was not supplied."
}
