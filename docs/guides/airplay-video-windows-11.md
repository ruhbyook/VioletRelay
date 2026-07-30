# How to AirPlay Video from Windows 11 to Apple TV

Violet Relay provides free, open-source AirPlay video casting from a Windows 11
PC to Apple TV. It plays local audio and video on Windows even without an Apple
TV; casting is an optional feature.

Download the latest unsigned portable build from
[Violet Relay Releases](https://github.com/ruhbyook/VioletRelay/releases/latest).

## Media casting, not screen mirroring

Violet Relay sends a video URL or a temporary local media stream to Apple TV.
The Apple TV performs playback while Violet Relay provides play, pause, seek,
stop, progress, reconnect, and continue-locally controls.

This is different from duplicating the entire Windows desktop. It avoids the
continuous screen capture used by mirroring, but it also means Violet Relay
cannot cast arbitrary applications, browser tabs, DRM streaming services, or
protected Apple TV+ content.

## Cast a local video

1. Extract the complete Violet Relay portable ZIP and run
   `VioletRelay.exe`.
2. Open or drag in a local video.
3. Choose the intended audio and subtitle tracks with **CC**.
4. Put the PC and Apple TV on the same private network.
5. Open **AirPlay** and scan for receivers.
6. Pair AirPlay and Companion if either protocol requests a PIN.
7. Press **Cast** beside the Apple TV.

Compatible media starts through a short temporary HLS buffer. Other codecs,
HDR profiles, or subtitle choices can trigger hardware-accelerated conversion.
The optional FFmpeg tools are downloaded only after you approve the verified
upstream package.

## Cast a direct media URL

Use **URL** for a direct, unauthenticated HTTP/HTTPS MP4, MOV, or HLS media URL.
A normal web page is not a media URL. Violet Relay intentionally does not
extract video from YouTube pages, streaming-service pages, or sites that require
DRM or custom authentication headers.

## Network troubleshooting

If discovery works but playback does not start:

- Allow Violet Relay through Windows Firewall on private networks.
- Avoid guest Wi-Fi or router settings that isolate wireless clients.
- Confirm the Apple TV can reach the PC's local IP address.
- Rescan after the Apple TV wakes from sleep.
- Review the redacted diagnostic log from **Settings and About**.

The integration is based on the reverse-engineered `pyatv` project and is not
provided or certified by Apple. tvOS changes can require future compatibility
updates.

[Return to the Violet Relay README](../../README.md).
