from __future__ import annotations

import asyncio
import logging
import plistlib
import random
import secrets
import socket
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pyatv.auth.hap_channel import setup_channel
from pyatv.auth.hap_pairing import parse_credentials
from pyatv.protocols.airplay.auth import verify_connection
from pyatv.protocols.airplay.channels import EventChannel
from pyatv.protocols.raop.protocols import StreamContext
from pyatv.protocols.raop.protocols.airplayv2 import (
    AirPlayV2,
    EVENTS_READ_INFO,
    EVENTS_SALT,
    EVENTS_WRITE_INFO,
)
from pyatv.support.http import decode_bplist_from_body, http_connect
from pyatv.support.rtsp import RtspSession


SOURCE_VERSION = "960.10.1"
SENDER_OS_NAME = "iPhone OS"
SENDER_OS_VERSION = "26.0"
SENDER_OS_BUILD = "23A341"
SENDER_MODEL = "iPhone18,1"
RCS_CLIENT_TYPE = "A6B27562-B43A-4F2D-B75F-82391E250194"


def _uuid() -> str:
    return str(uuid4()).upper()


def _sender_mac() -> str:
    value = bytearray(secrets.token_bytes(6))
    value[0] = (value[0] | 0x02) & 0xFE
    return ":".join(f"{part:02X}" for part in value)


def build_setup_body(
    local_ip: str,
    session_uuid: str,
    correlation_uuid: str,
    sender_mac: str,
) -> dict[str, Any]:
    peer = {
        "ID": correlation_uuid,
        "Addresses": [local_ip],
        "DeviceType": 0,
        "SupportsClockPortMatchingOverride": True,
    }
    return {
        "name": "Violet Relay",
        "updateSessionRequest": False,
        "statsCollectionEnabled": False,
        "sessionUUID": session_uuid,
        # AirPlay TV implementations use the Apple sender identity to select
        # their presentation scale. Mixing an iPhone model with a Windows OS
        # leaves some 4K receivers at a 1x scale on a 2x (1920 -> 3840) canvas.
        "osName": SENDER_OS_NAME,
        "timingProtocol": "PTP",
        "isScreenMirroringSession": False,
        "osBuildVersion": SENDER_OS_BUILD,
        "sourceVersion": SOURCE_VERSION,
        "osVersion": SENDER_OS_VERSION,
        "timingPeerInfo": peer,
        "isMultiSelectAirPlay": False,
        "timingPeerList": [peer],
        "internalBuild": False,
        "sessionCorrelationUUID": correlation_uuid,
        "deviceID": sender_mac,
        "diagnosticsAndUsage": False,
        "model": SENDER_MODEL,
        "macAddress": sender_mac,
    }


def build_insert_command(
    url: str,
    position_seconds: float,
    item_uuid: str,
    sender_mac: str = "",
    item_after_uuid: str = "",
) -> dict[str, Any]:
    timescale = 1000
    is_hls = urlsplit(url).path.casefold().endswith(".m3u8")
    command = {
        "type": "insertPlayQueueItem",
        "item": {
            "uuid": item_uuid,
            "playerItemLoggingID": "I/PWI.01",
            "playbackRestrictions": 0,
            "supportsIntegratedTimeline": False,
            # AirPlayReceiverKit and CoreMedia use both spellings in their URL
            # playback layers. Be explicit so built-in TV web players do not
            # classify an opaque local URL as an audio-only/auxiliary item.
            "isAudioOnly": False,
            "audioOnly": False,
            "mediaType": "file",
            "streamType": 1,
            "rate": 1.0,
            "volume": 1.0,
            "mightSupportStorePastisKeyRequests": True,
            "playerLoggingID": "P/II",
            "allowedCommonMediaClientDataKeys": 0,
            "audioMode": "default",
            "referenceRestrictions": 3,
            "clientBundleID": "app.violetrelay.player",
            "clientProcName": "Violet Relay",
            "model": SENDER_MODEL,
            "osBuildVersion": SENDER_OS_BUILD,
            "Content-Location": url,
            # The receiver uses this key—not the URL suffix—to select its
            # HLS/MSE player. Without it, a playlist is misrouted through the
            # progressive-file player and no media segments are requested.
            **({"HLS-Content-Location": url} if is_hls else {}),
            "snapTimeToPausePlayback": False,
            "Start-Position": {
                "flags": 1,
                "value": int(max(position_seconds, 0) * timescale),
                "epoch": 0,
                "timescale": timescale,
            },
            **({"SenderMACAddress": sender_mac} if sender_mac else {}),
        },
    }
    if item_after_uuid:
        command["itemAfter"] = {"uuid": item_after_uuid}
    return command


