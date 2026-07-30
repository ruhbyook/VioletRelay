# How to Cast MKV from Windows 11 to Apple TV

Violet Relay is a free and open-source Windows 11 media player that can cast
your own local MKV video to Apple TV over AirPlay. It sends the media itself
rather than mirroring the Windows desktop.

## What you need

- A Windows 11 x64 PC
- An Apple TV on the same private network
- A local, non-DRM media file you have permission to play
- Private-network access through Windows Firewall when prompted

Download the latest unsigned portable build from
[Violet Relay Releases](https://github.com/ruhbyook/VioletRelay/releases/latest),
extract the complete ZIP, and run `VioletRelay.exe`.

## Cast the MKV

1. Open or drag the MKV file into Violet Relay.
2. Confirm that the intended audio track is selected under **CC**.
3. If you want captions on the television, select the embedded subtitle or add
   an external subtitle file under **CC** before starting the cast.
4. Open **AirPlay**, select the Apple TV, and complete any pairing PIN prompts.
5. Press **Cast** beside the paired receiver.

Use **Stop casting** to end television playback. Use **Continue here** to stop
the Apple TV and resume on the PC at the last confirmed position.

## Does Violet Relay convert the whole MKV first?

Usually not. An MKV is a container, so the required preparation depends on the
video, audio, and subtitle streams inside it:

- Compatible H.264 or HEVC can normally be copied into a short rolling HLS
  buffer without re-encoding the entire movie.
- Incompatible video, audio, HDR, or image-based subtitles may require
  conversion.
- When conversion is needed, Violet Relay tries NVIDIA NVENC, AMD AMF, Intel
  Quick Sync, and finally CPU encoding.
- A selected subtitle is built into the outgoing video so it appears reliably
  on Apple TV.

The AirPlay panel reports preparation progress. Temporary work can be cancelled,
and completed compatibility copies are managed by the local cache.

## If the Apple TV keeps loading

- Confirm that both devices are on the same private LAN rather than an isolated
  guest network.
- Allow Violet Relay through Windows Firewall on private networks.
- Keep the portable folder intact; do not run only the executable from inside
  the ZIP.
- Stop and retry the cast after the first subtitle buffer is ready.
- Check **Settings and About -> Open diagnostic log folder** for a specific
  connection or conversion error.

Violet Relay supports direct media playback, not DRM services, browser capture,
YouTube extraction, or desktop mirroring. AirPlay support is unofficial and
based on the reverse-engineered `pyatv` project.

[Return to the Violet Relay README](../../README.md).
