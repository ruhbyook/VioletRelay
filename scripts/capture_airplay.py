from __future__ import annotations

import argparse
import asyncio
from functools import partial
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import socket
from types import SimpleNamespace

import pyatv
from pyatv.const import Protocol
from pyatv.core import mdns
from pyatv.scripts.atvproxy import (
    AirPlayAppleTVProxy,
    publish_airplay_service,
)
from pyatv.protocols.airplay.utils import decode_plist_body, encode_plist_body
from zeroconf import Zeroconf

from xmediaplayerx.paths import AppPaths
from xmediaplayerx.services.secure_storage import SecureFileStorage


class CaptureRedactionFilter(logging.Filter):
    def __init__(self, credential: str):
        super().__init__()
        self.credential = credential

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().replace(self.credential, "<airplay-credentials>")
        if re.search(r"/pair-(?:setup|verify)", message, re.IGNORECASE):
            message = "<AirPlay pairing exchange redacted>"
        message = re.sub(
            r"(https?://[^\s?'\"]+)\?[^\s'\"]+",
            r"\1?<redacted>",
            message,
        )
        record.msg = message
        record.args = ()
        return True


class SntpRelay(asyncio.DatagramProtocol):
    """Relay AirPlay timing datagrams between the receiver and real sender."""

    def __init__(self, receiver_ip: str, sender_ip: str, sender_port: int):
        self.receiver_ip = receiver_ip
        self.sender = (sender_ip, sender_port)
        self.receiver: tuple[str, int] | None = None
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, address: tuple[str, int]) -> None:
        if self.transport is None:
            return
        if address[0] == self.receiver_ip:
            self.receiver = address
            self.transport.sendto(data, self.sender)
        elif address[0] == self.sender[0] and self.receiver is not None:
            self.transport.sendto(data, self.receiver)


class CaptureAirPlayAppleTVProxy(AirPlayAppleTVProxy):
    """AirPlay proxy preserving sender session identity on current tvOS.

    The upstream diagnostic proxy shifts several identifiers so a proxied sender
    can coexist with a direct connection from the same device. tvOS 26 validates
    the session identity fields together and rejects that rewritten SETUP with
    status 400. Our capture has no parallel direct connection, so forwarding the
    original identity is both safe and faithful to the real Apple sender.
    """

    async def _handle_setup_event_channel(self, request, request_data):
        updated_request_data = dict(request_data)
        timing_port = request_data.get("timingPort")
        if request_data.get("timingProtocol") in {"NTP", "SNTP"} and timing_port:
            transport, _ = await self.loop.create_datagram_endpoint(
                lambda: SntpRelay(
                    receiver_ip=self.address,
                    sender_ip=self.client_ip,
                    sender_port=int(timing_port),
                ),
                local_addr=("0.0.0.0", 0),
            )
            relay_port = transport.get_extra_info("sockname")[1]
            updated_request_data["timingPort"] = relay_port
            if not hasattr(self, "_capture_udp_transports"):
                self._capture_udp_transports = []
            self._capture_udp_transports.append(transport)
            logging.getLogger(__name__).debug(
                "SNTP relay: receiver=%s:%d sender=%s:%d",
                self.address,
                relay_port,
                self.client_ip,
                timing_port,
            )

        request = request._replace(
            path=self._rewrite_uri(request.path),
            body=encode_plist_body(updated_request_data),
        )
        response = await self.send_to_atv(request)
        response_data = decode_plist_body(response.body) or {}
        event_port = response_data["eventPort"]

        key = request.headers.get(
            "DACP-ID", request.headers.get("Active-Remote", request.path)
        )
        proxy_port = await self._create_channel_server(
            f"Event {key}",
            partial(self._create_event_channel, event_port, self._rewrite_info),
        )
        logging.getLogger(__name__).debug(
            "Event port: remote=%d, local=%d", event_port, proxy_port
        )
        return response._replace(
            body=encode_plist_body({**response_data, "eventPort": proxy_port})
        )

    async def _handle_setup_data_stream_channel(self, request, request_data):
        """Proxy dedicated streams and preserve receiver-initiated streams.

        Current tvOS omits ``dataPort`` for some type-130 remote-control
        streams. That is a successful receiver-initiated stream response, not a
        malformed response. The upstream diagnostic proxy currently assumes
        every stream is sender-connected and crashes with ``KeyError``.
        """
        request = request._replace(path=self._rewrite_uri(request.path))
        request_streams = request_data["streams"]
        response = await self.send_to_atv(request)
        response_data = decode_plist_body(response.body) or {}
        response_streams = response_data["streams"]

        proxied_streams = []
        for request_stream, response_stream in zip(request_streams, response_streams):
            if "dataPort" not in response_stream:
                proxied_streams.append(response_stream)
                logging.getLogger(__name__).debug(
                    "Receiver-initiated data stream %s accepted without dataPort",
                    response_stream.get("streamID"),
                )
                continue

            stream_id = response_stream["streamID"]
            stream_port = response_stream["dataPort"]
            stream_seed = request_stream["seed"]
            proxy_port = await self._create_channel_server(
                f"Data stream {stream_id}",
                partial(
                    self._create_data_stream_channel,
                    stream_port,
                    stream_id,
                    stream_seed,
                ),
            )
            logging.getLogger(__name__).debug(
                "Data stream %d port: remote=%d, local=%d",
                stream_id,
                stream_port,
                proxy_port,
            )
            proxied_streams.append({**response_stream, "dataPort": proxy_port})

        return response._replace(
            body=encode_plist_body({**response_data, "streams": proxied_streams})
        )

    def connection_lost(self, exc):
        for transport in getattr(self, "_capture_udp_transports", []):
            transport.close()
        super().connection_lost(exc)


