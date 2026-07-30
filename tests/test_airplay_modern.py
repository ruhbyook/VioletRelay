import asyncio
from types import SimpleNamespace

import pyatv
from pyatv.const import DeviceState, Protocol

import reelferry.services.airplay as airplay_module
from reelferry.services.airplay import AirPlayService
from reelferry.services.airplay_modern import (
    SOURCE_VERSION,
    build_end_policy_command,
    build_insert_command,
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
    assert body["sourceVersion"] == SOURCE_VERSION
    assert body["timingPeerInfo"]["Addresses"] == ["192.0.2.20"]
    assert body["timingPeerList"] == [body["timingPeerInfo"]]


def test_modern_queue_command_contains_url_and_position():
    command = build_insert_command("http://media.test/movie.mp4", 12.345, "ITEM")

    assert command["type"] == "insertPlayQueueItem"
    assert command["item"]["Content-Location"] == "http://media.test/movie.mp4"
    assert command["item"]["Start-Position"] == {
        "flags": 1,
        "value": 12345,
        "epoch": 0,
        "timescale": 1000,
    }


def test_modern_queue_uses_hardware_verified_end_policy():
    assert build_end_policy_command() == {
        "type": "setProperty",
        "property": "actionAtItemEnd",
        "value": 1,
    }


def test_tvos_26_prefers_modern_airplay(tmp_path, monkeypatch):
    calls = []

    class ModernSession:
        def __init__(self, config, service, _logger):
            calls.append(("create", config.address, service.credentials))

        async def start(self, source, position):
            calls.append(("start", source, position))

        async def close(self):
            calls.append(("close",))

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
    assert calls[-1] == ("close",)
