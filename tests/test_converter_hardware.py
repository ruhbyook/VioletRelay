from pathlib import Path
import threading

import pytest
import violetrelay.services.converter as converter_module

from violetrelay.services.cache import CastCache
from violetrelay.services.converter import (
    BACKEND_LABELS,
    EncoderBackend,
    HlsSession,
    MediaPreparer,
)
from violetrelay.services.media import MediaInfo, MediaStream


class FakeLocator:
    def require(self):
        return Path("ffmpeg.exe"), Path("ffprobe.exe")


class FakeProbe:
    def probe(self, _source):
        raise AssertionError("probe should not be used")


def hdr_info() -> MediaInfo:
    return MediaInfo(
        source="movie.mkv",
        duration_seconds=120,
        format_name="matroska",
        size=100,
        streams=[
            MediaStream(
                0, "video", "hevc", 3840, 2160, color_transfer="smpte2084"
            ),
            MediaStream(1, "audio", "aac"),
        ],
    )


def preparer(tmp_path) -> MediaPreparer:
    return MediaPreparer(
        FakeLocator(), FakeProbe(), CastCache(tmp_path / "cache", 10_000)
    )


@pytest.mark.parametrize(
    ("backend", "encoder"),
    [
        (EncoderBackend.NVIDIA, "h264_nvenc"),
        (EncoderBackend.AMD, "h264_amf"),
        (EncoderBackend.INTEL, "h264_qsv"),
        (EncoderBackend.CPU, "libx264"),
    ],
)
def test_standard_conversion_has_options_for_every_backend(backend, encoder):
    options = MediaPreparer._h264_video_options(backend)
    assert options[options.index("-c:v") + 1] == encoder
    assert options[options.index("-g") + 1] == "96"


def test_standard_conversion_fails_over_in_vendor_order(tmp_path, monkeypatch):
    instance = preparer(tmp_path)
    instance._backend_probe = {
        EncoderBackend.NVIDIA: True,
        EncoderBackend.AMD: True,
        EncoderBackend.INTEL: True,
    }
    attempts = []

    def fake_transcode(_source, output, _info, _subtitle, _audio, backend, *_args):
        attempts.append(backend)
        if backend in {EncoderBackend.NVIDIA, EncoderBackend.AMD}:
            raise RuntimeError("driver rejected encoder")
        output.write_bytes(b"converted")

    monkeypatch.setattr(instance, "_run_transcode", fake_transcode)
    result = instance._transcode_with_fallback(
        "movie.mkv",
        tmp_path / "out.mp4",
        hdr_info(),
        "",
        0,
        lambda *_args: None,
        threading.Event(),
    )
    assert result == EncoderBackend.INTEL
    assert attempts == [
        EncoderBackend.NVIDIA,
        EncoderBackend.AMD,
        EncoderBackend.INTEL,
    ]


def test_standard_conversion_uses_cpu_when_no_gpu_encoder_works(tmp_path, monkeypatch):
    instance = preparer(tmp_path)
    instance._backend_probe = {
        EncoderBackend.NVIDIA: False,
        EncoderBackend.AMD: False,
        EncoderBackend.INTEL: False,
    }
    attempts = []

    def fake_transcode(_source, output, _info, _subtitle, _audio, backend, *_args):
        attempts.append(backend)
        output.write_bytes(b"converted")

    monkeypatch.setattr(instance, "_run_transcode", fake_transcode)
    result = instance._transcode_with_fallback(
        "movie.mkv",
        tmp_path / "out.mp4",
        hdr_info(),
        "",
        0,
        lambda *_args: None,
        threading.Event(),
    )
    assert result == EncoderBackend.CPU
    assert attempts == [EncoderBackend.CPU]


@pytest.mark.parametrize(
    ("backend", "hwaccel", "filter_name", "encoder"),
    [
        (EncoderBackend.NVIDIA, "cuda", "scale_cuda", "hevc_nvenc"),
        (EncoderBackend.AMD, "amf", "vpp_amf", "hevc_amf"),
        (EncoderBackend.INTEL, "qsv", "scale_qsv", "hevc_qsv"),
    ],
)
def test_hdr_stream_has_vendor_specific_zero_copy_pipeline(
    backend, hwaccel, filter_name, encoder
):
    inputs, filters, video = MediaPreparer._hdr_video_options(backend, "hevc")
    assert hwaccel in inputs
    assert filter_name in " ".join(filters)
    assert encoder in video
    assert "main10" in video
    assert video[video.index("-g") + 1] == "96"


