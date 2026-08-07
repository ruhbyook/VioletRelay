from __future__ import annotations

import logging
from typing import Any, Mapping

from pyatv.auth.hap_pairing import parse_credentials
from pyatv.protocols.airplay.player import AirPlayPlayer
from pyatv.protocols.raop.protocols import StreamContext
from pyatv.protocols.raop.protocols.airplayv2 import AirPlayV2
from pyatv.support.http import http_connect
from pyatv.support.rtsp import RtspSession


class ReceiverCompatibleRtspSession(RtspSession):
    """Treat optional AirPlay 2 setProperty calls as best-effort.

    Some built-in TV receivers implement the AirPlay 2 setup, play and rate
    requests but return 501 for Apple's optional PUT /setProperty requests.
    Upstream pyatv currently treats those responses as fatal even though URL
    playback can proceed without the properties.
    """

    def __init__(self, connection: Any, logger: logging.Logger) -> None:
        super().__init__(connection)
        self.log = logger

    async def exchange(
        self,
        method: str,
        uri: str | None = None,
        content_type: str | None = None,
        headers: Mapping[str, object] | None = None,
        body: str | bytes | dict | None = None,
        allow_error: bool = False,
        protocol: str = "RTSP/1.0",
    ):
        optional_command = (
            method == "PUT"
            and bool(uri and uri.startswith("/setProperty?"))
        ) or (
            method == "POST"
            and bool(uri and uri.startswith("/rate?"))
        )
        response = await super().exchange(
            method,
            uri,
            content_type,
            headers,
            body,
            allow_error=allow_error or optional_command,
            protocol=protocol,
        )
        if optional_command and response.code != 200:
            self.log.info(
                "AirPlay receiver skipped optional command: uri=%s status=%d",
                uri,
                response.code,
            )
        return response


async def play_url_compatible(
    config: Any,
    service: Any,
    url: str,
    position_seconds: float,
    logger: logging.Logger,
) -> None:
    """Play an AirPlay 2 URL while tolerating optional receiver omissions."""
    connection = await http_connect(str(config.address), service.port)
    rtsp = ReceiverCompatibleRtspSession(connection, logger)
    context = StreamContext()
    context.credentials = parse_credentials(service.credentials)
    protocol = AirPlayV2(context, rtsp)
    try:
        player = AirPlayPlayer(rtsp, protocol)
        await player.play_url(url, position_seconds)
    finally:
        protocol.teardown()
        connection.close()
