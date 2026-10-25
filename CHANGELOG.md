# Changelog

## 0.7.2 - 2026-10-25

- Updated the pinned network, certificate, media-tag, image, and build packages
  to resolve the dependency advisories that blocked CI security checks.
- Updated Qt/PySide6 to 6.12.0, platformdirs to 4.13.5, and Hatchling to 1.32.4.
- Updated the checkout, Python setup, and artifact upload GitHub Actions to v7.
- Moved the pinned build manifest to `requirements.txt` so Dependabot can update
  the versions actually installed by CI and portable builds, and grouped future
  dependency proposals to reduce duplicate notifications.
- Added installed-dependency consistency checks to both CI jobs.
- Isolated native DLL discovery from unrelated tools on the build machine's
  PATH, fixing a packaged Qt startup failure, and bounded startup smoke tests
  to 30 seconds.
- Included the Apple TV casting fix while preserving built-in AirPlay TV playback.
- Documented successful physical AirPlay playback and same-session seeking on
  a Sony BRAVIA 4K VH22 running Android TV 12, including a clean post-update
  compatibility check.

## 0.7.1 - 2026-08-07

- Updated `aiohttp` to 3.14.3 and `cryptography` to 50.0.0 to resolve all
  advisories reported by the locked-dependency security audit.

## 0.7.0 - 2026-08-07

- Added discovery and casting support for smart TVs that advertise built-in
  AirPlay video, while continuing to filter out audio-only speakers and
  soundbars.
- Added playback confirmation and estimated progress for AirPlay TV receivers
  without Apple TV metadata services, and hide remote controls those receivers
  do not expose.
- Added direct original-file playback and large-file range streaming for
  built-in TV firmware that accepts AirPlay files but not fragmented HLS.
- Fixed AirPlay progress overlays showing wall-clock time by publishing complete
  movie timelines for HDR, subtitle-burned, and stream-copy HLS playback.

## 0.6.3 - 2026-07-30

- Added an AirPlay-panel reminder to select subtitles with **CC** before
  starting a cast.
- Documented that changing the subtitle during an active cast requires stopping,
  choosing the new track, and casting again.
- Added focused MKV, subtitle, and Windows AirPlay casting guides plus clearer
  free/open-source discovery copy and package keywords.

## 0.6.2 - 2026-07-30

- Rewrote the project overview around Violet Relay's standalone local playback
  features and made it explicit that Apple TV hardware is optional.
- Split minimum local-playback requirements from the additional network
  requirements used only for casting.
- Removed obsolete pre-release rename and migration messaging from the public
  documentation and in-app About panel.
- Simplified the public release history so it starts with Violet Relay.

## 0.6.1 - 2026-07-30

- Restored the distinctive arched relay icon chosen for Violet Relay.
- Rebuilt the transparent master, Windows ICO, in-app artwork, repository logo,
  and social preview with a clean edge matte.

## 0.6.0 - 2026-07-30

Initial Violet Relay public beta.

- Added local audio/video playback, direct media URLs, a session queue,
  subtitles, fullscreen playback, playback speed, and durable resume positions.
- Added Apple TV discovery, encrypted pairing storage, modern tvOS 26 AirPlay
  playback, remote transport, reconnect handling, and Continue Locally.
- Added direct, remuxed, converted, and paced HLS casting with NVIDIA, AMD,
  Intel, and CPU encoder fallback paths.
- Added session-safe subtitle streaming and seeking, cache management,
  conversion cancellation, and diagnostic redaction.
- Added Windows Open with/default-player registration and explicit removal.
- Added the Violet Relay Windows/QML icon, centered vector controls, and
  Fluent-style interface.
- Public packages acquire pinned, hash-verified FFmpeg tools directly from the
  upstream provider after explicit user confirmation.
- Added guarded release packaging, CI verification, privacy and security
  policies, contribution guidance, issue templates, and checksums.

## Pre-release development

Earlier builds were private hardware-integration prototypes and are not
supported as public releases.
