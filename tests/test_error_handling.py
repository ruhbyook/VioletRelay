import logging
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from violetrelay.app import _close_startup_components, _shutdown_components
from violetrelay.services.converter import ConversionCancelled, MediaPreparer
from violetrelay.services.media import FFmpegLocator, MediaProbe, validate_media_url
from violetrelay.settings import SettingsStore


def test_settings_reject_invalid_root_types_and_clamp_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"volume": 9, "cache_limit_gb": -4, "muted": "yes", '
        '"window": {"width": "huge", "height": 99999}}',
        encoding="utf-8",
    )
    settings = SettingsStore(path)
    assert settings.get("volume") == 1.0
    assert settings.get("cache_limit_gb") == 1
    assert settings.get("muted") is False
    assert settings.get("window.width") == 1280
    assert settings.get("window.height") == 4320

    path.write_text("[]", encoding="utf-8")
    assert SettingsStore(path).get("window.width") == 1280


def test_settings_failed_atomic_replace_removes_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    settings = SettingsStore(path)

    def fail_replace(_self, _target):
        raise OSError("disk is read-only")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="read-only"):
        settings.set("volume", 0.4)
    assert not path.with_suffix(".tmp").exists()


def test_media_probe_wraps_timeout_and_invalid_json(monkeypatch):
    locator = FFmpegLocator.__new__(FFmpegLocator)
    locator.ffmpeg = Path("ffmpeg.exe")
    locator.ffprobe = Path("ffprobe.exe")
    probe = MediaProbe(locator)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 2)

    monkeypatch.setattr("violetrelay.services.media.subprocess.run", timeout)
    with pytest.raises(TimeoutError, match="timed out"):
        probe.probe("movie.mkv", timeout=2)

    class Result:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(
        "violetrelay.services.media.subprocess.run", lambda *_a, **_k: Result()
    )
    with pytest.raises(RuntimeError, match="invalid media information"):
        probe.probe("movie.mkv")


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.test/movie.mp4",
        "https://example.test:invalid/movie.mp4",
        "https://[broken/movie.mp4",
    ],
)
def test_url_validation_rejects_credential_and_malformed_urls(url):
    with pytest.raises(ValueError):
        validate_media_url(url)


def test_ffmpeg_cancellation_does_not_wait_for_progress_output():
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ConversionCancelled):
            MediaPreparer._run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                30,
                lambda *_args: None,
                cancel,
            )
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5


def test_ffmpeg_progress_callback_failure_does_not_abort_encoding():
    MediaPreparer._run(
        [
            sys.executable,
            "-c",
            "print('out_time_us=1000000'); print('progress=end')",
        ],
        1,
        lambda *_args: (_ for _ in ()).throw(RuntimeError("UI was closed")),
        threading.Event(),
    )


def test_shutdown_always_closes_components_when_settings_fail():
    closed = []

    class Settings:
        def set(self, _key, _value):
            raise OSError("read-only")

    class Window:
        def property(self, name):
            return {"width": 1200, "height": 700, "visibility": 2}[name]

    class Component:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    _shutdown_components(
        Settings(),
        Window(),
        Component("playback"),
        Component("airplay"),
        logging.getLogger("test.shutdown"),
    )
    assert closed == ["playback", "airplay"]


def test_startup_cleanup_continues_if_airplay_close_fails():
    closed = []

    class Playback:
        def close(self):
            closed.append("playback")

    class AirPlay:
        def close(self):
            closed.append("airplay")
            raise RuntimeError("cleanup failed")

    _close_startup_components(
        Playback(), None, AirPlay(), logging.getLogger("test.startup")
    )
    assert closed == ["airplay", "playback"]
