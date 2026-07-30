import json
from pathlib import Path

from reelferry.controllers.playback import PlaybackController
from reelferry.models import QueueModel
from reelferry.services.playback_history import (
    MIN_RESUME_MS,
    MediaIdentity,
    PlaybackHistory,
    finish_window_ms,
    is_effectively_complete,
)
from reelferry.settings import SettingsStore


def media_file(path: Path, marker: bytes = b"a") -> Path:
    path.write_bytes(marker * (150 * 1024))
    return path


def test_resume_position_survives_restart(tmp_path):
    source = media_file(tmp_path / "long audiobook.m4b")
    history_file = tmp_path / "playback_history.json"
    history = PlaybackHistory(history_file)
    identity = history.identify(source)

    assert history.save(identity, 5_213_000, 26_940_000, "Long audiobook")

    restored = PlaybackHistory(history_file).get(identity)
    assert restored is not None
    assert restored.position_ms == 5_213_000
    assert restored.duration_ms == 26_940_000
    assert restored.title == "Long audiobook"
    assert not history_file.with_suffix(".json.tmp").exists()


def test_content_identity_survives_rename_but_replacement_resets(tmp_path):
    original = media_file(tmp_path / "old name.m4b", b"a")
    first = PlaybackHistory.identify(original)
    renamed = original.rename(tmp_path / "new name.m4b")
    moved = PlaybackHistory.identify(renamed)
    assert moved.key == first.key

    renamed.write_bytes(b"b" * renamed.stat().st_size)
    replacement = PlaybackHistory.identify(renamed)
    assert replacement.key != first.key


def test_short_progress_is_ignored_and_near_end_is_completed(tmp_path):
    history = PlaybackHistory(tmp_path / "history.json")
    identity = MediaIdentity("one", "book.m4b", 100, 1)

    assert not history.save(identity, MIN_RESUME_MS - 1, 600_000, "Book")
    assert history.get(identity) is None
    assert history.save(identity, 120_000, 600_000, "Book")
    assert history.get(identity) is not None
    assert history.save(identity, 598_000, 600_000, "Book")
    assert history.get(identity) is None


def test_completion_window_is_capped_for_long_media():
    seven_and_half_hours = int(7.5 * 60 * 60 * 1000)
    assert finish_window_ms(seven_and_half_hours, audio=True) == 10_000
    assert not is_effectively_complete(
        seven_and_half_hours - 10_001,
        seven_and_half_hours,
        audio=True,
    )
    assert is_effectively_complete(
        seven_and_half_hours - 10_000,
        seven_and_half_hours,
        audio=True,
    )


def test_history_prunes_old_and_excess_entries(tmp_path):
    now = [1_000_000.0]
    history = PlaybackHistory(
        tmp_path / "history.json",
        max_entries=2,
        retention_days=1,
        clock=lambda: now[0],
    )
    for index in range(3):
        identity = MediaIdentity(str(index), f"{index}.mp4", 100, index)
        history.save(identity, 30_000, 600_000, str(index))
        now[0] += 1

    assert history.count == 2
    assert history.get(MediaIdentity("0", "0.mp4", 100, 0)) is None
    assert history.get(MediaIdentity("2", "2.mp4", 100, 2)) is not None

    now[0] += 86_401
    reloaded = PlaybackHistory(
        tmp_path / "history.json",
        max_entries=2,
        retention_days=1,
        clock=lambda: now[0],
    )
    assert reloaded.count == 0


def test_malformed_history_starts_clean(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    assert PlaybackHistory(path).count == 0


def test_controller_offers_resume_and_start_over_clears_it(qtbot, tmp_path):
    source = media_file(tmp_path / "Way of the Wolf.m4b")
    history = PlaybackHistory(tmp_path / "history.json")
    identity = history.identify(source)
    history.save(identity, 5_213_000, 26_940_000, "Way of the Wolf")
    queue = QueueModel()
    queue.addFiles([str(source)])
    controller = PlaybackController(
        queue,
        SettingsStore(tmp_path / "settings.json"),
        history=history,
    )

    with qtbot.waitSignal(controller.resumeSuggested) as signal:
        controller.playIndex(0)

    assert signal.args == ["Way of the Wolf", "1:26:53"]
    controller.startFromBeginning()
    assert history.get(identity) is None
    controller.close()


def test_remote_cast_position_is_checkpointed(tmp_path):
    source = media_file(tmp_path / "book.m4b")
    history = PlaybackHistory(tmp_path / "history.json")
    queue = QueueModel()
    queue.addFiles([str(source)])
    controller = PlaybackController(
        queue,
        SettingsStore(tmp_path / "settings.json"),
        history=history,
    )
    controller._resume_identity = history.identify(source)

    controller.checkpoint_remote_position(
        3_600_000,
        20_000_000,
        force=True,
    )

    record = history.get(controller._resume_identity)
    assert record is not None and record.position_ms == 3_600_000
    controller.close()
