import asyncio
from types import SimpleNamespace

import pyatv
from aiohttp import ClientSession
from pyatv import exceptions
from pyatv.const import DeviceState, Protocol

from violetrelay.services.airplay import AirPlayService


class FakeModel:
    def __init__(self, name):
        self.name = name


class FakeService:
    def __init__(self, protocol, credentials=None):
        self.protocol = protocol
        self.credentials = credentials
        self.enabled = True


class FakeConfig:
    def __init__(self, identifier, name, address, model, protocols):
        self.identifier = identifier
        self.name = name
        self.address = address
        self.device_info = SimpleNamespace(model=FakeModel(model))
        self.services = [FakeService(protocol) for protocol in protocols]

    def get_service(self, protocol):
        return next((service for service in self.services if service.protocol == protocol), None)


def test_scan_filters_audio_receivers_and_formats_model(tmp_path, monkeypatch):
    async def scenario():
        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        await service.initialize()
        apple_tv = FakeConfig(
            "tv", "Living Room", "192.0.2.10", "AppleTV4KGen3", [Protocol.AirPlay, Protocol.Companion]
        )
        speaker = FakeConfig(
            "speaker", "Speaker", "192.0.2.11", "Unknown", [Protocol.AirPlay, Protocol.RAOP]
        )

        async def fake_scan(*_args, **_kwargs):
            return [speaker, apple_tv]

        monkeypatch.setattr(pyatv, "scan", fake_scan)
        devices = await service.scan()
        await service.close()
        return devices

    devices = asyncio.run(scenario())
    assert len(devices) == 1
    assert devices[0].name == "Living Room"
    assert devices[0].model == "Apple TV 4K (3rd generation)"


def test_pairing_prompt_and_pin_flow(tmp_path, monkeypatch):
    class Pairing:
        device_provides_pin = True
        has_paired = False

        async def begin(self):
            pass

        def pin(self, value):
            self.entered_pin = value

        async def finish(self):
            self.has_paired = self.entered_pin == 1234

        async def close(self):
            pass

    async def scenario():
        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        await service.initialize()
        service.configs["tv"] = FakeConfig(
            "tv", "Living Room", "192.0.2.10", "AppleTV4KGen3", [Protocol.AirPlay, Protocol.Companion]
        )

        async def fake_pair(*_args, **_kwargs):
            return Pairing()

        monkeypatch.setattr(pyatv, "pair", fake_pair)
        prompt = await service.begin_pair("tv", "AirPlay")
        paired = await service.finish_pair("1234")
        await service.close()
        return prompt, paired

    prompt, paired = asyncio.run(scenario())
    assert prompt.protocol == "AirPlay"
    assert prompt.device_provides_pin
    assert paired


def test_local_hls_server_serves_manifest_and_segments(tmp_path):
    async def scenario():
        directory = tmp_path / "hls"
        directory.mkdir()
        (directory / "index.m3u8").write_text(
            '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4.0,\nsegment_000000.m4s\n',
            encoding="utf-8",
        )
        (directory / "init.mp4").write_bytes(b"init")
        (directory / "segment_000000.m4s").write_bytes(b"segment")
        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        await service.initialize()
        url = await service._serve_hls(directory, "127.0.0.1")
        async with ClientSession() as client:
            async with client.get(url) as response:
                status = response.status
                content_type = response.headers["Content-Type"]
                body = await response.text()
            segment_url = url.rsplit("/", 1)[0] + "/segment_000000.m4s"
            async with client.get(segment_url) as response:
                segment = await response.read()
        await service.close()
        return status, content_type, body, segment

    status, content_type, body, segment = asyncio.run(scenario())
    assert status == 200
    assert content_type.startswith("application/vnd.apple.mpegurl")
    assert "segment_000000.m4s" in body
    assert segment == b"segment"


def test_tvos_26_play_url_failure_has_actionable_message(tmp_path, monkeypatch):
    class FailedStream:
        async def play_url(self, *_args, **_kwargs):
            raise exceptions.HttpError("Internal Server Error", 500)

    class ConnectedAtv:
        stream = FailedStream()

        class Apps:
            async def app_list(self):
                return []

        class Remote:
            async def stop(self):
                pass

        apps = Apps()
        remote_control = Remote()

        def close(self):
            return set()

    async def scenario():
        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        await service.initialize()
        config = FakeConfig(
            "tv", "Living Room", "192.0.2.10", "AppleTV4KGen3", [Protocol.AirPlay]
        )
        config.get_service(Protocol.AirPlay).properties = {"osvers": "26.5"}
        service.configs["tv"] = config

        async def fake_connect(*_args, **_kwargs):
            return ConnectedAtv()

        monkeypatch.setattr(pyatv, "connect", fake_connect)
        try:
            await service.start_cast("tv", "https://example.test/video.mp4")
        except RuntimeError as error:
            message = str(error)
        else:
            message = ""
        await service.close()
        return message

    message = asyncio.run(scenario())
    assert "tvOS 26.5" in message
    assert "Install the free VLC app" in message


def test_tvos_26_uses_vlc_callback_fallback(tmp_path, monkeypatch):
    launched = []

    class Apps:
        async def app_list(self):
            return [SimpleNamespace(identifier="org.videolan.vlc-ios")]

        async def launch_app(self, url):
            launched.append(url)

    class Metadata:
        async def playing(self):
            return SimpleNamespace(device_state=DeviceState.Playing)

    class Remote:
        async def stop(self):
            pass

    class ConnectedAtv:
        apps = Apps()
        metadata = Metadata()
        remote_control = Remote()

        def close(self):
            return set()

    async def scenario():
        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        await service.initialize()
        config = FakeConfig(
            "tv", "Living Room", "192.0.2.10", "AppleTV4KGen3", [Protocol.AirPlay]
        )
        config.get_service(Protocol.AirPlay).properties = {"osvers": "26.5"}
        service.configs["tv"] = config

        async def fake_connect(*_args, **_kwargs):
            return ConnectedAtv()

        monkeypatch.setattr(pyatv, "connect", fake_connect)
        await service.start_cast("tv", "https://example.test/video.mp4")
        transport = service.cast_transport
        await service.close()
        return transport

    transport = asyncio.run(scenario())
    assert transport == "vlc"
    assert launched == [
        "vlc-x-callback://x-callback-url/stream?url="
        "https%3A%2F%2Fexample.test%2Fvideo.mp4"
    ]
