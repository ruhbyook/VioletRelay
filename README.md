# ReelFerry

<p align="center">
  <img src="src/reelferry/qml/assets/reelferry-icon.png" width="112" alt="ReelFerry icon">
</p>

<p align="center"><strong>Play here. Watch there.</strong></p>

[![Tests](https://github.com/ruhbyook/ReelFerry/actions/workflows/ci.yml/badge.svg)](https://github.com/ruhbyook/ReelFerry/actions/workflows/ci.yml)
[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-7C5CFF)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/ruhbyook/ReelFerry?include_prereleases)](https://github.com/ruhbyook/ReelFerry/releases/latest)

ReelFerry is a cinematic Windows 11 media player that plays local audio and
video files and direct media URLs, maintains a session queue, remembers local
playback positions, renders SRT subtitles, and casts media to Apple TV using
AirPlay.

This is an unofficial beta. Its AirPlay support is built on the reverse-engineered
`pyatv` project rather than an Apple-provided Windows SDK. It casts media playback;
it does not mirror the Windows desktop and cannot play DRM-protected streaming
services. ReelFerry is not affiliated with, endorsed by, or certified by Apple.

## Requirements

- Windows 11 x64
- An Apple TV on the same private network
- Windows network discovery enabled

Python is not required for the portable release.

## Download

Download the latest ZIP from
[GitHub Releases](https://github.com/ruhbyook/ReelFerry/releases/latest),
extract the complete folder, and run `ReelFerry.exe`.

The first public beta is unsigned, so Windows may show **Windows protected your
PC**. Verify the ZIP against the published `SHA256SUMS.txt`, then use **More
info → Run anyway** only when it came from this repository.

The public ZIP does not redistribute FFmpeg. When casting or conversion needs
the optional media tools, ReelFerry explains the 105 MB upstream download
and starts it only after you choose **Install**. The archive and both
executables are SHA-256 verified before use.

## Upgrading from xMediaPlayerx

ReelFerry 0.5.0 is the renamed continuation of xMediaPlayerx. On first launch,
it moves the existing `%LOCALAPPDATA%\xMediaPlayerx` data into
`%LOCALAPPDATA%\ReelFerry` without duplicating large prepared-cast files. This
preserves settings, playback positions, Apple TV pairing credentials, installed
media tools, cached conversions, and logs.

Windows **Open with** and Default Apps registration is upgraded automatically.
ReelFerry removes duplicate old-name entries but retains a small compatibility
ProgID, so file types already assigned to `xMediaPlayerx.Video` continue opening
in `ReelFerry.exe`. Choosing **Remove Windows file integration** removes both
the new registration and that compatibility entry.

## Development setup

Install Python 3.13, open PowerShell in the repository, and run:

```powershell
.\scripts\bootstrap.ps1
.\scripts\run.ps1
```

The bootstrap creates `.venv`, installs the locked application dependencies, downloads the FFmpeg 8.1.2 release essentials ZIP from the Windows provider linked by ffmpeg.org, verifies its published SHA-256, and places `ffmpeg.exe` and `ffprobe.exe` under `vendor/ffmpeg/bin`.

If Windows Firewall prompts when casting a local file, allow ReelFerry/Python on private networks. Apple TV must be able to reach the temporary HTTP server created on the PC.

## Usage

- The player uses a purpose-built Windows icon and a compact Fluent-style
  transport bar whose primary and secondary actions remain clear at small
  window sizes.
- Public builds can install the pinned FFmpeg media tools directly from the
  upstream provider after explicit confirmation. Settings shows whether the
  verified tools are available.
- Open or drag local audio/video into the player, or use **URL** for a direct
  MP4, MOV, or HLS URL. Remote URLs are checked off the UI thread before Qt
  opens them. HTML pages are rejected explicitly, while extensionless HLS and
  MP4 endpoints are recognized by their response metadata and media probe.
- Local-media positions are saved atomically every 15 seconds and on pause,
  stop, file changes, casting updates, and shutdown. Reopening an unfinished
  item offers **Resume** or **Start over**. A lightweight content identity keeps
  the position across renames while preventing a replacement file at the same
  path from inheriting it. Up to 500 positions are retained for two years;
  natural completion removes the saved position.
- Add external SRT captions with the **CC** button.
- Open **CC** to choose among embedded audio and subtitle tracks. Text tracks
  such as ASS/SSA render locally; image subtitles such as PGS are burned into a
  compatibility copy after confirmation.
- External SRT renders immediately. ASS, SSA, WebVTT, SUP, and VobSub/IDX files
  can be converted and burned in when required.
- Open **AirPlay**, scan, and pair the Apple TV. AirPlay and Companion can each request a PIN once.
- Select **Cast**. Compatible files start directly. Selected subtitles are burned
  into a paced H.264/AAC HLS stream with hardware acceleration, so playback can
  begin after a short buffer instead of waiting for a full-movie conversion.
  Compatible H.264/HEVC MKV and AVI files are stream-copied straight into that
  short HLS buffer, avoiding a complete intermediate MP4. Other incompatible
  files are converted to a cached 1080p copy when live conversion is unavailable.
- Local files are delivered as temporary fragmented HLS without another
  encode. This avoids Apple TV's monolithic-MP4 probe failure while preserving
  prepared conversions in the cache for later casts. Stream-copy output is
  paced slightly ahead of playback so tvOS sees a stable rolling live edge
  instead of trying to prefetch an entire movie at once.
- A finite remote file is cached for conversion only when its server supplies
  a verified size plus an ETag or Last-Modified revision. These values are part
  of the cache key, preventing a changed file at the same URL from reusing a
  stale prepared copy. Direct compatible URLs and live HLS do not require a
  download or conversion cache.
- Conversion probes the installed driver and uses NVIDIA NVENC, AMD AMF, or
  Intel Quick Sync hardware acceleration in that order when available. If a
  GPU rejects the source, the app automatically tries the next accelerator
  and finally the CPU compatibility encoder.
- On NVIDIA systems, text-subtitle streaming decodes and resizes supported
  H.264, HEVC, and AV1 video on the GPU before subtitle rendering and HDR
  tone-mapping. This keeps demanding 4K HDR casts safely ahead of playback
  throughout the movie; unsupported CUDA inputs automatically retry the
  compatible filter path.
- Incompatible HDR sources can be prepared as a fast 10-bit HEVC HLS stream
  through NVIDIA, AMD, or Intel hardware. Hardware HLS is paced just ahead of
  playback and uses short, forced-IDR segments so Apple TV cannot chase a
  rapidly advancing live edge. If that path is unavailable, the app safely
  falls back to the cached 1080p SDR conversion.
- The selected audio/subtitle tracks are preserved when remuxing or casting.
- A cast is not labeled **Playing** until Apple TV reports playback and, for
  PC-hosted media, requests actual video bytes. A receiver that only accepts the
  queue command now produces a specific network/playlist error instead of a
  false success screen.
- tvOS URL sessions that finish in a paused final-frame state are normalized to
  natural completion so the session queue advances. An explicit user pause is
  kept distinct and never advances the queue.
- Push metadata is used when Apple TV exposes it, with one-second polling as a
  fallback. Receiver volume appears only when the active Apple TV output reports
  that it supports setting volume.
- Generated HLS casts use the full movie timeline. Seeking restarts the temporary
  producer at the requested absolute position after a short buffer, and burned
  subtitles retain their original movie timestamps after starting or seeking
  beyond zero.
- If Qt cannot play a local codec, the app offers a cancellable local
  compatibility conversion and resumes from the previous position.
- The portable Windows build registers itself per-user as an available handler
  on first launch, so supported movie files offer ReelFerry under **Open
  with** without changing any existing defaults. Registration is automatically
  repaired if the portable folder moves.
- Open **Settings and About** and choose **Make ReelFerry a default player**
  to open ReelFerry's Windows Default Apps page. Windows keeps control of
  the actual choice and requires your confirmation.
- **Remove Windows file integration** removes the portable app's Open with and
  Default Apps registry entries before deleting or moving the application.
- Double-clicked/command-line files open immediately. If the portable folder is
  moved later, the same panel detects the stale executable path and offers to
  repair it.
- Use **Continue here** to stop Apple TV and resume locally at the last known position.
- If the network drops unexpectedly, local playback stays paused at the last
  confirmed position and the app offers **Retry casting** or **Continue here**.
- The last successfully selected Apple TV is remembered and shown first on the
  next scan. **Settings and About** exposes the prepared-copy cache limit,
  cache cleanup, and the diagnostic log folder.

Pairing data, settings, playback history, cache files, and redacted logs live
below `%LOCALAPPDATA%\ReelFerry` (the exact cache/config split follows
Windows platform conventions). Playback history is local to the Windows user
and is never sent over the network. Pairing credentials are encrypted with
Windows DPAPI for the current user; moving that file to another Windows account
or PC requires pairing again. If pairing data is corrupt or belongs to another
account, it is preserved with an `.unreadable-*` suffix and the app starts
unpaired so recovery does not block local playback.

Network, conversion, settings, and Windows-integration failures are contained at
their service boundary and shown in the interface with non-empty, credential-
redacted messages. Failed or cancelled conversions remove partial files; failed
cast startup and shutdown paths also close Apple TV connections, local HTTP
servers, hardware encoders, and worker threads before returning control.

## Test and package

```powershell
.\scripts\test.ps1
.\scripts\generate_test_fixtures.ps1
.\scripts\build.ps1
```

The portable build is produced at `dist\ReelFerry\ReelFerry.exe`. It is
currently unsigned and intended for local use and beta testing. See
[`RELEASING.md`](RELEASING.md) for the guarded release archive process.
The fixture script creates short direct, remux, transcode, HDR, embedded/external
subtitle, Unicode-path, and malformed-media samples under
`build\test-fixtures`. `test.ps1` also runs those fixtures through the real
bundled FFmpeg/ffprobe binaries; use `-SkipMediaIntegration` only when that
separate integration pass is intentionally unavailable.

## Physical Apple TV checklist

Automated tests mock the protocol boundary. Before treating a build as verified, test these on the real device:

1. Discovery, AirPlay pairing, Companion pairing, and credential reuse after restart.
2. Direct H.264/AAC MP4 and a public HLS stream.
3. MKV stream-copy startup, incompatible-codec transcoding, and SRT burn-in.
4. Hardware conversion on each GPU vendor intended for the release, plus the
   forced CPU fallback. GPU paths require a current vendor graphics driver.
5. Pause, resume, seek, stop, natural queue advancement, and Continue Locally.
   On the tvOS 26.5 reference receiver, the automated 20-second hardware smoke
   test must show position advancement and a natural `ended` state.
6. Wi-Fi interruption, Apple TV sleep/wake, a blocked firewall, and app shutdown during conversion.

## Current boundaries

- Direct, unauthenticated HTTP/HTTPS media URLs only.
- No YouTube page extraction, browser capture, DRM, AirPlay mirroring, updater, telemetry, or persistent media library.
- Compatible 4K/HDR may be passed through. Incompatible sources are converted to a reliable 1080p SDR fallback.

## tvOS 26 compatibility note

`pyatv`'s legacy `/play` URL path has a confirmed regression on Apple TV 4K devices
running tvOS 26.x. ReelFerry uses the current AirPlay 2 PTP session and
`insertPlayQueueItem` command used by Apple senders instead. This path was verified
on a physical Apple TV 4K running tvOS 26.5 with direct URLs and PC-hosted local
files. VLC for Apple TV remains an automatic emergency fallback if modern session
setup fails. Earlier tvOS releases continue to use `pyatv`'s direct AirPlay path.

## Support development

Every feature is free and remains available without payment. If ReelFerry
is useful to you, optional crypto tips can support hardware testing and future
development:

| Asset | Network | Public receiving address |
| --- | --- | --- |
| BTC | Bitcoin | `bc1q4udt9zp44v23c3geph6tq5h5a659xa0qqph2es` |
| ETH or USDC | Ethereum Mainnet only; USDC must be ERC-20 | `0xAd53452fB8ae492a96154D12aa671D3331AA6680` |

The in-app heart button displays offline QR codes and copies these exact public
addresses. It never connects a wallet or requests a seed phrase, private key,
account, or personal information. Check the asset and network before sending:
crypto transfers are irreversible. Tips are optional, do not unlock features,
and are not represented as tax-deductible charitable donations.

## License

ReelFerry is free software licensed under GPL-3.0-or-later. All functionality
is available without payment. Tips do not change the license.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
[FFMPEG_SOURCE.md](FFMPEG_SOURCE.md) before redistributing a build. Public
ReelFerry packages intentionally acquire FFmpeg directly from its provider
after user consent rather than redistributing that static binary. Developer or
private builds that bundle it remain subject to its GPLv3 corresponding-source
requirements.

See also [Privacy](PRIVACY.md), [Security](SECURITY.md),
[Code signing policy](CODE_SIGNING_POLICY.md),
[Contributing](CONTRIBUTING.md), and [Changelog](CHANGELOG.md).

AirPlay and Apple TV are trademarks of Apple Inc. ReelFerry uses these names
only to describe compatibility.

Copyright © 2026 ReelFerry contributors.
