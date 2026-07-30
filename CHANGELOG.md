# Changelog

## 0.5.3 - 2026-07-30

- Replaced font-based toolbar and transport glyphs with normalized vector
  geometry so the visible icon strokes, rather than invisible font metrics,
  are centered inside each control.
- Centered Open, URL, and AirPlay icon-label groups as a unit and snapped their
  vertical placement to whole device-independent pixels.
- Added a vector captions icon and accessible names for icon-only controls.
- Verified active-player renders at 100%, 125%, 150%, and 200% Windows scaling.

## 0.5.2 - 2026-07-30

- Centered toolbar and transport glyphs against the complete circular button
  bounds instead of Qt Material's inherited padded content area.
- Replaced the header's mixed Unicode symbols with consistently sized Segoe
  Fluent Icons for Up Next, support, and application information.
- Added a regression check for full-bounds icon-button alignment.

## 0.5.1 - 2026-07-30

- Rebuilt the ReelFerry **R** as a clean geometric silhouette that remains
  recognizable at Windows taskbar and file-icon sizes.
- Reduced the glow, simplified the play symbol, and removed the broken-looking
  bowl produced by the original stroked construction.
- Added dedicated, cache-busted GitHub logo artwork and a branded social
  preview image.

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
