import asyncio
import threading
from types import SimpleNamespace

import pyatv
import pytest
from pyatv.const import DeviceState, FeatureName, FeatureState, Protocol

from violetrelay.services.airplay import (
    AirPlayService,
    AsyncRuntime,
    UnavailableAsyncRuntime,
)


class Config:
    identifier = "tv"
    name = "Living Room"
    address = "192.0.2.10"

    def __init__(self):
        self.airplay = SimpleNamespace(
            protocol=Protocol.AirPlay,
            credentials="credentials",
            properties={"osvers": ""},
            enabled=True,
        )
        self.services = [self.airplay]

    def get_service(self, protocol):
        return self.airplay if protocol == Protocol.AirPlay else None


def test_three_metadata_failures_report_disconnect(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")

        class Metadata:
            async def playing(self):
                raise ConnectionError("network down")

        service.atv = SimpleNamespace(metadata=Metadata())
        statuses = [await service.status() for _ in range(3)]
        service.atv = None
        return statuses

    statuses = asyncio.run(scenario())
    assert [status.state for status in statuses] == ["playing", "playing", "error"]
    assert "Lost connection" in statuses[-1].error


def test_failed_cast_start_closes_partial_connection(tmp_path, monkeypatch):
    closed = []

    class Stream:
        async def play_url(self, *_args, **_kwargs):
            raise RuntimeError("receiver rejected media")

    class Remote:
        async def stop(self):
            pass

    class Atv:
        stream = Stream()
        remote_control = Remote()

        def close(self):
            closed.append(True)
            return set()

    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        config = Config()
        config.airplay.credentials = None
        service.configs["tv"] = config

        async def connect(*_args, **_kwargs):
            return Atv()

        monkeypatch.setattr(pyatv, "connect", connect)
        with pytest.raises(RuntimeError, match="rejected"):
            await service.start_cast("tv", "https://example.test/movie.mp4")
        return service.atv, service.play_task

    atv, play_task = asyncio.run(scenario())
    assert atv is None and play_task is None
    assert closed == [True]


def test_local_server_is_cleaned_if_route_selection_fails(tmp_path, monkeypatch):
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"video")

    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        monkeypatch.setattr(
            service,
            "_local_address_for",
            lambda _address: (_ for _ in ()).throw(OSError("no route")),
        )
        with pytest.raises(OSError, match="no route"):
            await service._serve_file(media, "192.0.2.10")
        return service.hls_runner

    assert asyncio.run(scenario()) is None


