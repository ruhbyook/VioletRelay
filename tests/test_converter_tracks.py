from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
import violetrelay.services.converter as converter_module
from violetrelay.services.cache import CastCache
from violetrelay.services.converter import EncoderBackend, MediaPreparer
from violetrelay.services.media import (
    MediaInfo,
    MediaStream,
    PreparationKind,
    RemoteMediaIdentity,
)


class FakeLocator:
    def require(self):
        return Path("ffmpeg.exe"), Path("ffprobe.exe")


class FakeProbe:
    def __init__(self, info):
        self.info = info

    def probe(self, _source):
        return self.info


def media_with_subtitle(codec: str) -> MediaInfo:
    return MediaInfo(
        source="movie.mkv",
        duration_seconds=10,
        format_name="matroska",
        size=100,
        streams=[
            MediaStream(0, "video", "h264", 1920, 1080),
            MediaStream(1, "audio", "aac", tags={"language": "eng"}),
            MediaStream(2, "audio", "aac", tags={"language": "nld"}),
            MediaStream(3, "subtitle", codec, tags={"language": "eng"}),
        ],
    )


def test_bitmap_subtitle_uses_overlay_graph(tmp_path):
    info = media_with_subtitle("hdmv_pgs_subtitle")
    preparer = MediaPreparer(FakeLocator(), FakeProbe(info), CastCache(tmp_path, 1000))
    extra, arguments = preparer._filter_arguments(info, "embedded:0")
    assert extra == []
    graph = arguments[arguments.index("-filter_complex") + 1]
    assert "[0:v:0][0:s:0]overlay=" in graph
    assert arguments[-2:] == ["-map", "[vout]"]


def test_external_bitmap_subtitle_becomes_second_input(tmp_path):
    info = media_with_subtitle("ass")
    preparer = MediaPreparer(FakeLocator(), FakeProbe(info), CastCache(tmp_path, 1000))
    subtitle = str(tmp_path / "captions.sup")
    extra, arguments = preparer._filter_arguments(info, subtitle)
    assert extra == ["-i", subtitle]
    assert "[1:s:0]" in arguments[1]


def test_text_subtitle_uses_libass_filter(tmp_path):
    info = media_with_subtitle("ass")
    preparer = MediaPreparer(FakeLocator(), FakeProbe(info), CastCache(tmp_path, 1000))
    extra, arguments = preparer._filter_arguments(info, "embedded:0")
    assert extra == []
    assert "subtitles=" in arguments[-1]
    assert "si=0" in arguments[-1]


def test_seeked_text_subtitle_uses_absolute_movie_timestamps(tmp_path):
    info = media_with_subtitle("subrip")
    preparer = MediaPreparer(FakeLocator(), FakeProbe(info), CastCache(tmp_path, 1000))
    extra, arguments = preparer._filter_arguments(
        info,
        "embedded:0",
        42.25,
    )

    assert extra == []
    filters = arguments[arguments.index("-vf") + 1]
    assert filters.startswith("setpts=PTS+42.250/TB,subtitles=")
    assert "si=0,setpts=PTS-STARTPTS" in filters


def test_subtitle_filter_escapes_windows_and_filter_punctuation(tmp_path):
    path = tmp_path / "captions, [final]; it's.ass"
    escaped = MediaPreparer._escape_subtitle_path(str(path))
    assert "\\:" in escaped
    assert "\\," in escaped
    assert "\\[" in escaped and "\\]" in escaped
    assert "\\;" in escaped and "\\'" in escaped


def test_transcode_maps_selected_second_audio_track(tmp_path, monkeypatch):
    info = media_with_subtitle("ass")
    preparer = MediaPreparer(FakeLocator(), FakeProbe(info), CastCache(tmp_path, 1000))
    captured = {}

    def fake_run(command, *_args):
        captured["command"] = command

    monkeypatch.setattr(preparer, "_run", fake_run)
    preparer._run_transcode(
        "movie.mkv",
        tmp_path / "out.mp4",
        info,
        "",
        1,
        EncoderBackend.CPU,
        lambda *_args: None,
        threading.Event(),
    )
    command = captured["command"]
    audio_map = command.index("0:a:1?")
    assert command[audio_map - 1] == "-map"
    assert "libx264" in command