def build_end_policy_command(value: int = 1) -> dict[str, Any]:
    # The RCS queue protocol on the hardware-tested tvOS 26 receiver requires
    # value 1 for URL playback to start. Receiver completion is normalized by
    # AirPlayService so the Windows session queue can still auto-advance.
    return {
        "type": "setProperty",
        "property": "actionAtItemEnd",
        "value": value,
    }


def build_playback_stream_body() -> dict[str, Any]:
    """Declare URL playback so TVs allocate their full-screen video surface."""
    return {"streams": [{"type": 120}]}


class ModernAirPlaySession:
    """tvOS 26 URL playback using the current AirPlay 2 queue command."""

    def __init__(
        self,
        config: Any,
        service: Any,
        logger: logging.Logger,
        receiver_compatibility: bool = False,
    ):
        self.config = config
        self.service = service
        self.log = logger
        self.receiver_compatibility = receiver_compatibility
        self.connection: Any | None = None
        self.rtsp: RtspSession | None = None
        self.protocol: AirPlayV2 | None = None
        self.item_uuid = ""
        self._stream_headers: dict[str, str] = {}
        self._receiver_stream_id = "1"
        self._sender_mac_address = ""
        self.replacement_indeterminate = False

    @staticmethod
    def _require_ok(response: Any, operation: str) -> None:
        if response.code != 200:
            raise RuntimeError(f"Modern AirPlay {operation} failed with status {response.code}")

    async def _event_channel(self, event_port: int) -> None:
        if (
            self.protocol is None
            or self.protocol._verifier is None
            or self.connection is None
        ):
            raise RuntimeError("Modern AirPlay event channel is not initialized")
        for attempt in range(5):
            try:
                transport, _ = await setup_channel(
                    EventChannel,
                    self.protocol._verifier,
                    self.connection.remote_ip,
                    event_port,
                    EVENTS_SALT,
                    EVENTS_READ_INFO,
                    EVENTS_WRITE_INFO,
                )
                self.protocol.event_channel = transport
                return
            except ConnectionRefusedError:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.2)

    async def _command(self, payload: dict[str, Any]) -> Any:
        if self.rtsp is None:
            raise RuntimeError("Modern AirPlay command channel is not initialized")
        nested = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
        # Apple TV acknowledges the hyphenated TV SDK header with HTTP 200
        # but never starts the queue item. Its RCS endpoint requires the
        # original StreamID spelling, without the TV session headers.
        headers = (
            self._stream_headers or {"X-Apple-Stream-ID": "1"}
            if self.receiver_compatibility
            else {"X-Apple-StreamID": "1"}
        )

        async def send(command_headers: dict[str, str]) -> Any:
            return await self.rtsp.exchange(
                "POST",
                uri="/command",
                headers=command_headers,
                body={"params": {"data": nested}},
                allow_error=True,
            )

        response = await send(headers)
        if response.code != 200 and self.receiver_compatibility:
            # Hisense's AirPlay SDK rejects session/protocol headers on the
            # queue endpoint. Negotiate the two stream-header spellings used
            # by Apple receivers and third-party TV firmware.
            for candidate in (
                {"X-Apple-Stream-ID": self._receiver_stream_id},
                {},
                {"X-Apple-StreamID": self._receiver_stream_id},
            ):
                if candidate == headers:
                    continue
                candidate_response = await send(candidate)
                if candidate_response.code == 200:
                    self._stream_headers = candidate
                    self.log.info(
                        "Built-in TV selected AirPlay command headers: %s",
                        ",".join(candidate),
                    )
                    response = candidate_response
                    break
                response = candidate_response
        self._require_ok(response, str(payload.get("type", "command")))
        return response

    async def start(self, url: str, position_seconds: float = 0) -> None:
        try:
            async with asyncio.timeout(30):
                await self._start(url, position_seconds)
        except BaseException:
            try:
                await self.close()
            except Exception:
                self.log.warning(
                    "Modern AirPlay cleanup failed after timeout",
                    exc_info=True,
                )
            raise

    async def _start(self, url: str, position_seconds: float = 0) -> None:
        credentials = parse_credentials(self.service.credentials)
        self.connection = await http_connect(str(self.config.address), self.service.port)
        self.rtsp = RtspSession(self.connection)
        context = StreamContext()
        context.credentials = credentials
        self.protocol = AirPlayV2(context, self.rtsp)

        local_ip = self.connection.local_ip
        session_uuid = _uuid()
        correlation_uuid = _uuid()
        sender_mac = _sender_mac()
        self._sender_mac_address = sender_mac
        group_id = self.service.properties.get("gid", "")
        receiver_id = self.service.properties.get(
            "psi", self.service.properties.get("pi", "")
        )
        self._stream_headers = {
            "X-Apple-ProtocolVersion": "1",
            "X-Apple-Session-ID": session_uuid.lower(),
            "X-Apple-Stream-ID": "1",
        }

        try:
            self.protocol._verifier = await verify_connection(credentials, self.connection)
            response = await self.rtsp.setup(
                body=build_setup_body(
                    local_ip,
                    session_uuid,
                    correlation_uuid,
                    sender_mac,
                )
            )
            self._require_ok(response, "session setup")
            setup_data = decode_bplist_from_body(response)
            try:
                event_port = int(setup_data["eventPort"])
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError(
                    "Modern AirPlay session setup omitted its event port"
                ) from error
            await self._event_channel(event_port)
            receiver_info = await self.rtsp.info()
            if self.receiver_compatibility:
                displays = receiver_info.get("displays", [])
                playback = receiver_info.get("playbackCapabilities", {})
                self.log.info(
                    "Built-in TV AirPlay capabilities: displays=%s playback=%s",
                    displays,
                    playback,
                )
            self._require_ok(await self.rtsp.record(), "record")

            peer_response = await self.rtsp.exchange(
                "SETPEERSX",
                content_type="/peer-list-changed-x",
                body=plistlib.dumps(
                    [
                        {
                            "ID": correlation_uuid,
                            "Addresses": [local_ip],
                            "ClockID": random.randrange(1, 2**63),
                            "DeviceType": 0,
                            "ClockPorts": {group_id or receiver_id: 32768},
                            "SupportsClockPortMatchingOverride": True,
                        }
                    ],
                    fmt=plistlib.FMT_BINARY,
                ),
                allow_error=True,
            )
            if peer_response.code != 200 and not (
                self.receiver_compatibility and peer_response.code in {404, 501}
            ):
                self._require_ok(peer_response, "peer setup")
            elif peer_response.code != 200:
                self.log.info(
                    "AirPlay receiver skipped optional peer setup: status=%d",
                    peer_response.code,
                )
            await self.protocol.start_feedback()

            if self.receiver_compatibility:
                playback_response = await self.rtsp.setup(
                    headers=self._stream_headers,
                    body=build_playback_stream_body(),
                )
                self._require_ok(playback_response, "playback stream setup")
                self.log.info(
                    "Built-in TV playback stream: %s",
                    decode_bplist_from_body(playback_response),
                )
            else:
                rtcp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    rtcp_socket.bind((local_ip, 0))
                    audio_response = await self.rtsp.setup(
                        body={
                            "streams": [
                                {
                                    "audioFormat": 262144,
                                    "supportsDynamicStreamID": True,
                                    "streamConnectionID": random.randrange(1, 2**63),
                                    "ct": 2,
                                    "audioMode": "default",
                                    "spf": 352,
                                    "isMedia": True,
                                    "latencyMax": 88200,
                                    "type": 96,
                                    "sr": 44100,
                                    "latencyMin": 11025,
                                    "streamConnections": {
                                        "streamConnectionTypeRTP": {
                                            "streamConnectionKeyUseStreamEncryptionKey": True
                                        },
                                        "streamConnectionTypeMediaDataControl": {
                                            "streamConnectionKeyEncryptionSeed": random.randrange(
                                                -(2**63), 2**63
                                            )
                                        },
                                        "streamConnectionTypeRTCP": {
                                            "streamConnectionKeyPort": rtcp_socket.getsockname()[1]
                                        },
                                    },
                                }
                            ]
                        }
                    )
                    self._require_ok(audio_response, "media stream setup")
                finally:
                    rtcp_socket.close()

            control_response = await self.rtsp.setup(
                headers=(self._stream_headers if self.receiver_compatibility else None),
                body={
                    "streams": [
                        {
                            "clientUUID": _uuid(),
                            "clientTypeUUID": RCS_CLIENT_TYPE,
                            "channelID": f"{receiver_id}-RCS-1",
                            "controlType": 1,
                            "type": 130,
                        }
                    ]
                }
            )
            self._require_ok(control_response, "control stream setup")
            control_data = decode_bplist_from_body(control_response)
            if self.receiver_compatibility:
                self.log.info("Built-in TV control stream: %s", control_data)
                try:
                    assigned_stream_id = control_data["streams"][0]["streamID"]
                except (KeyError, IndexError, TypeError):
                    pass
                else:
                    self._receiver_stream_id = str(assigned_stream_id)

            self.item_uuid = _uuid()
            await self._command(
                build_insert_command(
                    url,
                    position_seconds,
                    self.item_uuid,
                    sender_mac,
                )
            )
            await self._command(build_end_policy_command())
            await self._command({"type": "setRate", "rate": 1.0})
        except Exception:
            try:
                await self.close()
            except Exception:
                self.log.warning(
                    "Modern AirPlay cleanup failed after startup error",
                    exc_info=True,
                )
            raise

    async def replace(self, url: str, position_seconds: float = 0) -> None:
        """Replace the active queue item without tearing down the RCS session."""
        if self.rtsp is None or not self.item_uuid:
            raise RuntimeError("Modern AirPlay queue replacement is not available")

        old_item_uuid = self.item_uuid
        new_item_uuid = _uuid()
        inserted = False
        self.replacement_indeterminate = False
        try:
            # Third-party receiver web players only detach the current media
            # cleanly when removing it advances to an item already queued
            # immediately after it. Keep this transition on the existing RCS
            # stream so a seek cannot race an unacknowledged RTSP teardown.
            await self._command({"type": "setRate", "rate": 0.0})
            await self._command(build_end_policy_command(0))
            await self._command(
                build_insert_command(
                    url,
                    position_seconds,
                    new_item_uuid,
                    self._sender_mac_address,
                    item_after_uuid=old_item_uuid,
                )
            )
            inserted = True
            # From here until remove OLD is acknowledged, either item can be
            # current if the receiver returns an ambiguous error. Do not issue
            # destructive rollback commands without a current-item event.
            self.replacement_indeterminate = True
            await self._command(
                {
                    "type": "removePlayQueueItem",
                    "item": {"uuid": old_item_uuid},
                }
            )
            self.item_uuid = new_item_uuid
            self.replacement_indeterminate = False
        except Exception:
            if not inserted:
                try:
                    await self._command(build_end_policy_command())
                    await self._command({"type": "setRate", "rate": 1.0})
                except Exception:
                    self.log.info(
                        "Modern AirPlay could not resume after replacement failure"
                    )
            raise

        # remove-current with Advance already starts NEW. Normalize the rate;
        # the service restores stop-at-end after it observes NEW media fetches.
        try:
            await self._command({"type": "setRate", "rate": 1.0})
        except Exception:
            self.log.info("Modern AirPlay did not acknowledge replacement rate 1")

    async def finish_replacement(self) -> None:
        """Restore the normal one-item end policy after NEW starts fetching."""
        if self.rtsp is None or not self.item_uuid:
            return
        try:
            await self._command(build_end_policy_command())
        except Exception:
            # Advance is safe for a one-item queue and should not turn an
            # otherwise successful seek into a playback failure.
            self.log.info("Modern AirPlay did not restore the queue end policy")

    async def stop(self) -> None:
        """Stop the active queue item while the RCS command channel is alive."""
        if self.rtsp is None or not self.item_uuid:
            return
        try:
            await self._command({"type": "setRate", "rate": 0.0})
        except Exception:
            self.log.info("Modern AirPlay receiver did not acknowledge setRate 0")
        if self.receiver_compatibility:
            try:
                await self._command(build_end_policy_command(0))
            except Exception:
                self.log.info(
                    "Built-in TV did not acknowledge queue cleanup policy"
                )

    async def close(self) -> None:
        protocol = self.protocol
        rtsp = self.rtsp
        connection = self.connection
        self.protocol = None
        self.connection = None
        self.rtsp = None
        self.item_uuid = ""
        self._stream_headers = {}
        self._receiver_stream_id = "1"
        self._sender_mac_address = ""
        self.replacement_indeterminate = False
        if rtsp is not None:
            try:
                await rtsp.teardown(rtsp.session_id)
            except Exception:
                self.log.info("Modern AirPlay receiver did not acknowledge teardown")
        if protocol is not None:
            try:
                protocol.teardown()
            except Exception:
                self.log.warning("AirPlay protocol teardown failed", exc_info=True)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                self.log.warning("AirPlay socket close failed", exc_info=True)
