import threading

import pytest

import violetrelay.controllers.playback as playback_module
from violetrelay.controllers.playback import PlaybackController
from violetrelay.models import QueueModel
from violetrelay.services.converter import PreparedMedia
from violetrelay.services.media import (
    MediaInfo,
    MediaStream,
    RemoteMediaIdentity,
)
from violetrelay.services.media import PreparationKind
from violetrelay.settings import SettingsStore


class FakePreparer:
    def __init__(self, info):
        self.probe = type("Probe", (), {"probe": lambda _self, _source: info})()


def track_info(source: str) -> MediaInfo:
    return MediaInfo(
        source=source,
        duration_seconds=30,
        format_name="matroska",
        size=100,
        streams=[
            MediaStream(0, "video", "h264"),
            MediaStream(1, "audio", "aac", tags={"language": "eng"}),
            MediaStream(
                2,
                "audio",
                "aac",
                tags={"language": "nld", "title": "Dub"},
                disposition={"default": 1},
            ),
            MediaStream(3, "subtitle", "ass", tags={"language": "eng"}),
            MediaStream(4, "subtitle", "hdmv_pgs_subtitle", tags={"language": "nld"}),
        ],
    )


def test_probe_populates_track_models_and_default(qtbot, tmp_path):
    queue = QueueModel()
    source = str(tmp_path / "movie.mkv")
    queue.addFiles([source])
    controller = PlaybackController(queue, SettingsStore(tmp_path / "settings.json"))
    info = track_info(source)
    controller._on_probe_finished(queue.current_item().id, info)
    assert queue.current_item().audio_stream == 1
    assert controller.audioTracks[1]["label"].startswith("NLD · Dub")
    assert controller.subtitleTracks[1]["value"] == "embedded:0"
    controller.close()


def test_selection_is_stored_and_bitmap_subtitle_offers_fallback(qtbot, tmp_path):
    queue = QueueModel()
    source = str(tmp_path / "movie.mkv")
    queue.addFiles([source])
    controller = PlaybackController(queue, SettingsStore(tmp_path / "settings.json"))
    controller._on_probe_finished(queue.current_item().id, track_info(source))
    controller.selectAudioTrack(0)
    assert queue.current_item().audio_stream == 0
    with qtbot.waitSignal(controller.fallbackSuggested):
        controller.selectSubtitleTrack("embedded:1")
    assert queue.current_item().subtitle == "embedded:1"
    controller.selectSubtitleTrack("")
    assert queue.current_item().subtitle == ""
    controller.close()


def test_local_player_error_offers_conversion_instead_of_terminal_error(qtbot, tmp_path):
    queue = QueueModel()
    source_path = tmp_path / "movie.mkv"
    source_path.write_bytes(b"unsupported")
    queue.addFiles([str(source_path)])
    controller = PlaybackController(
        queue,
        SettingsStore(tmp_path / "settings.json"),
        FakePreparer(track_info(str(source_path))),
    )
    terminal_errors = []
    controller.errorOccurred.connect(terminal_errors.append)
    with qtbot.waitSignal(controller.fallbackSuggested) as prompt:
        controller._on_player_error(None, "Unsupported codec")
    assert "compatible local copy" in prompt.args[0]
    assert terminal_errors == []
    controller.close()


def test_settings_write_failure_is_reported_without_reverting_control(qtbot, tmp_path):
    queue = QueueModel()
    settings = SettingsStore(tmp_path / "settings.json")
    controller = PlaybackController(queue, settings)

    def fail_set(*_args):
        raise OSError("read-only settings")

    settings.set = fail_set
    with qtbot.waitSignal(controller.errorOccurred) as signal:
        controller.setVolume(0.35)
    assert "read-only settings" in signal.args[0]
    assert controller.volume == pytest.approx(0.35)
    controller.close()


def test_embedded_subtitles_are_left_to_qt_without_qml_duplicate(tmp_path):
    queue = QueueModel()
    queue.addFiles([str(tmp_path / "movie.mkv")])
    queue.current_item().subtitle = "embedded:0"
    controller = PlaybackController(queue, SettingsStore(tmp_path / "settings.json"))

    controller._refresh_subtitle_text()

    assert controller.subtitleText == ""
    controller.close()


def test_external_srt_still_uses_qml_overlay(tmp_path):
    queue = QueueModel()
    queue.addFiles([str(tmp_path / "movie.mkv")])
    subtitle = tmp_path / "captions.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nExternal caption\n",
        encoding="utf-8",
    )
    controller = PlaybackController(queue, SettingsStore(tmp_path / "settings.json"))
    controller.selectExternalSubtitle(str(subtitle))

    controller._refresh_subtitle_text()

    assert controller.subtitleText == "External caption"
    controller.close()


def test_completed_fallback_replaces_only_local_playback_and_keeps_queue_source(
    qtbot, tmp_path
):
    queue = QueueModel()
    original = tmp_path / "movie.mkv"
    converted = tmp_path / "converted.mp4"
    original.write_bytes(b"source")
    converted.write_bytes(b"converted")
    queue.addFiles([str(original)])
    controller = PlaybackController(queue, SettingsStore(tmp_path / "settings.json"))
    controller._fallback_preparing = True
    controller._fallback_resume_ms = 1234
    controller._on_fallback_finished(
        queue.current_item().id,
        PreparedMedia(
            str(converted), PreparationKind.TRANSCODE, False, track_info(str(original))
        ),
    )
    assert queue.current_item().source == str(original)
    assert controller._local_overrides[queue.current_item().id] == str(converted)
    assert controller._using_fallback
    assert controller._pending_seek_ms == 1234
    assert not controller.fallbackPreparing
    controller.close()


def test_direct_url_is_preflighted_without_blocking_ui(
    qtbot, tmp_path, monkeypatch
):
    queue = QueueModel()
    controller = PlaybackController(
        queue, SettingsStore(tmp_path / "settings.json")
    )
    inspected = []
    release = threading.Event()

    def inspect(source):
        inspected.append(source)
        release.wait(timeout=2)
        return RemoteMediaIdentity(
            source,
            1_000,
            content_type="video/mp4",
            etag='"revision"',
        )

    monkeypatch.setattr(
        playback_module,
        "inspect_remote_media",
        inspect,
    )
    played = []
    monkeypatch.setattr(controller, "playIndex", played.append)

    controller.openUrl("https://example.test/movie")

    assert controller.urlOpening
    release.set()
    qtbot.waitUntil(lambda: not controller.urlOpening)
    assert inspected == ["https://example.test/movie"]
    assert queue.count == 1
    assert played == [0]
    controller.close()


def test_webpage_url_is_rejected_before_player_load(
    qtbot, tmp_path, monkeypatch
):
    queue = QueueModel()
    controller = PlaybackController(
        queue, SettingsStore(tmp_path / "settings.json")
    )
    monkeypatch.setattr(
        playback_module,
        "inspect_remote_media",
        lambda source: RemoteMediaIdentity(
            source,
            500,
            content_type="text/html",
            etag='"page"',
        ),
    )

    with qtbot.waitSignal(controller.errorOccurred) as signal:
        controller.openUrl("https://example.test/watch")

    assert "web page" in signal.args[0]
    assert queue.count == 0
    controller.close()
