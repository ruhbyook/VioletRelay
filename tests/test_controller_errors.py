import concurrent.futures
from types import SimpleNamespace

from violetrelay.controllers.airplay import AirPlayController
from violetrelay.models import QueueModel
from violetrelay.services.airplay import AirPlayDevice, CastStatus
from violetrelay.settings import SettingsStore


class Player:
    def __init__(self):
        self.play_calls = 0

    def play(self):
        self.play_calls += 1


class Playback:
    fallbackPreparing = False
    playing = True
    position = 12_000
    duration = 120_000

    def __init__(self):
        self.player = Player()
        self.paused = 0
        self.seeks = []
        self.next_calls = 0

    def pause(self):
        self.paused += 1

    def seek(self, position):
        self.seeks.append(position)

    def next(self):
        self.next_calls += 1


class Service:
    def __init__(self):
        self.replace_calls = []
        self.start_calls = []

    def start_cast(self, identifier, source, position, duration):
        self.start_calls.append((identifier, source, position, duration))

        async def start():
            pass

        return start()

    async def stop_cast(self):
        pass

    async def status(self):
        return CastStatus("playing", 1, 10)

    async def command(self, *_args):
        pass

    def replace_stream(self, source, position, duration):
        self.replace_calls.append((source, position, duration))

        async def replace():
            pass

        return replace()


class Runtime:
    def __init__(self, error=None, pending=False):
        self.service = Service()
        self.error = error
        self.pending = pending
        self.submissions = []
        self.closed = False

    def submit(self, coroutine):
        coroutine.close()
        future = concurrent.futures.Future()
        self.submissions.append(future)
        if not self.pending:
            if self.error is not None:
                future.set_exception(self.error)
            else:
                future.set_result(None)
        return future

    def close(self):
        self.closed = True


class Session:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def controller(tmp_path, runtime=None):
    runtime = runtime or Runtime()
    playback = Playback()
    instance = AirPlayController(
        QueueModel(),
        playback,
        SettingsStore(tmp_path / "settings.json"),
        runtime,
        object(),
    )
    return instance, playback, runtime


def test_cast_start_failure_resumes_local_and_cleans_stream(qtbot, tmp_path):
    instance, playback, _runtime = controller(tmp_path)
    session = Session()
    instance._active_stream_session = session
    instance._connecting = True
    instance._local_was_playing = True

    with qtbot.waitSignal(instance.errorOccurred) as signal:
        instance._on_error("connection failed")

    qtbot.waitUntil(lambda: session.stopped)
    assert signal.args == ["connection failed"]
    assert playback.player.play_calls == 1
    assert instance._active_stream_session is None
    instance.close()


def test_stop_failure_still_clears_cast_state_and_stream(qtbot, tmp_path):
    instance, _playback, _runtime = controller(
        tmp_path, Runtime(error=ConnectionError("receiver vanished"))
    )
    session = Session()
    instance._casting = True
    instance._active_stream_session = session

    with qtbot.waitSignal(instance.errorOccurred) as signal:
        instance.stopCasting()

    qtbot.waitUntil(lambda: session.stopped)
    assert "receiver vanished" in signal.args[0]
    assert not instance.casting
    instance.close()


def test_continue_local_resumes_even_if_stop_fails(qtbot, tmp_path):
    instance, playback, _runtime = controller(
        tmp_path, Runtime(error=TimeoutError("receiver timeout"))
    )
    instance._casting = True
    instance._cast_position = 42

    instance.continueLocally()

    assert playback.seeks == [42_000]
    assert playback.player.play_calls == 1
    assert not instance.casting
    instance.close()


def test_status_poll_does_not_stack_slow_requests(qtbot, tmp_path):
    instance, _playback, runtime = controller(tmp_path, Runtime(pending=True))
    instance._casting = True
    instance._cast_generation = 1

    instance._poll_status()
    instance._poll_status()
    assert len(runtime.submissions) == 1

    runtime.submissions[0].set_result(CastStatus("playing", 3, 10))
    qtbot.waitUntil(lambda: not instance._poll_in_flight)
    assert instance.castPosition == 3
    instance.close()


def test_stream_status_is_mapped_to_absolute_movie_timeline(qtbot, tmp_path):
    instance, _playback, _runtime = controller(tmp_path)
    instance._casting = True
    instance._active_stream_session = Session()
    instance._stream_start_seconds = 3_600.0
    instance._stream_duration_seconds = 7_000

    instance._on_status(CastStatus("playing", 12, 20))

    assert instance.castPosition == 3_612
    assert instance.castDuration == 7_000
    instance.close()


def test_absolute_stream_status_is_not_offset_twice(qtbot, tmp_path):
    instance, _playback, _runtime = controller(tmp_path)
    instance._casting = True
    instance._active_stream_session = Session()
    instance._stream_start_seconds = 3_600.0
    instance._stream_duration_seconds = 7_000
    instance._stream_absolute_timeline = True

    instance._on_status(CastStatus("playing", 3_612, 7_000))

    assert instance.castPosition == 3_612
    assert instance.castDuration == 7_000
    instance.close()