def test_local_fallback_is_cached_by_selected_tracks(tmp_path, monkeypatch):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    info = media_with_subtitle("ass")
    info.source = str(source)
    cache = CastCache(tmp_path / "cache", 10_000)
    preparer = MediaPreparer(FakeLocator(), FakeProbe(info), cache)
    preparer._backend_probe = {
        EncoderBackend.NVIDIA: False,
        EncoderBackend.AMD: False,
        EncoderBackend.INTEL: False,
    }
    calls = []

    def fake_transcode(_source, output, _info, subtitle, audio, *_args):
        calls.append((subtitle, audio))
        output.write_bytes(b"converted")

    monkeypatch.setattr(preparer, "_run_transcode", fake_transcode)
    first = preparer.prepare_local_fallback(
        str(source), "embedded:0", 1, cancel=threading.Event()
    )
    second = preparer.prepare_local_fallback(
        str(source), "embedded:0", 1, cancel=threading.Event()
    )
    assert first.kind == PreparationKind.TRANSCODE
    assert second.cached
    assert calls == [("embedded:0", 1)]


def test_compatible_mkv_streams_immediately_with_selected_default_audio(
    tmp_path, monkeypatch
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    info = media_with_subtitle("ass")
    info.source = str(source)
    info.audio_streams[0].disposition = {"default": 0}
    info.audio_streams[1].disposition = {"default": 1}
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    calls = []

    def fail_remux(*_args):
        raise AssertionError("a complete intermediate MP4 must not be created")

    def fake_stream(_source, kind, _cached, _info, _start, _progress, _cancel, audio):
        calls.append(audio)
        return SimpleNamespace(kind=kind, streaming=True)

    monkeypatch.setattr(preparer, "_run_remux", fail_remux)
    monkeypatch.setattr(preparer, "_local_file_stream", fake_stream)
    result = preparer.prepare(str(source), audio_stream=-1)
    assert result.kind == PreparationKind.REMUX
    assert result.streaming
    assert calls == [1]


def test_compatible_local_file_is_presented_as_copy_hls(tmp_path, monkeypatch):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"video")
    info = MediaInfo(
        source=str(source),
        duration_seconds=120,
        format_name="mov,mp4",
        size=source.stat().st_size,
        streams=[
            MediaStream(0, "video", "h264", 1920, 1080),
            MediaStream(1, "audio", "aac"),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    calls = []

    class FakeSession:
        directory = tmp_path / "stream"
        manifest = tmp_path / "stream" / "index.m3u8"
        producer_manifest = tmp_path / "stream" / "producer.m3u8"
        progress = lambda *_args: None

        def wait_until_ready(self, cancel):
            calls.append(("ready", cancel.is_set()))

        def stop(self):
            calls.append(("stop",))

        def publish_vod_segments(
            self,
            durations,
            first_real_segment,
            real_segment_start_number=None,
        ):
            calls.append(
                (
                    "publish",
                    durations,
                    first_real_segment,
                    real_segment_start_number,
                )
            )

    def fake_start(path, media_info, _progress, position, audio):
        calls.append(("start", path, media_info, position, audio))
        return FakeSession()

    monkeypatch.setattr(preparer, "_start_copy_hls", fake_start)
    monkeypatch.setattr(
        preparer,
        "_probe_copy_keyframe_start",
        lambda *_args: 16.0,
    )
    monkeypatch.setattr(
        preparer,
        "_probe_copy_hls_durations",
        lambda *_args: (5.0, 7.0, 3.0),
    )
    monkeypatch.setattr(
        preparer,
        "_probe_first_hls_video_pts",
        lambda *_args: 0.125,
    )
    result = preparer.prepare(
        str(source),
        start_position_seconds=18.5,
        cancel=threading.Event(),
    )

    assert result.streaming
    assert result.source.endswith("index.m3u8")
    assert result.start_position_seconds == 18.5
    assert result.absolute_timeline
    assert result.kind == PreparationKind.DIRECT
    assert calls[0] == ("start", source, info, 18.5, 0)
    assert calls[1] == ("ready", False)
    assert calls[2] == (
        "publish",
        (4.0, 4.0, 4.0, 3.875, 5.0, 7.0, 3.0),
        4,
        0,
    )
    assert all(call[0] != "stop" for call in calls)


def test_builtin_tv_receives_compatible_local_file_without_hls(
    tmp_path, monkeypatch
):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"video")
    info = MediaInfo(
        source=str(source),
        duration_seconds=120,
        format_name="mov,mp4",
        size=source.stat().st_size,
        streams=[
            MediaStream(0, "video", "h264", 1920, 1080),
            MediaStream(1, "audio", "aac"),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        preparer,
        "_local_file_stream",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("built-in TV must receive the MP4 file")
        ),
    )

    result = preparer.prepare(str(source), allow_hls_playback=False)

    assert result.source == str(source)
    assert result.kind == PreparationKind.DIRECT
    assert not result.streaming


def test_builtin_tv_builds_complete_mp4_for_selected_subtitles(
    tmp_path, monkeypatch
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    info = MediaInfo(
        source=str(source),
        duration_seconds=120,
        format_name="matroska",
        size=source.stat().st_size,
        streams=[
            MediaStream(
                0,
                "video",
                "av1",
                3840,
                2160,
                color_transfer="smpte2084",
            ),
            MediaStream(1, "audio", "aac"),
            MediaStream(2, "subtitle", "ass"),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        preparer,
        "_prepare_hdr_stream",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("built-in TV must not receive HLS")
        ),
    )

    def fake_transcode(_source, output, *_args):
        output.write_bytes(b"converted mp4")

    monkeypatch.setattr(preparer, "_transcode_with_fallback", fake_transcode)
    result = preparer.prepare(
        str(source),
        "embedded:0",
        allow_hls_playback=False,
    )

    assert Path(result.source).read_bytes() == b"converted mp4"
    assert result.kind == PreparationKind.TRANSCODE
    assert not result.streaming


def test_builtin_tv_streams_original_av1_hdr_file_immediately(
    tmp_path, monkeypatch
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    info = MediaInfo(
        source=str(source),
        duration_seconds=120,
        format_name="matroska",
        size=source.stat().st_size,
        streams=[
            MediaStream(
                0,
                "video",
                "av1",
                3840,
                2160,
                color_transfer="smpte2084",
            ),
            MediaStream(1, "audio", "truehd", disposition={"default": 1}),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        preparer,
        "_transcode_with_fallback",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("native built-in TV playback must start immediately")
        ),
    )

    result = preparer.prepare(str(source), allow_hls_playback=False)

    assert result.source == str(source)
    assert result.kind == PreparationKind.DIRECT
    assert not result.streaming


def test_local_file_hls_wrapper_copies_streams_without_reencoding(
    tmp_path, monkeypatch
):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"video")
    info = MediaInfo(
        source=str(source),
        duration_seconds=120,
        format_name="mov,mp4",
        size=source.stat().st_size,
        streams=[
            MediaStream(0, "video", "h264", 1920, 1080),
            MediaStream(1, "audio", "aac"),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    captured = {}

    class FakeSession:
        def __init__(
            self,
            directory,
            command,
            duration,
            _progress,
            producer_manifest_name="index.m3u8",
        ):
            captured.update(
                directory=directory,
                command=command,
                duration=duration,
                producer_manifest_name=producer_manifest_name,
            )

    monkeypatch.setattr(converter_module, "HlsSession", FakeSession)
    preparer._start_copy_hls(source, info, lambda *_args: None, 12.5)

    command = captured["command"]
    assert command[command.index("-c") + 1] == "copy"
    assert command[command.index("-hls_segment_type") + 1] == "fmp4"
    assert command[command.index("-readrate") + 1] == "1.05"
    assert command[command.index("-readrate_initial_burst") + 1] == "30"
    assert command[command.index("-readrate_catchup") + 1] == "1.5"
    assert command[command.index("-ss") + 1] == "12.500"
    assert command[-1].endswith("producer.m3u8")
    assert captured["producer_manifest_name"] == "producer.m3u8"
    assert "h264_nvenc" not in command
    assert "libx264" not in command
    assert captured["duration"] == 107.5


def test_copy_vod_timeline_uses_irregular_real_segments_and_distinct_prefix(
    tmp_path,
):
    timeline = MediaPreparer._build_copy_hls_timeline(
        12.0,
        (8.0, 5.0, 5.0),
    )
    session = object.__new__(converter_module.HlsSession)
    session.manifest = tmp_path / "index.m3u8"

    session.publish_vod_segments(
        timeline.segment_durations,
        timeline.first_real_segment,
        real_segment_start_number=0,
    )

    playlist = session.manifest.read_text(encoding="utf-8")
    assert timeline.first_real_segment == 3
    assert timeline.segment_durations == (4.0, 4.0, 4.0, 8.0, 5.0, 5.0)
    assert "#EXT-X-TARGETDURATION:8" in playlist
    assert "missing_000002.m4s" in playlist
    assert (
        '#EXT-X-DISCONTINUITY\n#EXT-X-MAP:URI="init.mp4"\n'
        "#EXTINF:8.000000,\nsegment_000000.m4s"
    ) in playlist
    assert "segment_000003.m4s" not in playlist


def test_copy_seek_seconds_truncates_and_clamps_to_duration():
    assert MediaPreparer._copy_seek_seconds(-3.0, 120.0) == 0.0
    assert MediaPreparer._copy_seek_seconds(0.0009, 120.0) == 0.0
    assert MediaPreparer._copy_seek_seconds(12.3459, 120.0) == 12.345
    assert MediaPreparer._copy_seek_seconds(120.0, 120.0) == 119.999


def test_copy_timeline_anchor_falls_back_to_full_minus_remaining_duration():
    anchor = MediaPreparer._resolve_copy_timeline_anchor(
        18.5,
        None,
        0.125,
        120.0,
        (8.0, 40.0, 56.0),
    )

    assert anchor == 16.0
    assert MediaPreparer._copy_timeline_prefix(0.0000004) == ()


def test_copy_keyframe_probe_accounts_for_format_start_time(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "shifted.mp4"
    source.write_bytes(b"video")
    info = MediaInfo(str(source), 120, "mov,mp4", 5, [])
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    captured = {}

    class Result:
        returncode = 0
        stderr = ""
        stdout = (
            '{"packets":[{"pts_time":"14.004000","flags":"K__"}],'
            '"format":{"start_time":"9.978000"}}'
        )

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return Result()

    monkeypatch.setattr(converter_module.subprocess, "run", fake_run)

    keyframe = preparer._probe_copy_keyframe_start(
        source,
        5.0,
        threading.Event(),
    )

    assert keyframe == pytest.approx(4.026)
    command = captured["command"]
    assert command[command.index("-read_intervals") + 1] == "+5.000%+#1"


def test_copy_hls_duration_probe_preserves_irregular_extinfs_and_caches(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"video")
    info = MediaInfo(
        str(source),
        120,
        "mov,mp4",
        5,
        [MediaStream(0, "video", "h264"), MediaStream(1, "audio", "aac")],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    launches = []

    class FakeProcess:
        returncode = 0

        def __init__(self, command, **_kwargs):
            launches.append(command)
            Path(command[-1]).write_text(
                "#EXTM3U\n"
                "#EXT-X-PLAYLIST-TYPE:VOD\n"
                "#EXTINF:4.046000,\nNUL\n"
                "#EXTINF:8.300000,\nNUL\n"
                "#EXTINF:1.167000,\nNUL\n"
                "#EXT-X-ENDLIST\n",
                encoding="utf-8",
            )

        def communicate(self, timeout):
            assert timeout == 0.2
            return "", ""

    monkeypatch.setattr(converter_module.subprocess, "Popen", FakeProcess)
    directory = tmp_path / "stream"
    directory.mkdir()

    first = preparer._probe_copy_hls_durations(
        source,
        info,
        12.5,
        0,
        directory,
        threading.Event(),
    )
    second = preparer._probe_copy_hls_durations(
        source,
        info,
        12.5,
        0,
        tmp_path / "unused",
        threading.Event(),
    )

    assert first == second == (4.046, 8.3, 1.167)
    assert len(launches) == 1
    command = launches[0]
    assert command[command.index("-ss") + 1] == "12.500"
    assert command[command.index("-hls_playlist_type") + 1] == "vod"
    assert command[command.index("-hls_segment_filename") + 1] == (
        "NUL" if converter_module.os.name == "nt" else converter_module.os.devnull
    )


def test_selected_subtitle_starts_streaming_transcode_instead_of_cached_conversion(
    tmp_path, monkeypatch
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    info = media_with_subtitle("subrip")
    info.source = str(source)
    info.duration_seconds = 120
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    expected = SimpleNamespace(streaming=True)
    calls = []

    def fake_prepare(
        path, media_info, subtitle, audio, position, _progress, _cancel
    ):
        calls.append((path, media_info, subtitle, audio, position))
        return expected

    monkeypatch.setattr(preparer, "_prepare_transcode_stream", fake_prepare)
    monkeypatch.setattr(
        preparer,
        "_transcode_with_fallback",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("full-file conversion should not run")
        ),
    )

    result = preparer.prepare(
        str(source),
        "embedded:0",
        start_position_seconds=17.25,
        audio_stream=1,
    )

    assert result is expected
    assert calls == [
        (str(source), info, "embedded:0", 1, 17.25),
    ]


def test_subtitle_hls_transcode_is_paced_and_burns_selected_track(
    tmp_path, monkeypatch
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    info = media_with_subtitle("subrip")
    info.source = str(source)
    info.duration_seconds = 120
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    captured = {}

    class FakeSession:
        def __init__(
            self,
            directory,
            command,
            duration,
            _progress,
            producer_manifest_name="index.m3u8",
        ):
            captured.update(
                directory=directory,
                command=command,
                duration=duration,
                producer_manifest_name=producer_manifest_name,
            )

    monkeypatch.setattr(converter_module, "HlsSession", FakeSession)
    preparer._start_transcode_hls(
        str(source),
        info,
        "embedded:0",
        lambda *_args: None,
        10.5,
        1,
        EncoderBackend.NVIDIA,
    )

    command = captured["command"]
    assert command[command.index("-readrate") + 1] == "1.05"
    assert command[command.index("-readrate_initial_burst") + 1] == "30"
    assert command[command.index("-ss") + 1] == "8.000"
    video_codecs = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "-c:v"
    ]
    assert video_codecs == ["h264_cuvid", "h264_nvenc"]
    assert command[command.index("-g") + 1] == "96"
    assert command[command.index("-hls_segment_type") + 1] == "fmp4"
    assert command[command.index("-hls_flags") + 1] == (
        "independent_segments+temp_file"
    )
    assert command[command.index("-start_number") + 1] == "2"
    assert command[-1].endswith("producer.m3u8")
    assert captured["producer_manifest_name"] == "producer.m3u8"
    assert command[command.index("-map", command.index("-vf")) + 1] == "0:a:1?"
    video_filter = command[command.index("-vf") + 1]
    assert "scale_cuda=" in video_filter
    assert "hwdownload" in video_filter
    assert "subtitles=" in video_filter
    assert "si=0" in video_filter
    assert "setpts=PTS+8.000/TB" in video_filter
    assert "setpts=PTS+10.500/TB" not in video_filter
    assert "scale=w=" not in video_filter
    assert captured["duration"] == 112


def test_external_bitmap_subtitle_hls_aligns_both_input_seeks(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    subtitle = tmp_path / "captions.sup"
    info = media_with_subtitle("ass")
    info.source = str(source)
    info.duration_seconds = 120
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    captured = {}

    class FakeSession:
        def __init__(
            self,
            _directory,
            command,
            duration,
            _progress,
            producer_manifest_name="index.m3u8",
        ):
            captured.update(
                command=command,
                duration=duration,
                producer_manifest_name=producer_manifest_name,
            )

    monkeypatch.setattr(converter_module, "HlsSession", FakeSession)
    preparer._start_transcode_hls(
        str(source),
        info,
        str(subtitle),
        lambda *_args: None,
        10.5,
        0,
        EncoderBackend.NVIDIA,
        accelerated_input=False,
    )

    command = captured["command"]
    seek_indices = [index for index, value in enumerate(command) if value == "-ss"]
    assert [command[index + 1] for index in seek_indices] == ["8.000", "8.000"]
    main_input = command.index("-i")
    subtitle_input = command.index("-i", main_input + 1)
    assert seek_indices[0] < main_input
    assert seek_indices[1] == subtitle_input - 2
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:v:0][1:s:0]overlay=" in graph
    assert command[command.index("-start_number") + 1] == "2"
    assert captured["duration"] == 112
    assert captured["producer_manifest_name"] == "producer.m3u8"


def test_extensionless_hls_content_type_bypasses_probe(tmp_path, monkeypatch):
    class RejectProbe:
        def probe(self, _source):
            raise AssertionError("HLS should not be probed or converted")

    preparer = MediaPreparer(
        FakeLocator(), RejectProbe(), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        converter_module,
        "inspect_remote_media",
        lambda source: RemoteMediaIdentity(
            source,
            0,
            content_type="application/vnd.apple.mpegurl",
        ),
    )

    result = preparer.prepare("https://example.test/live/channel")

    assert result.kind == PreparationKind.DIRECT
    assert not result.streaming


def test_remote_webpage_is_rejected_before_ffprobe(tmp_path, monkeypatch):
    class RejectProbe:
        def probe(self, _source):
            raise AssertionError("web pages should never reach FFprobe")

    preparer = MediaPreparer(
        FakeLocator(), RejectProbe(), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        converter_module,
        "inspect_remote_media",
        lambda source: RemoteMediaIdentity(
            source,
            500,
            content_type="text/html; charset=utf-8",
            etag='"page"',
        ),
    )

    with pytest.raises(ValueError, match="web page"):
        preparer.prepare("https://example.test/watch")


def test_direct_remote_mp4_can_continue_when_head_is_blocked(
    tmp_path, monkeypatch
):
    source = "https://example.test/movie.mp4"
    info = MediaInfo(
        source=source,
        duration_seconds=30,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        size=1_000,
        streams=[
            MediaStream(0, "video", "h264", 1280, 720),
            MediaStream(1, "audio", "aac"),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        converter_module,
        "inspect_remote_media",
        lambda _value: (_ for _ in ()).throw(
            RuntimeError("HEAD and Range are blocked")
        ),
    )

    result = preparer.prepare(source)

    assert result.kind == PreparationKind.DIRECT
    assert result.source == source


def test_remote_conversion_requires_stable_http_identity(tmp_path, monkeypatch):
    source = "https://example.test/download"
    info = MediaInfo(
        source=source,
        duration_seconds=30,
        format_name="matroska",
        size=1_000,
        streams=[
            MediaStream(0, "video", "vp9", 1280, 720),
            MediaStream(1, "audio", "opus"),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        converter_module,
        "inspect_remote_media",
        lambda value: RemoteMediaIdentity(
            value,
            1_000,
            content_type="application/octet-stream",
        ),
    )

    with pytest.raises(RuntimeError, match="ETag or Last-Modified"):
        preparer.prepare(source)


def test_remote_conversion_requires_finite_duration(tmp_path, monkeypatch):
    source = "https://example.test/download"
    info = MediaInfo(
        source=source,
        duration_seconds=0,
        format_name="matroska",
        size=1_000,
        streams=[
            MediaStream(0, "video", "vp9", 1280, 720),
            MediaStream(1, "audio", "opus"),
        ],
    )
    preparer = MediaPreparer(
        FakeLocator(), FakeProbe(info), CastCache(tmp_path / "cache", 10_000)
    )
    monkeypatch.setattr(
        converter_module,
        "inspect_remote_media",
        lambda value: RemoteMediaIdentity(
            value,
            1_000,
            content_type="application/octet-stream",
            etag='"revision-1"',
        ),
    )

    with pytest.raises(RuntimeError, match="finite duration"):
        preparer.prepare(source)


def test_remote_conversion_accepts_stable_revision_identity(
    tmp_path, monkeypatch
):
    source = "https://example.test/download"
    info = MediaInfo(
        source=source,
        duration_seconds=30,
        format_name="matroska",
        size=1_000,
        streams=[
            MediaStream(0, "video", "vp9", 1280, 720),
            MediaStream(1, "audio", "opus"),
        ],
    )
    cache = CastCache(tmp_path / "cache", 10_000)
    preparer = MediaPreparer(FakeLocator(), FakeProbe(info), cache)
    monkeypatch.setattr(
        converter_module,
        "inspect_remote_media",
        lambda value: RemoteMediaIdentity(
            value,
            1_000,
            content_type="application/octet-stream",
            etag='"revision-1"',
        ),
    )

    def fake_transcode(_source, output, *_args):
        output.write_bytes(b"converted")

    monkeypatch.setattr(preparer, "_transcode_with_fallback", fake_transcode)
    monkeypatch.setattr(
        preparer,
        "_local_file_stream",
        lambda _source, kind, *_args: SimpleNamespace(kind=kind),
    )

    result = preparer.prepare(source)

    assert result.kind == PreparationKind.TRANSCODE
    assert len(list(cache.directory.glob("*.mp4"))) == 1
