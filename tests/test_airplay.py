import asyncio
from types import SimpleNamespace

import pyatv
from aiohttp import ClientSession
from pyatv import exceptions
from pyatv.const import DeviceState, Protocol

from violetrelay.services.airplay import (
    AirPlayService,
    _requires_chunked_file_transfer,
)


class FakeModel:
    def __init__(self, name):
        self.name = name


class FakeService:
    def __init__(self, protocol, credentials=None, properties=None):
        self.protocol = protocol
        self.credentials = credentials
        self.properties = properties or {}
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
        television = FakeConfig(
            "television", "Den TV", "192.0.2.12", "Unknown", [Protocol.AirPlay]
        )
        apple_tv.get_service(Protocol.AirPlay).properties = {
            "features": "0x1"
        }
        speaker.get_service(Protocol.AirPlay).properties = {
            "features": "0x0"
        }
        television.get_service(Protocol.AirPlay).properties = {
            "features": "0x0,0x20000",
            "manufacturer": "Hisense",
            "model": "100E75LE",
        }

        async def fake_scan(*_args, **_kwargs):
            return [speaker, television, apple_tv]

        monkeypatch.setattr(pyatv, "scan", fake_scan)
        devices = await service.scan()
        await service.close()
        return devices

    devices = asyncio.run(scenario())
    assert [device.name for device in devices] == ["Den TV", "Living Room"]
    assert devices[0].model == "Hisense 100E75LE"
    assert devices[0].protocols == ("AirPlay",)
    assert not devices[0].transport_controls
    assert devices[0].receiver_compatibility
    assert devices[1].model == "Apple TV 4K (3rd generation)"
    assert devices[1].transport_controls
    assert not devices[1].receiver_compatibility


def test_airplay_video_feature_detection_rejects_audio_only_receiver():
    video = FakeService(
        Protocol.AirPlay, properties={"features": "0x7F8AD0,0x38BCF46"}
    )
    speaker = FakeService(
        Protocol.AirPlay, properties={"features": "0xC05F8A00,0x1C340"}
    )

    assert AirPlayService._supports_airplay_video(video)
    assert not AirPlayService._supports_airplay_video(speaker)


def test_windows_large_file_transfer_avoids_transmitfile_dword_limit():
    assert not _requires_chunked_file_transfer(0xFFFFFFFF, windows=True)
    assert _requires_chunked_file_transfer(0x100000000, windows=True)
    assert not _requires_chunked_file_transfer(0x100000000, windows=False)


def test_third_party_receiver_uses_compatibility_transport():
    hisense = SimpleNamespace(
        device_info=SimpleNamespace(raw_model="100E75LE")
    )
    apple_tv = SimpleNamespace(
        device_info=SimpleNamespace(raw_model="AppleTV14,1")
    )
    service = FakeService(Protocol.AirPlay)

    assert AirPlayService._is_third_party_video_receiver(hisense, service)
    assert not AirPlayService._is_third_party_video_receiver(apple_tv, service)


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


def test_local_hls_server_waits_for_future_segment_but_not_missing_prefix(
    tmp_path,
):
    async def scenario():
        directory = tmp_path / "hls"
        directory.mkdir()
        (directory / "index.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
        (directory / "segment_000003.m4s").write_bytes(b"ready")
        service = AirPlayService(
            asyncio.get_running_loop(), tmp_path / "pyatv.json"
        )
        url = await service._serve_hls(directory, "127.0.0.1")
        base_url = url.rsplit("/", 1)[0]

        async with ClientSession() as client:
            async def fetch_future():
                async with client.get(
                    base_url + "/segment_000004.m4s"
                ) as response:
                    return response.status, await response.read()

            future = asyncio.create_task(fetch_future())
            await asyncio.sleep(0.1)
            assert not future.done()
            (directory / "segment_000004.m4s").write_bytes(b"future")
            future_result = await future
            async with client.get(
                base_url + "/segment_000002.m4s"
            ) as response:
                prefix_status = response.status
        await service.close()
        return future_result, prefix_status

    future_result, prefix_status = asyncio.run(scenario())
    assert future_result == (200, b"future")
    assert prefix_status == 404


def test_overlapping_media_servers_keep_request_events_isolated(tmp_path):
    async def scenario():
        old_directory = tmp_path / "old"
        new_directory = tmp_path / "new"
        for directory, content in (
            (old_directory, b"old"),
            (new_directory, b"new"),
        ):
            directory.mkdir()
            (directory / "index.m3u8").write_text(
                "#EXTM3U\n#EXTINF:4.0,\nsegment.m4s\n",
                encoding="utf-8",
            )
            (directory / "segment.m4s").write_bytes(content)

        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        old_url = await service._serve_hls(old_directory, "127.0.0.1")
        old_runner = service.hls_runner
        old_event = service._media_request_event
        await service._serve_hls(new_directory, "127.0.0.1")
        new_event = service._media_request_event

        async with ClientSession() as client:
            old_segment = old_url.rsplit("/", 1)[0] + "/segment.m4s"
            async with client.get(old_segment) as response:
                await response.read()
        result = (old_event.is_set(), new_event.is_set())
        await old_runner.cleanup()
        await service.close()
        return result

    old_requested, new_requested = asyncio.run(scenario())
    assert old_requested
    assert not new_requested


def test_replace_stream_hands_off_server_without_reconnecting(tmp_path):
    class Runner:
        def __init__(self, name):
            self.name = name
            self.cleaned = False

        async def cleanup(self):
            self.cleaned = True

    async def scenario():
        playlist = tmp_path / "new" / "index.m3u8"
        playlist.parent.mkdir()
        playlist.write_text("#EXTM3U\n", encoding="utf-8")
        loop = asyncio.get_running_loop()
        service = AirPlayService(loop, tmp_path / "pyatv.json")
        old_runner = Runner("old")
        new_runner = Runner("new")
        old_requests = ["old.m4s"]
        old_event = asyncio.Event()
        calls = []

        class Modern:
            config = SimpleNamespace(address="192.0.2.20")
            replacement_indeterminate = False

            async def replace(self, url, position):
                calls.append(("replace", url, position))

            async def finish_replacement(self):
                calls.append(("finish",))

        service.atv = object()
        service.modern_session = Modern()
        service._receiver_compat_playback = True
        service.hls_runner = old_runner
        service.hls_requests = old_requests
        service._media_request_event = old_event
        service._served_entry_name = "old.m3u8"

        async def serve(_directory, _address):
            service.hls_runner = new_runner
            service.hls_requests = []
            service._media_request_event = asyncio.Event()
            service._served_entry_name = "index.m3u8"
            return "http://media.test/new/index.m3u8"

        async def wait_started():
            calls.append(("wait", old_runner.cleaned))

        service._serve_hls = serve
        service._wait_until_playback_started = wait_started
        await service.replace_stream(str(playlist), 12, 321)
        result = (
            calls,
            old_runner.cleaned,
            new_runner.cleaned,
            service.hls_runner,
            service._estimated_start_position,
            service._estimated_duration,
        )
        service.atv = None
        service.modern_session = None
        service.hls_runner = None
        return result

    calls, old_cleaned, new_cleaned, active_runner, start, duration = asyncio.run(
        scenario()
    )
    assert calls == [
        ("replace", "http://media.test/new/index.m3u8", 12),
        ("wait", False),
        ("finish",),
    ]
    assert old_cleaned
    assert not new_cleaned
    assert active_runner.name == "new"
    assert start == 12
    assert duration == 321


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
