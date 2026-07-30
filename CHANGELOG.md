# Changelog

## 0.5.0 - 2026-07-30

- Renamed the application, Python package, executable, portable folder, release
  artifacts, Windows registration, diagnostics, documentation, and AirPlay
  client identity from xMediaPlayerx to **ReelFerry**.
- Added a new ReelFerry application icon and the tagline
  **Play here. Watch there.**
- Added a one-time, non-destructive migration for settings, playback history,
  encrypted Apple TV credentials, installed FFmpeg tools, logs, and prepared
  cast cache under `%LOCALAPPDATA%\ReelFerry`.
- Added Windows registry migration that removes duplicate old-name surfaces
  while retaining a compatibility ProgID for file types already assigned to
  the pre-rename application.
- Isolated packaged smoke tests from real user data and Windows file
  associations.

## 0.4.18 - 2026-07-30

- Added an optional, offline Support development dialog with explicit Bitcoin
  and Ethereum-mainnet network labels.
- Added bundled QR images and guarded clipboard actions for the canonical BTC
  and Ethereum/USDC public receiving addresses.
- Added GitHub funding metadata plus donation-address integrity, privacy, and
  release guidance. Tips remain optional and never unlock functionality.

## 0.4.17 - 2026-07-29

First public beta.

- Added local audio/video playback, direct media URLs, a session queue,
  subtitles, fullscreen playback, playback speed, and durable resume positions.
- Added Apple TV discovery, encrypted pairing storage, modern tvOS 26 AirPlay
  playback, remote transport, reconnect handling, and Continue Locally.
- Added direct, remuxed, converted, and paced HLS casting with NVIDIA, AMD,
  Intel, and CPU encoder fallback paths.
- Added session-safe subtitle streaming and seeking, cache management,
  conversion cancellation, and diagnostic redaction.
- Added Windows Open with/default-player registration and explicit removal.
- Added branded Windows/QML icons and redesigned Fluent-style controls.
- Public packages no longer redistribute FFmpeg. Users may install the pinned,
  hash-verified tools directly from the upstream provider through an explicit
  first-run prompt.
- Added public release verification, CI packaging, privacy/security policies,
  contribution guidance, issue templates, and checksums.

## Earlier 0.4.x builds

Earlier builds were private hardware-integration prototypes and are not
supported as public releases.
