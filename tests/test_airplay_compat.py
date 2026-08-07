import asyncio
import logging
from types import SimpleNamespace

from pyatv.support.rtsp import RtspSession

from violetrelay.services.airplay_compat import ReceiverCompatibleRtspSession


def test_optional_set_property_is_best_effort(monkeypatch):
    calls = []

    async def exchange(
        _self,
        method,
        uri=None,
        content_type=None,
        headers=None,
        body=None,
        allow_error=False,
        protocol="RTSP/1.0",
    ):
        calls.append((method, uri, allow_error))
        return SimpleNamespace(code=501)

    monkeypatch.setattr(RtspSession, "exchange", exchange)

    async def scenario():
        session = ReceiverCompatibleRtspSession(object(), logging.getLogger())
        return await session.exchange(
            "PUT", "/setProperty?actionAtItemEnd", body={"value": 0}
        )

    response = asyncio.run(scenario())
    assert response.code == 501
    assert calls == [("PUT", "/setProperty?actionAtItemEnd", True)]


def test_rate_command_is_best_effort(monkeypatch):
    calls = []

    async def exchange(
        _self,
        method,
        uri=None,
        content_type=None,
        headers=None,
        body=None,
        allow_error=False,
        protocol="RTSP/1.0",
    ):
        calls.append((method, uri, allow_error))
        return SimpleNamespace(code=200)

    monkeypatch.setattr(RtspSession, "exchange", exchange)

    async def scenario():
        session = ReceiverCompatibleRtspSession(object(), logging.getLogger())
        await session.exchange("POST", "/rate?value=1.000000")

    asyncio.run(scenario())
    assert calls == [("POST", "/rate?value=1.000000", True)]


def test_required_airplay_commands_still_raise_errors(monkeypatch):
    calls = []

    async def exchange(
        _self,
        method,
        uri=None,
        content_type=None,
        headers=None,
        body=None,
        allow_error=False,
        protocol="RTSP/1.0",
    ):
        calls.append((method, uri, allow_error))
        return SimpleNamespace(code=200)

    monkeypatch.setattr(RtspSession, "exchange", exchange)

    async def scenario():
        session = ReceiverCompatibleRtspSession(object(), logging.getLogger())
        await session.exchange("POST", "/play")

    asyncio.run(scenario())
    assert calls == [("POST", "/play", False)]