def test_absolute_stream_start_passes_movie_position_and_full_duration(
    qtbot, tmp_path
):
    instance, _playback, runtime = controller(tmp_path)
    instance._cast_device_id = "living-room"
    session = Session()
    prepared = SimpleNamespace(
        source=str(tmp_path / "index.m3u8"),
        streaming=True,
        stream_session=session,
        start_position_seconds=225.5,
        absolute_timeline=True,
        media_info=SimpleNamespace(duration_seconds=7_654.0),
    )

    instance._on_prepared(prepared)

    assert runtime.service.start_calls == [
        ("living-room", prepared.source, 225.5, 7_654.0)
    ]
    instance.close()


def test_stream_seek_replaces_inside_active_cast_session(qtbot, tmp_path):
    instance, playback, runtime = controller(tmp_path, Runtime(pending=True))
    old_session = Session()
    new_session = Session()
    instance.queue.addFiles([str(tmp_path / "movie.mkv")])
    instance.preparer = SimpleNamespace(
        prepare=lambda *_args, **_kwargs: SimpleNamespace(
            source=str(tmp_path / "new" / "index.m3u8"),
            streaming=True,
            stream_session=new_session,
            start_position_seconds=3_600.0,
            absolute_timeline=True,
            media_info=SimpleNamespace(duration_seconds=7_000.0),
        )
    )
    instance._casting = True
    instance._cast_position = 60
    instance._cast_duration = 7_000
    instance._stream_duration_seconds = 7_000
    instance._active_stream_session = old_session
    instance._last_cast_row = -1

    instance.seek(3_600)

    assert instance.preparing
    assert instance.casting
    assert instance._active_stream_session is old_session
    qtbot.waitUntil(lambda: len(runtime.submissions) == 1)
    assert runtime.service.replace_calls == [
        (str(tmp_path / "new" / "index.m3u8"), 3_600, 7_000.0)
    ]
    assert not old_session.stopped
    runtime.submissions[0].set_result(None)
    qtbot.waitUntil(lambda: playback.seeks == [3_600_000])
    qtbot.waitUntil(lambda: old_session.stopped)
    assert instance._active_stream_session is new_session
    assert instance.casting
    assert not instance.preparing
    assert instance.castPosition == 3_600
    assert instance.castDuration == 7_000
    assert not new_session.stopped
    instance.close()


def test_stream_seek_rejection_keeps_old_cast_playing(qtbot, tmp_path):
    instance, playback, runtime = controller(tmp_path, Runtime(pending=True))
    old_session = Session()
    new_session = Session()
    instance.queue.addFiles([str(tmp_path / "movie.mkv")])
    instance.preparer = SimpleNamespace(
        prepare=lambda *_args, **_kwargs: SimpleNamespace(
            source=str(tmp_path / "new" / "index.m3u8"),
            streaming=True,
            stream_session=new_session,
            start_position_seconds=3_600.0,
            absolute_timeline=True,
            media_info=SimpleNamespace(duration_seconds=7_000.0),
        )
    )
    instance._casting = True
    instance._cast_position = 60
    instance._cast_duration = 7_000
    instance._stream_duration_seconds = 7_000
    instance._active_stream_session = old_session

    instance.seek(3_600)
    qtbot.waitUntil(lambda: len(runtime.submissions) == 1)
    error = RuntimeError("receiver rejected replacement")
    error.cast_still_active = True
    with qtbot.waitSignal(instance.errorOccurred):
        runtime.submissions[0].set_exception(error)

    qtbot.waitUntil(lambda: new_session.stopped)
    assert instance._active_stream_session is old_session
    assert not old_session.stopped
    assert instance.casting
    assert not instance.preparing
    assert playback.player.play_calls == 0
    instance.close()


def test_preferred_receiver_is_sorted_first_and_marked(qtbot, tmp_path):
    instance, _playback, _runtime = controller(tmp_path)
    instance.settings.set("preferred_device_id", "bedroom")
    living = AirPlayDevice(
        "living", "Living Room", "192.0.2.10", "Apple TV", True, True,
        ("AirPlay", "Companion"),
    )
    bedroom = AirPlayDevice(
        "bedroom", "Bedroom", "192.0.2.11", "Apple TV", True, True,
        ("AirPlay", "Companion"),
    )

    instance._on_scan([living, bedroom])

    assert instance.devices.devices[0].identifier == "bedroom"
    index = instance.devices.index(0, 0)
    assert instance.devices.data(index, instance.devices.PreferredRole)
    instance.close()


def test_disconnect_offers_recovery_without_resuming_local(qtbot, tmp_path):
    instance, playback, _runtime = controller(tmp_path)
    instance._casting = True
    instance._cast_position = 42
    instance._cast_duration = 120

    with qtbot.waitSignal(instance.recoveryNeeded) as signal:
        instance._on_status(
            CastStatus(
                "error",
                42,
                120,
                "Lost connection to Apple TV. Retry casting or continue locally.",
            )
        )

    assert "Lost connection" in signal.args[0]
    assert playback.player.play_calls == 0
    instance.continueAfterDisconnect()
    assert playback.seeks == [42_000]
    assert playback.player.play_calls == 1
    instance.close()
