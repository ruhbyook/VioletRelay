# FFmpeg acquisition and corresponding-source information

## Public downloads

The public ReelFerry ZIP does **not** contain FFmpeg executables. On first
launch, ReelFerry explains why the optional media tools are needed and only
downloads them after the user chooses **Install**. The archive is fetched
directly from the Windows build provider linked by ffmpeg.org, not from a
ReelFerry server. The archive and both extracted executables are verified
against the SHA-256 values below before use.

This keeps the application download small, makes the upstream origin explicit,
and means ReelFerry is not redistributing that third-party static binary.

## Developer and private bundled builds

Developer builds may bundle these unmodified executables from the verified
`ffmpeg-release-essentials.zip` published by Gyan Doshi:

- FFmpeg version: `8.1.2-essentials_build-www.gyan.dev`
- Archive SHA-256: `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec`
- Pinned binary archive: <https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/ffmpeg-8.1.2-essentials_build.zip>
- `ffmpeg.exe` SHA-256: `1326dde4c84ff1f96fe6b8916c5bed29e163e9b5dccf995f6f3db069d143ec5e`
- `ffprobe.exe` SHA-256: `b49ccc7c6547b141ad5a2f6ec69cc04323d7133d7704d70b331b904c63eecb07`
- Binary provider and build sources: <https://www.gyan.dev/ffmpeg/builds/>
- FFmpeg upstream source: <https://ffmpeg.org/download.html>

The exact configure line is recorded by running:

```powershell
vendor\ffmpeg\bin\ffmpeg.exe -buildconf
```

It includes `--enable-gpl`, `--enable-version3`, `--enable-libx264`, and
`--enable-libx265`; the resulting executable is therefore GPLv3. Anyone
redistributing a release must make the complete corresponding source for this
exact binary—including enabled external libraries and build scripts—available
alongside the binary download for as long as required by GPLv3. A link to a
different FFmpeg release or only the main FFmpeg tarball is not sufficient.

Anyone who chooses to redistribute a bundled build must verify that the
provider's complete corresponding source remains available and mirror the exact
source next to the ReelFerry download. A public build created with
`scripts/release.ps1 -Public` deliberately refuses to include these executables.
