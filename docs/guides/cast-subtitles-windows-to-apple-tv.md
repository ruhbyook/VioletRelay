# How to Cast Video with Subtitles from Windows to Apple TV

Violet Relay can cast local video with an embedded subtitle track or an
external subtitle file from Windows 11 to Apple TV. Select the captions before
you start casting so Violet Relay can build them into the outgoing stream.

Download the latest unsigned portable beta from
[Violet Relay Releases](https://github.com/ruhbyook/VioletRelay/releases/latest).

## Select subtitles before casting

1. Open the video in Violet Relay.
2. Press **CC**.
3. Choose the intended embedded subtitle track, or choose **Add subtitle file**
   and select the external subtitle.
4. Check the captions during local playback.
5. Open **AirPlay**, select the paired Apple TV, and press **Cast**.

The AirPlay panel includes a reminder because the subtitle choice is fixed when
the cast begins. To change subtitles during television playback:

1. Press **Stop casting**.
2. Select the new track or file with **CC**.
3. Start the cast again.

## Supported subtitle paths

- Text subtitles such as SRT, ASS, SSA, and WebVTT can render locally.
- Embedded text tracks can be selected from the same **CC** panel as audio.
- External subtitle files can be attached to the current queue item.
- Image-based subtitles such as PGS may require a compatibility conversion.
- During Apple TV casting, the selected subtitle is burned into the temporary
  stream so receiver-side subtitle support is not required.

Burning captions means conversion may take longer than casting the same file
with subtitles turned off. Violet Relay uses supported NVIDIA, AMD, or Intel
hardware acceleration when available and falls back safely when a GPU path
cannot process the source.

## Subtitle timing

Seeking an active cast restarts the temporary producer at the requested
absolute movie position. The subtitle timeline is kept on the original movie
clock so captions remain aligned after seeking. If an external subtitle is
consistently early or late during local playback too, the subtitle file itself
was probably authored for a different cut of the video.

Violet Relay does not download subtitles or identify copyrighted media. Use
subtitle files and media you are permitted to use.

[Return to the Violet Relay README](../../README.md).