def test_hdr_hls_is_paced_and_publishes_complete_segments(tmp_path, monkeypatch):
    instance = preparer(tmp_path)
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
    instance._start_hardware_hls(
        "movie.mkv",
        hdr_info(),
        lambda *_args: None,
        12.5,
        0,
        EncoderBackend.NVIDIA,
    )

    command = captured["command"]
    assert command[command.index("-readrate") + 1] == "1.05"
    assert command[command.index("-readrate_initial_burst") + 1] == "30"
    assert command[command.index("-readrate_catchup") + 1] == "1.5"
    assert command[command.index("-g") + 1] == "96"
    assert command[command.index("-hls_flags") + 1] == (
        "independent_segments+temp_file"
    )
    assert command[command.index("-ss") + 1] == "12.000"
    assert command[command.index("-start_number") + 1] == "3"
    assert command[-1].endswith("producer.m3u8")
    assert captured["producer_manifest_name"] == "producer.m3u8"
    assert captured["duration"] == 108


def test_hdr_vod_timeline_declares_full_duration_and_seek_boundary(tmp_path):
    session = object.__new__(HlsSession)
    session.manifest = tmp_path / "index.m3u8"

    session.publish_vod_timeline(10.5, first_real_segment=2)

    playlist = session.manifest.read_text(encoding="utf-8")
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in playlist
    assert playlist.endswith("#EXT-X-ENDLIST\n")
    assert playlist.count("#EXTINF:") == 3
    assert "#EXTINF:2.500000,\nsegment_000002.m4s" in playlist
    assert (
        '#EXT-X-DISCONTINUITY\n#EXT-X-MAP:URI="init.mp4"\n'
        "#EXTINF:2.500000,\nsegment_000002.m4s"
    ) in playlist


def test_hdr_stream_fails_over_to_next_gpu(tmp_path, monkeypatch):
    instance = preparer(tmp_path)
    instance._backend_probe = {
        EncoderBackend.NVIDIA: True,
        EncoderBackend.AMD: True,
        EncoderBackend.INTEL: False,
    }
    attempts = []
    sessions = []

    class FakeSession:
        def __init__(self, backend):
            self.backend = backend
            self.manifest = tmp_path / f"{backend}.m3u8"
            self.progress = lambda *_args: None
            self.stopped = False

        def wait_until_ready(self, cancel):
            if self.backend == EncoderBackend.NVIDIA:
                raise RuntimeError("NVDEC does not support this stream")

        def publish_vod_timeline(self, duration, first_real_segment):
            self.published = (duration, first_real_segment)

        def stop(self):
            self.stopped = True

    def fake_start(_source, _info, _progress, _position, _audio, backend):
        attempts.append(backend)
        session = FakeSession(backend)
        sessions.append(session)
        return session

    monkeypatch.setattr(instance, "_start_hardware_hls", fake_start)
    result = instance._prepare_hdr_stream(
        "movie.mkv",
        hdr_info(),
        0,
        10.0,
        lambda *_args: None,
        threading.Event(),
    )
    assert result is not None and result.streaming
    assert result.stream_session is sessions[1]
    assert attempts == [EncoderBackend.NVIDIA, EncoderBackend.AMD]
    assert sessions[0].stopped
    assert not sessions[1].stopped
    assert sessions[1].published == (120, 2)
    assert result.absolute_timeline
    assert result.start_position_seconds == 10.0


def test_subtitle_stream_fails_over_to_next_gpu(tmp_path, monkeypatch):
    instance = preparer(tmp_path)
    instance._backend_probe = {
        EncoderBackend.NVIDIA: True,
        EncoderBackend.AMD: True,
        EncoderBackend.INTEL: False,
    }
    attempts = []
    sessions = []

    class FakeSession:
        def __init__(self, backend):
            self.backend = backend
            self.manifest = tmp_path / f"{backend}-subtitles.m3u8"
            self.progress = lambda *_args: None
            self.stopped = False

        def wait_until_ready(self, cancel):
            assert not cancel.is_set()
            if self.backend == EncoderBackend.NVIDIA:
                raise RuntimeError("NVENC could not initialize")

        def publish_vod_timeline(self, duration, first_real_segment):
            self.published = (duration, first_real_segment)

        def stop(self):
            self.stopped = True

    def fake_start(
        _source,
        _info,
        _subtitle,
        _progress,
        _position,
        _audio,
        backend,
        _accelerated,
    ):
        attempts.append(backend)
        session = FakeSession(backend)
        sessions.append(session)
        return session

    monkeypatch.setattr(instance, "_start_transcode_hls", fake_start)
    result = instance._prepare_transcode_stream(
        "movie.mkv",
        hdr_info(),
        "embedded:0",
        0,
        10.0,
        lambda *_args: None,
        threading.Event(),
    )

    assert result is not None and result.streaming
    assert result.kind.value == "transcode"
    assert result.stream_session is sessions[1]
    assert attempts == [EncoderBackend.NVIDIA, EncoderBackend.AMD]
    assert sessions[0].stopped
    assert not sessions[1].stopped
    assert not hasattr(sessions[0], "published")
    assert sessions[1].published == (120, 2)
    assert result.absolute_timeline