async def run_proxy(remote_ip: str, local_ip: str) -> None:
    paths = AppPaths.default()
    paths.ensure()
    log_path = paths.log_dir / "airplay-capture.log"
    ready_path = Path(".tools/airplay-proxy-ready.json").resolve()
    stop_path = Path(".tools/airplay-proxy-stop").resolve()
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.unlink(missing_ok=True)
    stop_path.unlink(missing_ok=True)

    loop = asyncio.get_running_loop()
    storage = SecureFileStorage(str(paths.airplay_storage_file), loop)
    await storage.load()
    configs = await pyatv.scan(loop, hosts=[remote_ip], timeout=5, storage=storage)
    if not configs:
        raise RuntimeError(f"Apple TV at {remote_ip} was not found")
    service = configs[0].get_service(Protocol.AirPlay)
    if service is None or not service.credentials:
        raise RuntimeError("Pair AirPlay in xMediaPlayerx before starting a capture")

    handler = RotatingFileHandler(log_path, maxBytes=8 * 1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    handler.addFilter(CaptureRedactionFilter(service.credentials))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    response = await mdns.unicast(loop, remote_ip, ["_airplay._tcp.local"])
    target = next(
        (item for item in response.services if item.type == "_airplay._tcp.local"),
        None,
    )
    if target is None:
        raise RuntimeError("The Apple TV AirPlay service did not respond")

    active_proxies: set[CaptureAirPlayAppleTVProxy] = set()

    def proxy_factory() -> CaptureAirPlayAppleTVProxy:
        proxy = CaptureAirPlayAppleTVProxy(
            loop,
            remote_ip,
            target.port,
            target.properties,
            service.credentials,
        )
        active_proxies.add(proxy)
        asyncio.create_task(proxy.start())
        return proxy

    server = await loop.create_server(proxy_factory, "0.0.0.0")
    port = server.sockets[0].getsockname()[1]
    zconf = Zeroconf()
    unpublish = await publish_airplay_service(
        zconf, local_ip, port, dict(target.properties)
    )
    ready_path.write_text(
        json.dumps({"name": "Proxy", "address": local_ip, "port": port, "log": str(log_path)}),
        encoding="utf-8",
    )
    logging.getLogger(__name__).info("AirPlay capture proxy ready on %s:%d", local_ip, port)
    try:
        while not stop_path.exists():
            await asyncio.sleep(0.5)
    finally:
        await unpublish()
        server.close()
        await server.wait_closed()
        zconf.close()
        ready_path.unlink(missing_ok=True)
        stop_path.unlink(missing_ok=True)


def local_address_for(remote_ip: str) -> str:
    """Return the interface address Windows would use to reach the receiver."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((remote_ip, 7000))
        return str(probe.getsockname()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a current Apple AirPlay sender handshake")
    parser.add_argument("--remote-ip", required=True, help="Apple TV IPv4 address")
    parser.add_argument(
        "--local-ip",
        help="PC LAN address to advertise (normally detected automatically)",
    )
    args = parser.parse_args()
    asyncio.run(run_proxy(args.remote_ip, args.local_ip or local_address_for(args.remote_ip)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
