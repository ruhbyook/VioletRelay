import asyncio
import logging
from types import SimpleNamespace

import pyatv
from pyatv.const import DeviceState, Protocol

import violetrelay.services.airplay as airplay_module
import violetrelay.services.airplay_modern as modern_module
from violetrelay.services.airplay import AirPlayService
from violetrelay.services.airplay_modern import (
    SENDER_MODEL,
    SENDER_OS_NAME,
    SENDER_OS_VERSION,
    SOURCE_VERSION,
    build_end_policy_command,
    build_insert_command,
    build_playback_stream_body,
    build_setup_body,
)


def test_modern_setup_identifies_ptp_sender():
    body = build_setup_body(
        "192.0.2.20",
        "SESSION",
        "CORRELATION",
        "02:58:4D:50:58:01",
    )

    assert body["timingProtocol"] == "PTP"
    assert body["isScreenMirroringSession"] is False
    assert body["osName"] == SENDER_OS_NAME
    assert body["osVersion"] == SENDER_OS_VERSION
    assert body["model"] == SENDER_MODEL
    assert body["sourceVersion"] == SOURCE_VERSION
    assert body["timingPeerInfo"]["Addresses"] == ["192.0.2.20"]
    assert body["timingPeerList"] == [body["timingPeerInfo"]]


def test_modern_queue_command_contains_url_and_position():
    command = build_insert_command(
        "http://media.test/movie.mp4",
        12.345,
        "ITEM",
        "02:58:4D:50:58:01",
    )

    assert command["type"] == "insertPlayQueueItem"
    assert command["item"]["Content-Location"] == "http://media.test/movie.mp4"
    assert "HLS-Content-Location" not in command["item"]
    assert command["item"]["streamType"] == 1
    assert command["item"]["mediaType"] == "file"
    assert command["item"]["isAudioOnly"] is False
    assert command["item"]["audioOnly"] is False
    assert command["item"]["SenderMACAddress"] == "02:58:4D:50:58:01"
    assert command["item"]["model"] == SENDER_MODEL
    assert command["item"]["Start-Position"] == {
        "flags": 1,
        "value": 12345,
        "epoch": 0,
        "timescale": 1000,
    }


def test_modern_hls_queue_selects_receiver_mse_player():
    command = build_insert_command(
        "http://media.test/live/index.m3u8?token=abc",
        0,
        "ITEM",
    )

    assert command["item"]["Content-Location"].endswith("token=abc")
    assert command["item"]["HLS-Content-Location"].endswith("token=abc")


def test_modern_queue_uses_hardware_verified_end_policy():
    assert build_end_policy_command() == {
        "type": "setProperty",
        "property": "actionAtItemEnd",
        "value": 1,
    }
    assert build_end_policy_command(0)["value"] == 0


def test_built_in_tv_declares_full_screen_playback_stream():
    assert build_playback_stream_body() == {"streams": [{"type": 120}]}


def test_modern_command_uses_airplay_video_stream_header():
    calls = []

    class Response:
        code = 200

    class Rtsp:
        async def exchange(self, method, **kwargs):
            calls.append((method, kwargs))
            return Response()

    async def scenario():
        session = airplay_module.ModernAirPlaySession(
            None,
            None,
            logging.getLogger("test.airplay"),
            receiver_compatibility=True,
        )
        session.rtsp = Rtsp()
        session._stream_headers = {
            "X-Apple-ProtocolVersion": "1",
            "X-Apple-Session-ID": "session",
            "X-Apple-Stream-ID": "1",
        }
        await session._command({"type": "setRate", "rate": 1.0})

    asyncio.run(scenario())
    assert calls[0][1]["headers"] == {
        "X-Apple-ProtocolVersion": "1",
        "X-Apple-Session-ID": "session",
        "X-Apple-Stream-ID": "1",
    }
    assert "X-Apple-StreamID" not in calls[0][1]["headers"]


def test_built_in_tv_negotiates_minimal_command_headers():
    calls = []

    class Response:
        def __init__(self, code):
            self.code = code

    class Rtsp:
        async def exchange(self, _method, **kwargs):
            headers = kwargs["headers"]
            calls.append(headers)
            return Response(200 if headers == {"X-Apple-Stream-ID": "1"} else 500)

    async def scenario():
        session = airplay_module.ModernAirPlaySession(
            None,
            None,
            logging.getLogger("test.airplay"),
            receiver_compatibility=True,
        )
        session.rtsp = Rtsp()
        session._stream_headers = {
            "X-Apple-ProtocolVersion": "1",
            "X-Apple-Session-ID": "session",
            "X-Apple-Stream-ID": "1",
        }
        await session._command({"type": "setRate", "rate": 1.0})
        return session._stream_headers

    selected = asyncio.run(scenario())
    assert calls == [
        {
            "X-Apple-ProtocolVersion": "1",
            "X-Apple-Session-ID": "session",
            "X-Apple-Stream-ID": "1",
        },
        {"X-Apple-Stream-ID": "1"},
    ]
    assert selected == {"X-Apple-Stream-ID": "1"}