def test_cuda_subtitle_filter_failure_retries_compatible_nvidia_path(
    tmp_path, monkeypatch
):
    instance = preparer(tmp_path)
    instance._backend_probe = {
        EncoderBackend.NVIDIA: True,
        EncoderBackend.AMD: False,
        EncoderBackend.INTEL: False,
    }
    attempts = []
    sessions = []

    class FakeSession:
        def __init__(self, accelerated):
            self.accelerated = accelerated
            self.manifest = tmp_path / f"{accelerated}-subtitles.m3u8"
            self.progress = lambda *_args: None
            self.stopped = False

        def wait_until_ready(self, cancel):
            assert not cancel.is_set()
            if self.accelerated:
                raise RuntimeError("scale_cuda failed to configure input")

        def publish_vod_timeline(self, duration, first_real_segment):
            self.published = (duration, first_real_segment)

        def stop(self):
            self.stopped = True

    def fake_start(
        _source,
        _info,
        _subtitle,
        _progress,
        _position,
        _audio,
        backend,
        accelerated,
    ):
        attempts.append((backend, accelerated))
        session = FakeSession(accelerated)
        sessions.append(session)
        return session

    monkeypatch.setattr(instance, "_start_transcode_hls", fake_start)
    result = instance._prepare_transcode_stream(
        "movie.mkv",
        hdr_info(),
        "embedded:0",
        0,
        10.0,
        lambda *_args: None,
        threading.Event(),
    )

    assert result is not None and result.streaming
    assert result.stream_session is sessions[1]
    assert attempts == [
        (EncoderBackend.NVIDIA, True),
        (EncoderBackend.NVIDIA, False),
    ]
    assert sessions[0].stopped
    assert not sessions[1].stopped
    assert not hasattr(sessions[0], "published")
    assert sessions[1].published == (120, 2)
    assert result.absolute_timeline


def test_cuda_subtitle_pipeline_is_not_used_for_bitmap_subtitles(tmp_path):
    instance = preparer(tmp_path)
    info = hdr_info()
    info.streams.append(MediaStream(2, "subtitle", "hdmv_pgs_subtitle"))

    assert not instance._nvidia_subtitle_pipeline_supported(
        info,
        "embedded:0",
        EncoderBackend.NVIDIA,
    )


def test_backend_labels_are_user_facing():
    assert BACKEND_LABELS[EncoderBackend.NVIDIA] == "NVIDIA NVENC"
    assert BACKEND_LABELS[EncoderBackend.AMD] == "AMD AMF"
    assert BACKEND_LABELS[EncoderBackend.INTEL] == "Intel Quick Sync"


def test_hardware_probe_uses_dimensions_accepted_by_nvenc(tmp_path, monkeypatch):
    instance = preparer(tmp_path)
    captured = {}

    class Result:
        returncode = 0

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return Result()

    monkeypatch.setattr("violetrelay.services.converter.subprocess.run", fake_run)
    assert instance._probe_hardware_backend(EncoderBackend.NVIDIA)
    assert "color=c=black:s=256x256:r=1" in captured["command"]


def test_non_hardware_ffmpeg_failure_is_not_retried(tmp_path, monkeypatch):
    instance = preparer(tmp_path)
    instance._backend_probe = {
        EncoderBackend.NVIDIA: True,
        EncoderBackend.AMD: True,
        EncoderBackend.INTEL: True,
    }
    attempts = []

    def fail(_source, _output, _info, _subtitle, _audio, backend, *_args):
        attempts.append(backend)
        raise RuntimeError("No space left on device")

    monkeypatch.setattr(instance, "_run_transcode", fail)
    with pytest.raises(RuntimeError, match="No space"):
        instance._transcode_with_fallback(
            "movie.mkv",
            tmp_path / "out.mp4",
            hdr_info(),
            "",
            0,
            lambda *_args: None,
            threading.Event(),
        )
    assert attempts == [EncoderBackend.NVIDIA]
