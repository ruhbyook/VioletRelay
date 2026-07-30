from __future__ import annotations

import argparse
import asyncio
import json
import plistlib
import random
import secrets
import socket
from uuid import uuid4

import pyatv
from pyatv.auth.hap_channel import setup_channel
from pyatv.auth.hap_pairing import parse_credentials
from pyatv.const import Protocol
from pyatv.protocols.airplay.auth import verify_connection
from pyatv.protocols.airplay.channels import EventChannel
from pyatv.protocols.raop.protocols import StreamContext
from pyatv.protocols.raop.protocols.airplayv2 import (
    AirPlayV2,
    EVENTS_READ_INFO,
    EVENTS_SALT,
    EVENTS_WRITE_INFO,
)
from pyatv.support.http import http_connect
from pyatv.support.rtsp import RtspSession

from reelferry.paths import AppPaths
from reelferry.services.secure_storage import SecureFileStorage


async def send_command(rtsp: RtspSession, payload: dict) -> int:
    nested = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
    response = await rtsp.exchange(
        "POST",
        uri="/command",
        headers={"X-Apple-StreamID": "1"},
        body={"params": {"data": nested}},
        allow_error=True,
    )
    return response.code


async def run(remote_ip: str, media_url: str, position: float) -> None:
    loop = asyncio.get_running_loop()
    paths = AppPaths.default()
    storage = SecureFileStorage(str(paths.airplay_storage_file), loop)
    await storage.load()
    configs = await pyatv.scan(loop, hosts=[remote_ip], timeout=5, storage=storage)
    if not configs:
        raise RuntimeError(f"Apple TV at {remote_ip} was not found")
    config = configs[0]
    service = config.get_service(Protocol.AirPlay)
    if service is None or not service.credentials:
        raise RuntimeError("AirPlay credentials are missing")

    connection = await http_connect(str(config.address), service.port)
    rtsp = RtspSession(connection)
    context = StreamContext()
    context.credentials = parse_credentials(service.credentials)
    protocol = AirPlayV2(context, rtsp)
    item_uuid = str(uuid4()).upper()
    correlation_uuid = str(uuid4()).upper()
    session_uuid = str(uuid4()).upper()
    client_uuid = str(uuid4()).upper()
    sender_mac = "02:" + ":".join(f"{value:02X}" for value in secrets.token_bytes(5))
    local_ip = connection.local_ip
    group_id = service.properties.get("gid", "")
    receiver_id = service.properties.get("psi", service.properties.get("pi", ""))
    try:
        protocol._verifier = await verify_connection(context.credentials, connection)
        setup_response = await rtsp.setup(
            body={
                "name": "ReelFerry",
                "updateSessionRequest": False,
                "statsCollectionEnabled": False,
                "sessionUUID": session_uuid,
                "osName": "Windows",
                "timingProtocol": "PTP",
                "osBuildVersion": "Windows 11",
                "sourceVersion": "960.10.1",
                "osVersion": "11",
                "timingPeerInfo": {
                    "ID": correlation_uuid,
                    "Addresses": [local_ip],
                    "DeviceType": 0,
                    "SupportsClockPortMatchingOverride": True,
                },
                "isMultiSelectAirPlay": False,
                "timingPeerList": [
                    {
                        "ID": correlation_uuid,
                        "Addresses": [local_ip],
                        "DeviceType": 0,
                        "SupportsClockPortMatchingOverride": True,
                    }
                ],
                "internalBuild": False,
                "sessionCorrelationUUID": correlation_uuid,
                "deviceID": sender_mac,
                "diagnosticsAndUsage": False,
                "model": "iPhone18,1",
                "macAddress": sender_mac,
            }
        )
        setup_data = plistlib.loads(setup_response.body)
        event_port = setup_data["eventPort"]
        protocol.event_channel, _ = await setup_channel(
            EventChannel,
            protocol._verifier,
            connection.remote_ip,
            event_port,
            EVENTS_SALT,
            EVENTS_READ_INFO,
            EVENTS_WRITE_INFO,
        )
        await rtsp.info()
        record = await rtsp.record()
        if record.code != 200:
            raise RuntimeError(f"RECORD failed with status {record.code}")
        await rtsp.exchange(
            "SETPEERSX",
            content_type="/peer-list-changed-x",
            body=plistlib.dumps(
                [
                    {
                        "ID": correlation_uuid,
                        "Addresses": [local_ip],
                        "ClockID": random.randrange(1, 2**63),
                        "DeviceType": 0,
                        "ClockPorts": {group_id: 32768},
                        "SupportsClockPortMatchingOverride": True,
                    }
                ],
                fmt=plistlib.FMT_BINARY,
            ),
        )
        await protocol.start_feedback()

        rtcp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rtcp_socket.bind((local_ip, 0))
        try:
            await rtsp.setup(
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
        finally:
            rtcp_socket.close()

        await rtsp.setup(
            body={
                "streams": [
                    {
                        "clientUUID": client_uuid,
                        "clientTypeUUID": "A6B27562-B43A-4F2D-B75F-82391E250194",
                        "channelID": f"{receiver_id}-RCS-1",
                        "controlType": 1,
                        "type": 130,
                    }
                ]
            }
        )

        timescale = 1000
        insert = {
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
                    "clientBundleID": "app.reelferry.player",
                    "clientProcName": "ReelFerry",
                    "Content-Location": media_url,
                    "snapTimeToPausePlayback": False,
                    "Start-Position": {
                        "flags": 1,
                        "value": int(position * timescale),
                        "epoch": 0,
                        "timescale": timescale,
                    },
                },
            }
        results = {
            "insert": await send_command(rtsp, insert),
            "endAction": await send_command(
                rtsp,
                {"type": "setProperty", "property": "actionAtItemEnd", "value": 1},
            ),
            "rate": await send_command(rtsp, {"type": "setRate", "rate": 1.0}),
        }
        await asyncio.sleep(8)
        print(json.dumps(results))
    finally:
        protocol.teardown()
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the tvOS 26 AirPlay command path")
    parser.add_argument("--remote-ip", required=True, help="Apple TV IPv4 address")
    parser.add_argument("--media-url", required=True, help="Direct HTTP(S) media URL")
    parser.add_argument("--position", type=float, default=0)
    args = parser.parse_args()
    asyncio.run(run(args.remote_ip, args.media_url, args.position))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