def test_modern_queue_replacement_keeps_existing_rcs_session(monkeypatch):
    calls = []
    monkeypatch.setattr(modern_module, "_uuid", lambda: "NEW")

    async def scenario():
        session = modern_module.ModernAirPlaySession(
            None,
            None,
            logging.getLogger("test.airplay"),
            receiver_compatibility=True,
        )
        session.rtsp = object()
        session.item_uuid = "OLD"
        session._sender_mac_address = "02:58:4D:50:58:01"

        async def command(payload):
            calls.append(payload)

        session._command = command
        await session.replace("http://media.test/new/index.m3u8", 12.5)
        await session.finish_replacement()
        return session.item_uuid

    item_uuid = asyncio.run(scenario())
    assert item_uuid == "NEW"
    assert calls[0] == {"type": "setRate", "rate": 0.0}
    assert calls[1] == build_end_policy_command(0)
    assert calls[2]["type"] == "insertPlayQueueItem"
    assert calls[2]["itemAfter"] == {"uuid": "OLD"}
    assert calls[2]["item"]["uuid"] == "NEW"
    assert calls[2]["item"]["HLS-Content-Location"].endswith("index.m3u8")
    assert calls[2]["item"]["Start-Position"]["value"] == 12_500
    assert calls[2]["item"]["SenderMACAddress"] == "02:58:4D:50:58:01"
    assert calls[3] == {
        "type": "removePlayQueueItem",
        "item": {"uuid": "OLD"},
    }
    assert calls[4] == {"type": "setRate", "rate": 1.0}
    assert calls[5] == build_end_policy_command()


def test_modern_replacement_rejection_never_removes_old_item(monkeypatch):
    calls = []
    monkeypatch.setattr(modern_module, "_uuid", lambda: "NEW")

    async def scenario():
        session = modern_module.ModernAirPlaySession(
            None,
            None,
            logging.getLogger("test.airplay"),
            receiver_compatibility=True,
        )
        session.rtsp = object()
        session.item_uuid = "OLD"

        async def command(payload):
            calls.append(payload)
            if payload["type"] == "insertPlayQueueItem":
                raise RuntimeError("rejected")

        session._command = command
        try:
            await session.replace("http://media.test/new/index.m3u8", 0)
        except RuntimeError:
            pass
        return session.item_uuid, session.replacement_indeterminate

    item_uuid, indeterminate = asyncio.run(scenario())
    assert item_uuid == "OLD"
    assert not indeterminate
    assert not any(call["type"] == "removePlayQueueItem" for call in calls)
    assert calls[-2:] == [
        build_end_policy_command(),
        {"type": "setRate", "rate": 1.0},
    ]


def test_modern_remove_failure_marks_queue_indeterminate(monkeypatch):
    calls = []
    monkeypatch.setattr(modern_module, "_uuid", lambda: "NEW")

    async def scenario():
        session = modern_module.ModernAirPlaySession(
            None,
            None,
            logging.getLogger("test.airplay"),
            receiver_compatibility=True,
        )
        session.rtsp = object()
        session.item_uuid = "OLD"

        async def command(payload):
            calls.append(payload)
            if payload["type"] == "removePlayQueueItem":
                raise RuntimeError("ambiguous removal")

        session._command = command
        try:
            await session.replace("http://media.test/new/index.m3u8", 0)
        except RuntimeError:
            pass
        return session.item_uuid, session.replacement_indeterminate

    item_uuid, indeterminate = asyncio.run(scenario())
    assert item_uuid == "OLD"
    assert indeterminate
    assert calls[-1] == {
        "type": "removePlayQueueItem",
        "item": {"uuid": "OLD"},
    }


def test_receiver_compatibility_stops_queue_and_tears_down_session():
    calls = []

    class Rtsp:
        session_id = 42

        async def teardown(self, session_id):
            calls.append(("teardown", session_id))

    async def scenario():
        session = airplay_module.ModernAirPlaySession(
            None,
            None,
            logging.getLogger("test.airplay"),
            receiver_compatibility=True,
        )
        session.rtsp = Rtsp()
        session.item_uuid = "ITEM"

        async def command(payload):
            calls.append(payload)

        session._command = command
        await session.stop()
        await session.close()

    asyncio.run(scenario())
    assert calls == [
        {"type": "setRate", "rate": 0.0},
        {
            "type": "setProperty",
            "property": "actionAtItemEnd",
            "value": 0,
        },
        ("teardown", 42),
    ]


def test_tvos_26_prefers_modern_airplay(tmp_path, monkeypatch):
    calls = []

    class ModernSession:
        def __init__(
            self,
            config,
            service,
            _logger,
            receiver_compatibility=False,
        ):
            calls.append(("create", config.address, service.credentials))
            calls.append(("compatibility", receiver_compatibility))

        async def start(self, source, position):
            calls.append(("start", source, position))

        async def close(self):
            calls.append(("close",))

        async def stop(self):
            calls.append(("stop",))

    class Metadata:
        async def playing(self):
            return SimpleNamespace(device_state=DeviceState.Playing)

    class Remote:
        async def stop(self):
            pass

    class ConnectedAtv:
        metadata = Metadata()
        remote_control = Remote()

        def close(self):
            return set()

    class Service:
        protocol = Protocol.AirPlay
        credentials = "credentials"
        properties = {"osvers": "26.5"}
        enabled = True

    class Config:
        identifier = "tv"
        name = "Living Room"
        address = "192.0.2.10"
        services = [Service()]

        def get_service(self, protocol):
            return self.services[0] if protocol == Protocol.AirPlay else None

    async def scenario():
        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        await service.initialize()
        service.configs["tv"] = Config()

        async def fake_connect(*_args, **_kwargs):
            return ConnectedAtv()

        monkeypatch.setattr(pyatv, "connect", fake_connect)
        monkeypatch.setattr(airplay_module, "ModernAirPlaySession", ModernSession)
        await service.start_cast("tv", "https://media.test/video.mp4", 7.5)
        transport = service.cast_transport
        await service.close()
        return transport

    transport = asyncio.run(scenario())
    assert transport == "airplay2"
    assert ("start", "https://media.test/video.mp4", 7.5) in calls
    assert calls[-2:] == [("stop",), ("close",)]
