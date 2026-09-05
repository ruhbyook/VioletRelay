from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import ipaddress
import logging
import mimetypes
import os
import random
import re
import secrets
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Coroutine
from urllib.parse import quote

import pyatv
from aiohttp import web
from pyatv import exceptions
from pyatv.const import DeviceState, FeatureName, FeatureState, Protocol

from violetrelay.services.airplay_compat import play_url_compatible
from violetrelay.services.airplay_modern import ModernAirPlaySession
from violetrelay.services.secure_storage import SecureFileStorage
from violetrelay.errors import error_message


_HLS_SEGMENT_NAME = re.compile(r"segment_(\d+)\.m4s\Z", re.IGNORECASE)


def _requires_chunked_file_transfer(
    count: int, *, windows: bool | None = None
) -> bool:
    """Return whether a file span exceeds Windows TransmitFile's size limit."""
    if windows is None:
        windows = os.name == "nt"
    # TransmitFile accepts at most 2,147,483,646 bytes, despite its DWORD
    # parameter. Larger spans fail with WinError 87, including 2-4 GiB MP4s.
    return windows and count > 0x7FFFFFFE


class _LargeFileResponse(web.FileResponse):
    """Use aiohttp's bounded fallback for spans beyond TransmitFile's limit."""

    async def _sendfile(self, request: Any, fobj: Any, offset: int, count: int):
        if _requires_chunked_file_transfer(count):
            writer = await web.StreamResponse.prepare(self, request)
            if writer is None:
                raise ConnectionError("The AirPlay media connection closed")
            return await self._sendfile_fallback(writer, fobj, offset, count)
        return await super()._sendfile(request, fobj, offset, count)


@dataclass(frozen=True, slots=True)
class AirPlayDevice:
    identifier: str
    name: str
    address: str
    model: str
    paired_airplay: bool
    paired_companion: bool
    protocols: tuple[str, ...]
    receiver_compatibility: bool = False

    @property
    def paired(self) -> bool:
        return self.paired_airplay and (self.paired_companion or "Companion" not in self.protocols)

    @property
    def transport_controls(self) -> bool:
        """Return whether a separate remote-control protocol was discovered."""
        return any(
            protocol in self.protocols
            for protocol in ("Companion", "MRP", "DMAP")
        )


@dataclass(frozen=True, slots=True)
class PairingPrompt:
    protocol: str
    device_provides_pin: bool
    pin_for_device: str


@dataclass(frozen=True, slots=True)
class CastStatus:
    state: str
    position_seconds: int
    duration_seconds: int
    error: str = ""
    receiver_volume: float | None = None
    can_set_volume: bool = False


class StreamReplacementError(RuntimeError):
    """A stream seek failed, with the old cast either preserved or stopped."""

    def __init__(self, message: str, *, cast_still_active: bool) -> None:
        super().__init__(message)
        self.cast_still_active = cast_still_active


class _PushListener:
    def __init__(self, service: "AirPlayService") -> None:
        self.service = service

    def playstatus_update(self, _updater: Any, playstatus: Any) -> None:
        self.service._push_playing = playstatus
        self.service._push_updated_at = self.service.loop.time()

    def playstatus_error(self, _updater: Any, exception: Exception) -> None:
        self.service.log.debug("AirPlay push metadata failed: %s", exception)
        self.service._push_playing = None
        self.service._push_updated_at = 0.0


class AsyncRuntime:
    def __init__(self, storage_path: Path):
        self.log = logging.getLogger("violetrelay.airplay.runtime")
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="AirPlayRuntime", daemon=True)
        self.service = AirPlayService(self.loop, storage_path)
        self._lock = threading.Lock()
        self._closed = False
        self._ready = threading.Event()
        self.thread.start()
        try:
            if not self._ready.wait(timeout=5):
                raise TimeoutError("The AirPlay worker did not start")
            self.submit(self.service.initialize()).result(timeout=10)
        except Exception:
            self.close()
            raise

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        try:
            self.loop.run_forever()
        except BaseException:
            self.log.exception("AirPlay worker stopped unexpectedly")
            self._ready.set()

    def submit(self, coroutine: Coroutine[Any, Any, Any]):
        with self._lock:
            if (
                self._closed
                or self.loop.is_closed()
                or not self.thread.is_alive()
                or not self.loop.is_running()
            ):
                coroutine.close()
                raise RuntimeError("The AirPlay worker is no longer running")
            try:
                return asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            except Exception:
                coroutine.close()
                raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            if self.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._shutdown(), self.loop
                )
                future.result(timeout=8)
        except Exception:
            self.log.warning("AirPlay worker cleanup did not finish cleanly", exc_info=True)
        finally:
            if self.loop.is_running():
                try:
                    self.loop.call_soon_threadsafe(self.loop.stop)
                except RuntimeError:
                    pass
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                self.log.error("AirPlay worker did not stop within the shutdown timeout")
            elif not self.loop.is_closed():
                self.loop.close()

    async def _shutdown(self) -> None:
        close_error: BaseException | None = None
        try:
            await self.service.close()
        except BaseException as error:
            close_error = error
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks(self.loop) if task is not current]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await self.loop.shutdown_asyncgens()
        if close_error is not None:
            raise close_error


