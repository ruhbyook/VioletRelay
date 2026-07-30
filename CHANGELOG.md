# Changelog

## 0.6.3 - 2026-07-30

- Added an AirPlay-panel reminder to select subtitles with **CC** before
  starting a cast.
- Documented that changing the subtitle during an active cast requires stopping,
  choosing the new track, and casting again.

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