def test_media_probe_requests_do_not_claim_playback_started(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        service.PLAYBACK_START_TIMEOUT_SECONDS = 0.03
        service.PLAYBACK_START_POLL_SECONDS = 0.005
        service.hls_requests.extend(["movie.mp4", "movie.mp4", "movie.mp4"])

        class Metadata:
            async def playing(self):
                return SimpleNamespace(device_state=DeviceState.Idle)

        service.atv = SimpleNamespace(metadata=Metadata())
        started = asyncio.Event()
        with pytest.raises(RuntimeError, match="did not start playback"):
            await service._wait_for_modern_playback(started)
        return started.is_set()

    assert not asyncio.run(scenario())


def test_local_cast_requires_receiver_to_fetch_playable_bytes(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        service.PLAYBACK_START_TIMEOUT_SECONDS = 0.03
        service.PLAYBACK_START_POLL_SECONDS = 0.005
        service.hls_runner = object()
        service._media_request_event = asyncio.Event()
        service.hls_requests.append("index.m3u8")

        class Metadata:
            async def playing(self):
                return SimpleNamespace(device_state=DeviceState.Playing)

        service.atv = SimpleNamespace(metadata=Metadata())
        with pytest.raises(RuntimeError, match="never requested video data"):
            await service._wait_until_playback_started()

    asyncio.run(scenario())


def test_local_cast_is_confirmed_after_playable_bytes_are_requested(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        service.PLAYBACK_START_TIMEOUT_SECONDS = 0.03
        service.PLAYBACK_START_POLL_SECONDS = 0.005
        service.hls_runner = object()
        service._media_request_event = asyncio.Event()
        service._media_request_event.set()

        class Metadata:
            async def playing(self):
                return SimpleNamespace(device_state=DeviceState.Playing)

        service.atv = SimpleNamespace(metadata=Metadata())
        await service._wait_until_playback_started()

    asyncio.run(scenario())


def test_metadata_free_tv_uses_media_fetch_and_estimates_position(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        service.METADATALESS_START_GRACE_SECONDS = 0
        service._metadata_available = False
        service._estimated_duration = 120
        service.atv = object()
        service.hls_runner = object()
        service._media_request_event = asyncio.Event()
        service._media_request_event.set()
        pending = asyncio.create_task(asyncio.Event().wait())
        try:
            await service._wait_until_playback_started(pending)
            service._estimated_started_at -= 4.2
            status = await service.status()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            service.play_task = None
            service.atv = None
            service.hls_runner = None
        return status

    status = asyncio.run(scenario())
    assert status.state == "playing"
    assert status.position_seconds == 4
    assert status.duration_seconds == 120


def test_metadata_free_tv_does_not_claim_start_without_video_bytes(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        service.PLAYBACK_START_TIMEOUT_SECONDS = 0.03
        service.PLAYBACK_START_POLL_SECONDS = 0.005
        service.METADATALESS_START_GRACE_SECONDS = 0
        service._metadata_available = False
        service.hls_runner = object()
        service._media_request_event = asyncio.Event()
        pending = asyncio.create_task(asyncio.Event().wait())
        try:
            with pytest.raises(RuntimeError, match="never connected"):
                await service._wait_until_playback_started(pending)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            service.hls_runner = None

    asyncio.run(scenario())


def test_fresh_push_metadata_avoids_polling(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")

        class Metadata:
            async def playing(self):
                raise AssertionError("poll fallback should not run")

        pushed = SimpleNamespace(
            device_state=DeviceState.Playing,
            position=12,
            total_time=120,
        )
        service.atv = SimpleNamespace(metadata=Metadata())
        service._push_playing = pushed
        service._push_updated_at = service.loop.time()
        return await service.status()

    status = asyncio.run(scenario())
    assert status.state == "playing"
    assert status.position_seconds == 12


def test_receiver_volume_is_exposed_only_when_feature_is_available(tmp_path):
    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")

        class Features:
            def in_state(self, state, feature):
                return (
                    state == FeatureState.Available
                    and feature == FeatureName.SetVolume
                )

        class Audio:
            volume = 37.0

            async def set_volume(self, level):
                self.volume = level

        class Metadata:
            async def playing(self):
                return SimpleNamespace(
                    device_state=DeviceState.Playing,
                    position=1,
                    total_time=10,
                )

        audio = Audio()
        service.atv = SimpleNamespace(
            metadata=Metadata(), features=Features(), audio=audio
        )
        status = await service.status()
        await service.set_volume(62)
        return status, audio.volume

    status, volume = asyncio.run(scenario())
    assert status.can_set_volume
    assert status.receiver_volume == 37.0
    assert volume == 62


def test_paused_final_frame_is_recognized_as_natural_end():
    assert AirPlayService._is_natural_end(
        SimpleNamespace(
            device_state=DeviceState.Paused,
            position=119,
            total_time=120,
        )
    )
    assert not AirPlayService._is_natural_end(
        SimpleNamespace(
            device_state=DeviceState.Paused,
            position=60,
            total_time=120,
        )
    )


def test_pairing_begin_failure_closes_pairing_session(tmp_path, monkeypatch):
    closed = []

    class Pairing:
        async def begin(self):
            raise ConnectionError("pairing failed")

        async def close(self):
            closed.append(True)

    async def scenario():
        service = AirPlayService(asyncio.get_running_loop(), tmp_path / "pyatv.json")
        config = Config()
        config.airplay.credentials = None
        service.configs["tv"] = config

        async def pair(*_args, **_kwargs):
            return Pairing()

        monkeypatch.setattr(pyatv, "pair", pair)
        with pytest.raises(ConnectionError):
            await service.begin_pair("tv", "AirPlay")
        return service.pairing

    assert asyncio.run(scenario()) is None
    assert closed == [True]


def test_runtime_initialization_failure_does_not_leak_worker_thread(
    tmp_path, monkeypatch
):
    before = {
        thread.ident
        for thread in threading.enumerate()
        if thread.name == "AirPlayRuntime"
    }

    async def fail_initialize(_self):
        raise RuntimeError("credential store unavailable")

    monkeypatch.setattr(AirPlayService, "initialize", fail_initialize)
    with pytest.raises(RuntimeError, match="credential store"):
        AsyncRuntime(tmp_path / "pyatv.json")

    after = {
        thread.ident
        for thread in threading.enumerate()
        if thread.name == "AirPlayRuntime"
    }
    assert after == before


def test_unavailable_runtime_reports_error_without_unawaited_coroutine():
    runtime = UnavailableAsyncRuntime("AirPlay worker failed")
    future = runtime.submit(runtime.service.scan())
    with pytest.raises(RuntimeError, match="worker failed"):
        future.result()
    runtime.close()
