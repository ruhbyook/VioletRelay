from __future__ import annotations

import asyncio
import logging
import plistlib
import random
import secrets
import socket
from typing import Any
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
        "name": "xMediaPlayerx",
        "updateSessionRequest": False,
        "statsCollectionEnabled": False,
        "sessionUUID": session_uuid,
        "osName": "Windows",
        "timingProtocol": "PTP",
        "osBuildVersion": "Windows 11",
        "sourceVersion": SOURCE_VERSION,
        "osVersion": "11",
        "timingPeerInfo": peer,
        "isMultiSelectAirPlay": False,
        "timingPeerList": [peer],
        "internalBuild": False,
        "sessionCorrelationUUID": correlation_uuid,
        "deviceID": sender_mac,
        "diagnosticsAndUsage": False,
        "model": "iPhone18,1",
        "macAddress": sender_mac,
    }


def build_insert_command(url: str, position_seconds: float, item_uuid: str) -> dict[str, Any]:
    timescale = 1000
    return {
        "type": "insertPlayQueueItem",
        "item": {
            "uuid": item_uuid,
            "playerItemLoggingID": "I/PWI.01",
            "playbackRestrictions": 0,
            "supportsIntegratedTimeline": False,
            "mediaType": "file",
            "playerLoggingID": "P/II",
            "allowedCommonMediaClientDataKeys": 0,
            "audioMode": "default",
            "referenceRestrictions": 3,
            "clientBundleID": "app.xmediaplayerx.player",
            "clientProcName": "xMediaPlayerx",
            "Content-Location": url,
            "snapTimeToPausePlayback": False,
            "Start-Position": {
                "flags": 1,
                "value": int(max(position_seconds, 0) * timescale),
                "epoch": 0,
                "timescale": timescale,
            },
        },
    }


def build_end_policy_command() -> dict[str, Any]:
    # The RCS queue protocol on the hardware-tested tvOS 26 receiver requires
    # value 1 for URL playback to start. Receiver completion is normalized by
    # AirPlayService so the Windows session queue can still auto-advance.
    return {
        "type": "setProperty",
        "property": "actionAtItemEnd",
        "value": 1,
    }


class ModernAirPlaySession:
    """tvOS 26 URL playback using the current AirPlay 2 queue command."""

    def __init__(self, config: Any, service: Any, logger: logging.Logger):
        self.config = config
        self.service = service
        self.log = logger
        self.connection: Any | None = None
        self.rtsp: RtspSession | None = None
        self.protocol: AirPlayV2 | None = None
        self.item_uuid = ""

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

    async def _command(self, payload: dict[str, Any]) -> None:
        if self.rtsp is None:
            raise RuntimeError("Modern AirPlay command channel is not initialized")
        nested = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
        response = await self.rtsp.exchange(
            "POST",
            uri="/command",
            headers={"X-Apple-StreamID": "1"},
            body={"params": {"data": nested}},
            allow_error=True,
        )
        self._require_ok(response, str(payload.get("type", "command")))

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
        group_id = self.service.properties.get("gid", "")
        receiver_id = self.service.properties.get(
            "psi", self.service.properties.get("pi", "")
        )

        try:
            self.protocol._verifier = await verify_connection(credentials, self.connection)
            response = await self.rtsp.setup(
                body=build_setup_body(
                    local_ip, session_uuid, correlation_uuid, sender_mac
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
            await self.rtsp.info()
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
            self._require_ok(peer_response, "peer setup")
            await self.protocol.start_feedback()

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

            self.item_uuid = _uuid()
            await self._command(build_insert_command(url, position_seconds, self.item_uuid))
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

    async def close(self) -> None:
        protocol = self.protocol
        connection = self.connection
        self.protocol = None
        self.connection = None
        self.rtsp = None
        self.item_uuid = ""
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