class UnavailableAsyncRuntime:
    """AirPlay boundary used when its worker cannot initialize.

    Local playback remains usable and every attempted AirPlay operation fails
    through the controller's normal, user-visible error path.
    """

    class _Service:
        def __getattr__(self, _name: str):
            async def unavailable(*_args, **_kwargs):
                return None

            return unavailable

    def __init__(self, message: str) -> None:
        self.message = message.strip() or "AirPlay is unavailable"
        self.service = self._Service()

    def submit(self, coroutine: Coroutine[Any, Any, Any]):
        coroutine.close()
        future: concurrent.futures.Future = concurrent.futures.Future()
        future.set_exception(RuntimeError(self.message))
        return future

    def close(self) -> None:
        return


class AirPlayService:
    VLC_BUNDLE_IDS = {"org.videolan.vlc-ios", "com.videolan.vlc-ios"}
    PLAYBACK_START_TIMEOUT_SECONDS = 15.0
    PLAYBACK_START_POLL_SECONDS = 0.5
    METADATALESS_START_GRACE_SECONDS = 2.0

    def __init__(self, loop: asyncio.AbstractEventLoop, storage_path: Path):
        self.loop = loop
        self.storage = SecureFileStorage(str(storage_path), loop)
        self.configs: dict[str, Any] = {}
        self.pairing: Any | None = None
        self.atv: Any | None = None
        self.play_task: asyncio.Task | None = None
        self.explicit_stop = False
        self.cast_transport = ""
        self.modern_session: ModernAirPlaySession | None = None
        self.hls_runner: web.AppRunner | None = None
        self.hls_requests: list[str] = []
        self._media_request_event: asyncio.Event | None = None
        self._served_entry_name = ""
        self._status_failures = 0
        self._push_listener: _PushListener | None = None
        self._push_playing: Any | None = None
        self._push_updated_at = 0.0
        self._user_paused = False
        self._metadata_available = True
        self._estimated_started_at = 0.0
        self._estimated_start_position = 0.0
        self._estimated_duration = 0.0
        self._receiver_compat_playback = False
        self.log = logging.getLogger("violetrelay.airplay")

    async def initialize(self) -> None:
        await self.storage.load()

    @staticmethod
    def _identifier(config: Any) -> str:
        identifier = getattr(config, "identifier", None)
        if identifier:
            return str(identifier)
        identifiers = getattr(config, "all_identifiers", set())
        return str(next(iter(identifiers), config.address))

    async def scan(self, timeout: int = 5) -> list[AirPlayDevice]:
        configs = await pyatv.scan(self.loop, timeout=timeout, storage=self.storage)
        devices: list[AirPlayDevice] = []
        self.configs.clear()
        for config in configs:
            identifier = self._identifier(config)
            self.configs[identifier] = config
            airplay = config.get_service(Protocol.AirPlay)
            companion = config.get_service(Protocol.Companion)
            protocols = tuple(service.protocol.name for service in config.services if getattr(service, "enabled", True))
            device_info = getattr(config, "device_info", None)
            raw_model = getattr(device_info, "model", "") or ""
            model_name = getattr(raw_model, "name", str(raw_model))
            advertised_model = str(
                getattr(device_info, "raw_model", "")
                or getattr(airplay, "properties", {}).get("model", "")
            )
            if model_name in {"", "Unknown"}:
                model_name = advertised_model or "AirPlay receiver"
            if airplay is None or not self._supports_airplay_video(airplay):
                # AirPlay audio devices (HomePods, speakers and soundbars) are
                # useful RAOP targets but cannot display Violet Relay video.
                continue
            model = self._friendly_model(model_name)
            manufacturer = str(
                getattr(airplay, "properties", {}).get("manufacturer", "")
                or getattr(airplay, "properties", {}).get("integrator", "")
            ).strip()
            if (
                manufacturer
                and "apple" not in manufacturer.casefold()
                and manufacturer.casefold() not in model.casefold()
            ):
                model = f"{manufacturer} {model}"
            devices.append(
                AirPlayDevice(
                    identifier=identifier,
                    name=str(config.name or "AirPlay receiver"),
                    address=str(config.address),
                    model=model,
                    paired_airplay=bool(airplay and airplay.credentials),
                    paired_companion=bool(companion and companion.credentials),
                    protocols=protocols,
                    receiver_compatibility=self._is_third_party_video_receiver(
                        config, airplay
                    ),
                )
            )
        return sorted(devices, key=lambda device: device.name.casefold())

    @staticmethod
    def _airplay_feature_flags(service: Any) -> int:
        properties = getattr(service, "properties", {})
        raw_features = str(
            properties.get("features", properties.get("ft", "0x0"))
        )
        try:
            parts = [int(part, 16) for part in raw_features.split(",")]
        except (TypeError, ValueError):
            return 0
        flags = parts[0] if parts else 0
        if len(parts) > 1:
            flags |= parts[1] << 32
        return flags

    @classmethod
    def _supports_airplay_video(cls, service: Any) -> bool:
        """Use advertised AirPlay feature bits to exclude audio-only targets."""
        flags = cls._airplay_feature_flags(service)
        supports_video_v1 = bool(flags & (1 << 0))
        supports_video_v2 = bool(flags & (1 << 49))
        return supports_video_v1 or supports_video_v2

    @classmethod
    def _supports_airplay_play_queue(cls, service: Any) -> bool:
        return bool(cls._airplay_feature_flags(service) & (1 << 33))

    @staticmethod
    def _friendly_model(model: str) -> str:
        known = {
            "AppleTV4KGen1": "Apple TV 4K (1st generation)",
            "AppleTV4KGen2": "Apple TV 4K (2nd generation)",
            "AppleTV4KGen3": "Apple TV 4K (3rd generation)",
            "AppleTVHD": "Apple TV HD",
            "AppleTV3": "Apple TV (3rd generation)",
        }
        return known.get(model, model.replace("DeviceModel.", "").replace("AppleTV", "Apple TV ").strip())

    def _config(self, identifier: str) -> Any:
        try:
            return self.configs[identifier]
        except KeyError as error:
            raise RuntimeError("The AirPlay receiver is no longer available; scan again") from error

    async def begin_pair(self, identifier: str, protocol_name: str) -> PairingPrompt | None:
        try:
            protocol = Protocol[protocol_name]
        except KeyError as error:
            raise ValueError(f"Unsupported pairing protocol: {protocol_name}") from error
        config = self._config(identifier)
        service = config.get_service(protocol)
        if service is None or service.credentials:
            return None
        if self.pairing is not None:
            await self._close_pairing()
        self.pairing = await pyatv.pair(
            config, protocol, self.loop, storage=self.storage
        )
        try:
            await asyncio.wait_for(self.pairing.begin(), timeout=30)
        except Exception:
            await self._close_pairing_safely()
            raise
        device_provides = bool(self.pairing.device_provides_pin)
        pin_for_device = ""
        if not device_provides:
            pin_for_device = f"{random.randint(0, 9999):04d}"
            self.pairing.pin(int(pin_for_device))
        return PairingPrompt(protocol.name, device_provides, pin_for_device)

    async def finish_pair(self, pin: str) -> bool:
        if self.pairing is None:
            raise RuntimeError("No pairing request is active")
        pairing = self.pairing
        try:
            if pairing.device_provides_pin:
                normalized = "".join(character for character in pin if character.isdigit())
                if not normalized:
                    raise ValueError("Enter the PIN displayed on the AirPlay receiver")
                pairing.pin(int(normalized))
            await asyncio.wait_for(pairing.finish(), timeout=30)
            paired = bool(pairing.has_paired)
            if paired:
                await self.storage.save()
            return paired
        finally:
            await self._close_pairing_safely()

    async def _close_pairing(self) -> None:
        if self.pairing is None:
            return
        pairing = self.pairing
        self.pairing = None
        result = pairing.close()
        if inspect.isawaitable(result):
            await result

    async def _close_pairing_safely(self) -> None:
        try:
            await self._close_pairing()
        except Exception:
            self.log.warning("Pairing session cleanup failed", exc_info=True)

    async def start_cast(
        self,
        identifier: str,
        source: str,
        position_seconds: float = 0,
        duration_seconds: float = 0,
    ) -> None:
        await self.stop_cast()
        try:
            await self._start_cast(
                identifier, source, position_seconds, duration_seconds
            )
        except Exception:
            await self.stop_cast()
            raise

    async def replace_stream(
        self,
        source: str,
        position_seconds: float = 0,
        duration_seconds: float = 0,
    ) -> None:
        """Replace generated HLS while preserving the active AirPlay 2 session."""
        if (
            self.atv is None
            or self.modern_session is None
            or not self._receiver_compat_playback
        ):
            raise RuntimeError(
                "This AirPlay receiver cannot seek by replacing its active stream"
            )
        source_path = Path(source)
        if not source_path.is_file() or source_path.suffix.casefold() != ".m3u8":
            raise RuntimeError("AirPlay stream replacement requires a local HLS playlist")

        old_runner = self.hls_runner
        old_requests = self.hls_requests
        old_media_event = self._media_request_event
        old_entry_name = self._served_entry_name
        new_runner: web.AppRunner | None = None
        switched = False
        try:
            play_source = await self._serve_hls(
                source_path.parent,
                str(self.modern_session.config.address),
            )
            new_runner = self.hls_runner
            await self.modern_session.replace(play_source, position_seconds)
            switched = True

            # A finite generated playlist exposes the original movie timeline,
            # including after an in-session queue replacement.
            self._estimated_started_at = 0.0
            self._estimated_start_position = max(0.0, position_seconds)
            self._estimated_duration = max(0.0, duration_seconds)
            self._status_failures = 0
            self._push_playing = None
            self._push_updated_at = 0.0
            await self._wait_until_playback_started()
            await self.modern_session.finish_replacement()
        except Exception as error:
            indeterminate = bool(
                self.modern_session is not None
                and self.modern_session.replacement_indeterminate
            )
            cast_still_active = False
            if indeterminate:
                # The receiver did not conclusively report whether OLD or NEW
                # is current. Stop the shared queue before closing either
                # server; guessing could strand it on a dead URL.
                try:
                    await self.stop_cast()
                finally:
                    if old_runner is not None:
                        try:
                            await old_runner.cleanup()
                        except Exception:
                            self.log.warning(
                                "Previous media server cleanup failed after an "
                                "indeterminate seek",
                                exc_info=True,
                            )
            elif not switched:
                # The current queue item is still valid. Discard only the new
                # server and put its predecessor back into the active aliases.
                if new_runner is not None:
                    try:
                        await new_runner.cleanup()
                    except Exception:
                        self.log.warning(
                            "Replacement media server cleanup failed",
                            exc_info=True,
                        )
                self.hls_runner = old_runner
                self.hls_requests = old_requests
                self._media_request_event = old_media_event
                self._served_entry_name = old_entry_name
                cast_still_active = True
            else:
                # NEW was selected but could not be confirmed. Stop it instead
                # of leaving the UI attached to an unusable queue item.
                try:
                    await self.stop_cast()
                finally:
                    if old_runner is not None:
                        try:
                            await old_runner.cleanup()
                        except Exception:
                            self.log.warning(
                                "Previous media server cleanup failed after seek",
                                exc_info=True,
                            )
            raise StreamReplacementError(
                f"AirPlay could not seek to the requested position: {error}",
                cast_still_active=cast_still_active,
            ) from error
        else:
            if old_runner is not None and old_runner is not new_runner:
                try:
                    await old_runner.cleanup()
                except Exception:
                    self.log.warning(
                        "Previous media server cleanup failed after seek",
                        exc_info=True,
                    )
            self.log.info("AirPlay stream replaced inside the active queue session")

    async def _start_cast(
        self,
        identifier: str,
        source: str,
        position_seconds: float = 0,
        duration_seconds: float = 0,
    ) -> None:
        config = self._config(identifier)
        self.atv = await asyncio.wait_for(
            pyatv.connect(config, self.loop, storage=self.storage), timeout=15
        )
        self._start_push_updates()
        self.explicit_stop = False
        self._user_paused = False
        self._status_failures = 0
        self._receiver_compat_playback = self._is_third_party_video_receiver(
            config, airplay_service=config.get_service(Protocol.AirPlay)
        )
        self._metadata_available = self._supports_playback_metadata()
        self._estimated_started_at = 0.0
        self._estimated_start_position = max(0.0, position_seconds)
        self._estimated_duration = max(0.0, duration_seconds)
        self.cast_transport = "airplay"
        play_source = source
        source_path = Path(source)
        if source_path.is_file() and source_path.suffix.lower() == ".m3u8":
            play_source = await self._serve_hls(source_path.parent, str(config.address))
        airplay = config.get_service(Protocol.AirPlay)
        os_version = str(getattr(airplay, "properties", {}).get("osvers", ""))
        self.log.info(
            "Starting cast: receiver=%s tvOS=%s source=%s",
            str(getattr(config, "name", "AirPlay receiver")),
            os_version or "unknown",
            "local-server" if self.hls_runner is not None else "remote-url",
        )

        # tvOS 26 and built-in TVs advertising AirPlay queue playback require
        # an AirPlay 2 PTP session followed by /command insertPlayQueueItem.
        # VLC remains an emergency compatibility transport on Apple TV.
        modern_receiver = os_version.startswith("26.") or (
            self._receiver_compat_playback
            and self._supports_airplay_play_queue(airplay)
        )
        modern_error: Exception | None = None
        if modern_receiver:
            if source_path.is_file() and source_path.suffix.lower() != ".m3u8":
                play_source = await self._serve_file(source_path, str(config.address))
            try:
                await self._start_modern_cast(
                    config, airplay, play_source, position_seconds
                )
            except Exception as error:
                modern_error = error
                self.log.warning("Modern AirPlay failed: %s", modern_error)
                if self.modern_session is not None:
                    await self.modern_session.close()
                    self.modern_session = None
                # VLC is a distinct receiver attempt and must prove that it
                # fetched media itself, not inherit a request from AirPlay.
                self.hls_requests.clear()
                if self._media_request_event is not None:
                    self._media_request_event.clear()
                if os_version.startswith("26."):
                    try:
                        await self._start_vlc_cast(
                            play_source, os_version, position_seconds
                        )
                    except Exception as vlc_error:
                        await self.stop_cast()
                        raise RuntimeError(
                            f"Modern AirPlay failed: {modern_error}. "
                            f"VLC fallback failed: {vlc_error}"
                        ) from modern_error
                    return
                self.log.info(
                    "Trying the built-in TV URL-play fallback after queue failure"
                )
            else:
                return

        if self._receiver_compat_playback:
            self.log.info(
                "Using built-in TV AirPlay compatibility transport"
            )
            playback = play_url_compatible(
                config,
                airplay,
                play_source,
                position_seconds,
                self.log,
            )
        else:
            playback = self.atv.stream.play_url(
                play_source, position=position_seconds
            )
        self.play_task = asyncio.create_task(playback)
        try:
            await self._wait_until_playback_started(self.play_task)
        except exceptions.HttpError as error:
            if error.status_code == 500 and os_version.startswith("26."):
                raise RuntimeError(
                    f"Apple TV on tvOS {os_version} rejected AirPlay media playback. "
                    "This is a known tvOS 26 / pyatv play_url regression; the video "
                    "and GPU conversion are not the cause."
                ) from error
            raise
        except Exception as error:
            if modern_error is not None:
                raise RuntimeError(
                    f"AirPlay 2 queue playback failed: {modern_error}. "
                    f"The receiver's URL fallback also failed: {error}"
                ) from modern_error
            raise

    async def _start_modern_cast(
        self,
        config: Any,
        airplay_service: Any,
        source: str,
        position_seconds: float,
    ) -> None:
        if airplay_service is None or not airplay_service.credentials:
            raise RuntimeError("Pair AirPlay before starting playback")
        self.modern_session = ModernAirPlaySession(
            config,
            airplay_service,
            self.log,
            receiver_compatibility=self._receiver_compat_playback,
        )
        try:
            await self.modern_session.start(source, position_seconds)
            self.cast_transport = "airplay2"
            started = asyncio.Event()
            self.play_task = asyncio.create_task(
                self._wait_for_modern_playback(started)
            )
            started_waiter = asyncio.create_task(started.wait())
            try:
                done, _pending = await asyncio.wait(
                    {started_waiter, self.play_task},
                    timeout=(
                        self.PLAYBACK_START_TIMEOUT_SECONDS
                        + self.PLAYBACK_START_POLL_SECONDS
                    ),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if self.play_task in done:
                    await self.play_task
                    raise RuntimeError(
                        "The AirPlay receiver stopped before media playback was confirmed"
                    )
                if started_waiter not in done:
                    raise RuntimeError(
                        "The AirPlay receiver accepted the media queue but did not start playback"
                    )
            finally:
                if not started_waiter.done():
                    started_waiter.cancel()
                await asyncio.gather(started_waiter, return_exceptions=True)
            if self.play_task.done():
                await self.play_task
        except Exception:
            if self.play_task is not None and not self.play_task.done():
                self.play_task.cancel()
                await asyncio.gather(self.play_task, return_exceptions=True)
            self.play_task = None
            if self.modern_session is not None:
                await self.modern_session.close()
                self.modern_session = None
            raise

    async def _wait_for_modern_playback(
        self, started_event: asyncio.Event | None = None
    ) -> None:
        if self.atv is None:
            raise RuntimeError("The AirPlay receiver disconnected before playback started")
        await self._wait_until_playback_started()
        if started_event is not None:
            started_event.set()
        if not self._metadata_available:
            while True:
                await asyncio.sleep(1)
                if (
                    self._estimated_duration > 0
                    and self._estimated_started_at > 0
                    and self.loop.time() - self._estimated_started_at
                    >= max(
                        0.0,
                        self._estimated_duration
                        - self._estimated_start_position,
                    )
                ):
                    return
        idle_samples = 0
        confirmed_at = self.loop.time()
        while True:
            await asyncio.sleep(1)
            playing = await self._playing_with_fallback()
            if self._is_terminal_state(playing, confirmed_at):
                idle_samples += 1
                if idle_samples >= 2:
                    return
            else:
                idle_samples = 0

    async def _start_vlc_cast(
        self, source: str, os_version: str, position_seconds: float = 0
    ) -> None:
        if self.atv is None:
            raise RuntimeError("Apple TV disconnected before VLC could start")
        applications = await self.atv.apps.app_list()
        installed = {str(application.identifier) for application in applications}
        if not installed.intersection(self.VLC_BUNDLE_IDS):
            raise RuntimeError(
                f"The optional VLC fallback is unavailable on this Apple TV (tvOS {os_version}). Install the free VLC "
                "app from the App Store on Apple TV, then cast again; Violet Relay "
                "will use VLC automatically while keeping remote controls here."
            )
        callback = (
            "vlc-x-callback://x-callback-url/stream?url="
            + quote(source, safe="")
        )
        await self.atv.apps.launch_app(callback)
        self.cast_transport = "vlc"
        self.play_task = asyncio.create_task(
            self._wait_for_vlc_playback(position_seconds)
        )
        await asyncio.sleep(0.75)
        if self.play_task.done():
            await self.play_task

    async def _wait_for_vlc_playback(self, position_seconds: float = 0) -> None:
        if self.atv is None:
            raise RuntimeError("Apple TV disconnected before VLC playback started")
        await self._wait_until_playback_started()
        idle_samples = 0
        confirmed_at = self.loop.time()
        if position_seconds > 0:
            try:
                await self.atv.remote_control.set_position(position_seconds)
            except Exception:
                self.log.info("VLC did not accept the requested resume position")
        while True:
            await asyncio.sleep(1)
            playing = await self._playing_with_fallback()
            if self._is_terminal_state(playing, confirmed_at):
                idle_samples += 1
                if idle_samples >= 2:
                    return
            else:
                idle_samples = 0

    @staticmethod
    def _is_natural_end(playing: Any) -> bool:
        if playing.device_state != DeviceState.Paused:
            return False
        try:
            position = float(playing.position)
            duration = float(playing.total_time)
        except (TypeError, ValueError):
            return False
        return duration > 0 and position >= max(0.0, duration - 1.0)

    def _is_terminal_state(self, playing: Any, confirmed_at: float) -> bool:
        if playing.device_state in {DeviceState.Idle, DeviceState.Stopped}:
            return True
        if self._user_paused or playing.device_state != DeviceState.Paused:
            return False
        if self._is_natural_end(playing):
            return True
        try:
            position = float(playing.position)
            duration = float(playing.total_time)
        except (TypeError, ValueError):
            return False
        # Some tvOS URL sessions reset metadata position to zero when the
        # final frame is reached. Only accept that receiver quirk after the
        # known duration has elapsed, and never after an app-requested pause.
        elapsed = max(0.0, self.loop.time() - confirmed_at)
        return (
            duration > 0
            and position <= 1.0
            and elapsed >= max(2.0, duration - 1.0)
        )

    def _receiver_requested_media_data(self) -> bool:
        """Return whether the receiver fetched playable bytes from our server."""
        if self.hls_runner is None:
            return True
        return bool(self._media_request_event and self._media_request_event.is_set())

    async def _wait_until_playback_started(
        self, playback_task: asyncio.Task | None = None
    ) -> None:
        """Require receiver state and a real local-media fetch before success."""
        started_waiting_at = asyncio.get_running_loop().time()
        deadline = started_waiting_at + self.PLAYBACK_START_TIMEOUT_SECONDS
        receiver_playing = False
        last_metadata_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            if playback_task is not None and playback_task.done():
                if playback_task.cancelled():
                    raise RuntimeError(
                        "The AirPlay receiver cancelled playback before it started"
                    )
                task_error = playback_task.exception()
                if task_error is not None:
                    raise task_error
            if self._metadata_available:
                try:
                    playing = await self._playing()
                    last_metadata_error = None
                    receiver_playing = (
                        playing.device_state == DeviceState.Playing
                    )
                except Exception as error:
                    last_metadata_error = error
                    receiver_playing = False
            else:
                # Stand-alone TV implementations expose AirPlay video but no
                # Companion/MRP metadata. A pending URL task or live queue
                # session proves that the receiver accepted the command; for
                # local media, also require an actual video-byte request.
                receiver_playing = (
                    (
                        playback_task is not None
                        and not playback_task.done()
                    )
                    or (
                        playback_task is None
                        and self.modern_session is not None
                        and self._receiver_compat_playback
                    )
                ) and self.loop.time() - started_waiting_at >= (
                    self.METADATALESS_START_GRACE_SECONDS
                )
            if receiver_playing and self._receiver_requested_media_data():
                # Seed the push cache with the directly confirmed state so a
                # pre-command Idle notification cannot immediately look like
                # a natural end before the next receiver push arrives.
                if self._metadata_available:
                    self._push_playing = playing
                    self._push_updated_at = self.loop.time()
                else:
                    self._estimated_started_at = self.loop.time()
                self.log.info(
                    "Cast playback confirmed: transport=%s media_fetch=%s",
                    self.cast_transport or "airplay",
                    "yes" if self.hls_runner is not None else "external",
                )
                return
            remaining = deadline - asyncio.get_running_loop().time()
            await asyncio.sleep(
                min(self.PLAYBACK_START_POLL_SECONDS, max(0.0, remaining))
            )

        if self.hls_runner is not None and not self._receiver_requested_media_data():
            playlist_seen = any(
                request.casefold().endswith(".m3u8")
                for request in self.hls_requests
            )
            if playlist_seen:
                raise RuntimeError(
                    "The AirPlay receiver opened the playlist but never requested video data. "
                    "Retry the cast; if it repeats, restart the receiver and check the "
                    "diagnostic log."
                )
            raise RuntimeError(
                "The AirPlay receiver accepted the cast but never connected to this PC's media "
                "server. Keep both devices on the same private network and allow "
                "Violet Relay through Windows Firewall."
            )
        if last_metadata_error is not None:
            raise RuntimeError(
                "The AirPlay receiver could not confirm that playback started: "
                f"{last_metadata_error}"
            ) from last_metadata_error
        raise RuntimeError(
            "The AirPlay receiver accepted the media queue but did not start playback"
        )

    def _supports_playback_metadata(self) -> bool:
        """Return whether the connected receiver can report playback state."""
        if self.atv is None:
            return False
        features = getattr(self.atv, "features", None)
        if features is None:
            # Keep compatibility with older pyatv facades and lightweight test
            # doubles where feature discovery is not exposed.
            return True
        try:
            # An idle Apple TV's MRP Position is Unavailable until playback
            # starts. Built-in TVs expose the same state through RAOP, which
            # only tracks audio sent by pyatv and stays Idle during our video
            # cast. Preserve media-fetch confirmation for those receivers.
            return features.in_state(
                FeatureState.Available, FeatureName.Position
            ) or (
                not self._receiver_compat_playback
                and features.in_state(
                    FeatureState.Unavailable, FeatureName.Position
                )
            )
        except Exception:
            return True

    @staticmethod
    def _is_third_party_video_receiver(config: Any, airplay_service: Any) -> bool:
        if airplay_service is None:
            return False
        device_info = getattr(config, "device_info", None)
        raw_model = str(
            getattr(device_info, "raw_model", "")
            or getattr(airplay_service, "properties", {}).get("model", "")
        )
        return bool(raw_model) and not raw_model.replace(" ", "").startswith(
            "AppleTV"
        )

    async def _serve_hls(self, directory: Path, device_address: str) -> str:
        directory = directory.resolve()
        return await self._serve_directory(directory, "index.m3u8", device_address)

    async def _serve_file(self, path: Path, device_address: str) -> str:
        path = path.resolve()
        return await self._serve_directory(path.parent, path.name, device_address)

    async def _serve_directory(
        self, directory: Path, entry_name: str, device_address: str
    ) -> str:
        token = secrets.token_urlsafe(18)
        entry = (directory / entry_name).resolve()
        if entry.parent != directory or not entry.is_file():
            raise FileNotFoundError(
                f"Prepared media is no longer available: {entry_name}"
            )
        requests: list[str] = []
        media_request_event = asyncio.Event()
        app = web.Application()

        async def file_handler(request: web.Request) -> web.StreamResponse:
            relative = request.match_info.get("filename", "")
            requests.append(relative)
            self.log.debug(
                "AirPlay media request: method=%s asset=%s range=%s",
                request.method,
                relative,
                request.headers.get("Range", "none"),
            )
            target = (directory / relative).resolve()
            if target.parent != directory:
                raise web.HTTPNotFound()
            if not target.is_file():
                segment_match = _HLS_SEGMENT_NAME.fullmatch(target.name)
                if segment_match is not None:
                    requested_index = int(segment_match.group(1))
                    produced_indices = [
                        int(match.group(1))
                        for path in directory.glob("segment_*.m4s")
                        if (match := _HLS_SEGMENT_NAME.fullmatch(path.name))
                    ]
                    # A complete VOD manifest advertises the whole movie while
                    # FFmpeg remains about 30 seconds ahead. Wait briefly for a
                    # future segment's atomic rename instead of racing it with
                    # a transient 404. Missing prefix segments are from before
                    # this seek and must fail immediately if ever requested.
                    if not produced_indices or requested_index >= min(produced_indices):
                        deadline = asyncio.get_running_loop().time() + 8.0
                        while (
                            not target.is_file()
                            and asyncio.get_running_loop().time() < deadline
                        ):
                            await asyncio.sleep(0.05)
            if not target.is_file():
                raise web.HTTPNotFound()
            content_types = {
                ".m3u8": "application/vnd.apple.mpegurl",
                ".m4s": "video/iso.segment",
                ".mp4": "video/mp4",
                ".m4v": "video/mp4",
                ".mov": "video/quicktime",
            }
            headers = {
                "Cache-Control": "no-cache" if target.suffix.lower() == ".m3u8" else "public, max-age=3600",
                "Content-Type": content_types.get(
                    target.suffix.lower(),
                    mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                ),
                "Accept-Ranges": "bytes",
            }
            if (
                request.method == "GET"
                and target.suffix.casefold() != ".m3u8"
            ):
                media_request_event.set()
                if len(requests) <= 4:
                    self.log.info(
                        "AirPlay receiver requested playable media data: asset=%s",
                        target.suffix.casefold() or "file",
                    )
            return _LargeFileResponse(target, headers=headers)

        app.router.add_get(f"/{token}/{{filename:.*}}", file_handler)
        runner = web.AppRunner(app, access_log=None)
        try:
            await runner.setup()
            bind_address = "::" if self._is_ipv6(device_address) else "0.0.0.0"
            site = web.TCPSite(runner, bind_address, 0)
            await site.start()
            server = getattr(site, "_server", None)
            sockets = list(getattr(server, "sockets", []) or [])
            if not sockets:
                raise RuntimeError("Unable to open the local HLS server")
            port = sockets[0].getsockname()[1]
            local_address = self._local_address_for(device_address)
        except Exception:
            await runner.cleanup()
            raise
        self.hls_runner = runner
        self.hls_requests = requests
        self._media_request_event = media_request_event
        self._served_entry_name = entry_name
        url_address = f"[{local_address}]" if ":" in local_address else local_address
        self.log.info(
            "Local cast server ready: address=%s port=%d entry=%s",
            local_address,
            port,
            Path(entry_name).suffix.casefold() or "file",
        )
        return f"http://{url_address}:{port}/{token}/{quote(entry_name)}"

    @staticmethod
    def _is_ipv6(address: str) -> bool:
        try:
            return ipaddress.ip_address(address).version == 6
        except ValueError:
            return ":" in address

    @staticmethod
    def _local_address_for(device_address: str) -> str:
        family = socket.AF_INET6 if AirPlayService._is_ipv6(device_address) else socket.AF_INET
        probe = socket.socket(family, socket.SOCK_DGRAM)
        try:
            try:
                probe.connect((device_address, 7000))
            except OSError as error:
                raise RuntimeError(
                    "No local network route to the AirPlay receiver is available"
                ) from error
            return str(probe.getsockname()[0])
        finally:
            probe.close()

    async def _stop_hls_server(self) -> None:
        runner = self.hls_runner
        self.hls_runner = None
        self._media_request_event = None
        self._served_entry_name = ""
        if runner is not None:
            await runner.cleanup()

    async def command(self, name: str, value: float | None = None) -> None:
        if self.atv is None:
            raise RuntimeError("No AirPlay cast is active")
        if not self._metadata_available and name != "stop":
            raise RuntimeError(
                "This AirPlay receiver does not expose playback controls; "
                "use Stop casting or Continue here"
            )
        remote = self.atv.remote_control
        if name == "seek":
            await asyncio.wait_for(
                remote.set_position(float(value or 0)), timeout=10
            )
        else:
            action = getattr(remote, name, None)
            if action is None:
                raise RuntimeError(f"The AirPlay receiver does not expose the {name} command")
            await asyncio.wait_for(action(), timeout=10)
            if name == "pause":
                self._user_paused = True
            elif name in {"play", "play_pause"}:
                self._user_paused = False

    async def _playing(self):
        if self.atv is None:
            raise RuntimeError("No AirPlay cast is active")
        return await asyncio.wait_for(self.atv.metadata.playing(), timeout=5)

    def _start_push_updates(self) -> None:
        self._push_playing = None
        self._push_updated_at = 0.0
        updater = getattr(self.atv, "push_updater", None)
        if updater is None:
            return
        try:
            listener = _PushListener(self)
            updater.listener = listener
            updater.start(initial_delay=0)
            self._push_listener = listener
            self.log.info("AirPlay push metadata enabled")
        except Exception:
            self._push_listener = None
            self.log.info(
                "AirPlay push metadata unavailable; using polling",
                exc_info=True,
            )

    def _stop_push_updates(self) -> None:
        updater = getattr(self.atv, "push_updater", None)
        if updater is not None:
            try:
                updater.stop()
                updater.listener = None
            except Exception:
                self.log.debug("Push metadata cleanup failed", exc_info=True)
        self._push_listener = None
        self._push_playing = None
        self._push_updated_at = 0.0

    async def _playing_with_fallback(self):
        if (
            self._push_playing is not None
            and self.loop.time() - self._push_updated_at <= 3.0
        ):
            return self._push_playing
        return await self._playing()

    def _receiver_volume(self) -> tuple[float | None, bool]:
        if self.atv is None:
            return None, False
        features = getattr(self.atv, "features", None)
        audio = getattr(self.atv, "audio", None)
        if features is None or audio is None:
            return None, False
        try:
            available = features.in_state(
                FeatureState.Available, FeatureName.SetVolume
            )
            if not available:
                return None, False
            volume = float(audio.volume)
            return max(0.0, min(100.0, volume)), True
        except Exception:
            return None, False

    async def set_volume(self, level: float) -> None:
        _volume, available = self._receiver_volume()
        if self.atv is None or not available:
            raise RuntimeError(
                "The AirPlay receiver does not expose volume control for this output"
            )
        await asyncio.wait_for(
            self.atv.audio.set_volume(max(0.0, min(100.0, float(level)))),
            timeout=10,
        )

    async def status(self) -> CastStatus:
        if self.atv is None:
            return CastStatus("idle", 0, 0)
        if self.play_task and self.play_task.done():
            if self.play_task.cancelled():
                return CastStatus("stopped", 0, 0)
            error = self.play_task.exception()
            if error:
                return CastStatus(
                    "error", 0, 0, error_message(error, "AirPlay playback failed")
                )
            return CastStatus("stopped" if self.explicit_stop else "ended", 0, 0)
        if not self._metadata_available:
            elapsed = (
                max(0.0, self.loop.time() - self._estimated_started_at)
                if self._estimated_started_at > 0
                else 0.0
            )
            position = self._estimated_start_position + elapsed
            if self._estimated_duration > 0:
                position = min(position, self._estimated_duration)
            return CastStatus(
                "playing",
                int(position),
                int(self._estimated_duration),
            )
        try:
            playing = await self._playing_with_fallback()
            self._status_failures = 0
            state = "playing"
            if playing.device_state == DeviceState.Paused:
                state = "paused"
            elif playing.device_state in {DeviceState.Idle, DeviceState.Stopped}:
                state = "buffering"
            volume, can_set_volume = self._receiver_volume()
            return CastStatus(
                state,
                int(playing.position or 0),
                int(playing.total_time or 0),
                receiver_volume=volume,
                can_set_volume=can_set_volume,
            )
        except Exception as error:
            self._status_failures += 1
            self.log.info(
                "Unable to poll cast metadata (%d/3): %s",
                self._status_failures,
                error,
            )
            if self._status_failures >= 3:
                return CastStatus(
                    "error",
                    0,
                    0,
                    "Lost connection to the AirPlay receiver. Retry casting or continue locally.",
                )
            return CastStatus("playing", 0, 0)

    async def stop_cast(self) -> None:
        self.explicit_stop = True
        if self.atv is not None and not (
            self.modern_session is not None and self._receiver_compat_playback
        ):
            try:
                await asyncio.wait_for(self.atv.remote_control.stop(), timeout=5)
            except Exception:
                self.log.info("AirPlay receiver did not acknowledge the stop command")
        if self.play_task is not None and not self.play_task.done():
            self.play_task.cancel()
            try:
                await self.play_task
            except (asyncio.CancelledError, Exception):
                pass
        self.play_task = None
        modern_session = self.modern_session
        self.modern_session = None
        if modern_session is not None:
            try:
                await modern_session.stop()
                await modern_session.close()
            except Exception:
                self.log.warning("Modern AirPlay session cleanup failed", exc_info=True)
        if self.atv is not None:
            atv = self.atv
            self._stop_push_updates()
            self.atv = None
            try:
                pending = atv.close()
                if pending:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True), timeout=5
                    )
            except Exception:
                self.log.warning("AirPlay connection cleanup failed", exc_info=True)
        self.cast_transport = ""
        self._user_paused = False
        self._status_failures = 0
        self._metadata_available = True
        self._estimated_started_at = 0.0
        self._estimated_start_position = 0.0
        self._estimated_duration = 0.0
        self._receiver_compat_playback = False
        try:
            await self._stop_hls_server()
        except Exception:
            self.log.warning("Local media server cleanup failed", exc_info=True)

    async def close(self) -> None:
        await self._close_pairing_safely()
        await self.stop_cast()
        try:
            await self.storage.save()
        except Exception:
            self.log.warning("Pairing credentials could not be saved", exc_info=True)
