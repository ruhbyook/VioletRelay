from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from xmediaplayerx.services.converter import (
    conversion_progress,
    streaming_buffer_progress,
)
from xmediaplayerx.services.media import (
    MediaInfo,
    MediaStream,
    PreparationKind,
    classify_media,
    default_audio_stream_index,
    inspect_remote_media,
    is_hls_url,
    validate_media_url,
)


def info(video="h264", audio="aac", transfer=""):
    return MediaInfo(
        source="movie",
        duration_seconds=60,
        format_name="matroska",
        size=100,
        streams=[
            MediaStream(0, "video", video, 1920, 1080, transfer),
            MediaStream(1, "audio", audio),
        ],
    )


def test_compatible_mp4_is_direct():
    assert classify_media(info(), "movie.mp4").kind == PreparationKind.DIRECT


def test_compatible_mkv_is_remuxed():
    assert classify_media(info(), "movie.mkv").kind == PreparationKind.REMUX


def test_incompatible_codec_is_transcoded():
    assert classify_media(info(video="vp9", audio="opus"), "movie.webm").kind == PreparationKind.TRANSCODE


def test_subtitle_forces_transcode():
    assert classify_media(info(), "movie.mp4", "captions.srt").kind == PreparationKind.TRANSCODE


def test_selected_non_primary_audio_is_remuxed_and_codec_is_checked():
    media = info()
    media.streams.extend(
        [
            MediaStream(2, "audio", "dts", tags={"language": "nld"}),
        ]
    )
    assert classify_media(media, "movie.mp4", audio_stream=1).kind == PreparationKind.TRANSCODE
    media.streams[-1].codec_name = "aac"
    assert classify_media(media, "movie.mp4", audio_stream=1).kind == PreparationKind.REMUX


def test_default_audio_selection_uses_disposition():
    media = info()
    media.streams[1].disposition = {"default": 0}
    media.streams.append(MediaStream(2, "audio", "aac", disposition={"default": 1}))
    assert default_audio_stream_index(media) == 1


def test_direct_url_validation_and_hls():
    assert validate_media_url("https://example.test/movie.mp4") == "https://example.test/movie.mp4"
    assert is_hls_url("https://example.test/live/index.m3u8?token=secret")
    with pytest.raises(ValueError):
        validate_media_url("file:///movie.mp4")


def test_remote_inspection_uses_headers_and_range_fallback():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_HEAD(self):
            if self.path == "/range-only":
                self.send_error(405)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html" if self.path == "/page" else "video/mp4",
            )
            self.send_header("Content-Length", "123")
            self.send_header("ETag", '"revision-1"')
            self.end_headers()

        def do_GET(self):
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", "1")
            self.send_header("Content-Range", "bytes 0-0/321")
            self.send_header(
                "Last-Modified", "Wed, 29 Jul 2026 12:00:00 GMT"
            )
            self.end_headers()
            self.wfile.write(b"x")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = f"http://127.0.0.1:{server.server_port}"
        media = inspect_remote_media(root + "/movie")
        page = inspect_remote_media(root + "/page")
        ranged = inspect_remote_media(root + "/range-only")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert media.content_length == 123
    assert media.etag == '"revision-1"'
    assert media.stable
    assert page.is_webpage
    assert ranged.content_length == 321
    assert ranged.last_modified
    assert ranged.stable


def test_content_type_detects_extensionless_hls():
    assert is_hls_url(
        "https://example.test/live/channel",
        "application/vnd.apple.mpegurl; charset=utf-8",
    )


def test_probe_format_allows_extensionless_mp4_to_be_direct():
    media = info()
    media.format_name = "mov,mp4,m4a,3gp,3g2,mj2"
    assert (
        classify_media(media, "https://example.test/download?id=1").kind
        == PreparationKind.DIRECT
    )


def test_conversion_progress_has_no_fake_minimum_and_reports_eta():
    ratio, status = conversion_progress(out_seconds=5, duration_seconds=10_000, speed=0.25)
    assert ratio == pytest.approx(0.0005)
    assert "0.25×" in status
    assert "left" in status


def test_conversion_progress_handles_unknown_duration():
    assert conversion_progress(10, 0, 1) == (0.0, "Preparing cast copy")


def test_streaming_progress_reports_only_the_initial_buffer():
    ratio, status = streaming_buffer_progress(4, speed=1.25)
    assert ratio == 0.5
    assert status == "Building initial 8-second buffer · 1.25×"


def test_streaming_progress_stays_below_complete_until_manifest_is_ready():
    ratio, _status = streaming_buffer_progress(100, speed=10)
    assert ratio == 0.95
