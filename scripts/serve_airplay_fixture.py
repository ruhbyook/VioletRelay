from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import socket

from aiohttp import web


HTML = """<!doctype html>
<html lang="en">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Violet Relay AirPlay test</title>
<style>
  body { margin: 0; background: #080b12; color: white; font: 18px -apple-system; }
  main { max-width: 900px; margin: 32px auto; padding: 20px; }
  video { width: 100%; background: black; border-radius: 16px; }
</style>
<main>
  <h1>AirPlay media test</h1>
  <p>Play the video, then use the AirPlay icon inside the video controls.</p>
  <video controls playsinline x-webkit-airplay="allow" preload="metadata">
    <source src="/fixture.mp4" type="video/mp4">
  </video>
</main>
</html>
"""


def local_address() -> str:
    """Return the preferred LAN address without transmitting application data."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])


async def run(bind: str, port: int, advertise_host: str | None) -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = root / ".tools" / "fixture.mp4"
    ready = root / ".tools" / "airplay-fixture-ready.json"
    stop = root / ".tools" / "airplay-fixture-stop"
    if not fixture.is_file():
        raise RuntimeError(f"Fixture is missing: {fixture}")

    ready.unlink(missing_ok=True)
    stop.unlink(missing_ok=True)
    requests: list[dict[str, str]] = []
    app = web.Application()
    app.router.add_get("/", lambda _: web.Response(text=HTML, content_type="text/html"))

    async def fixture_handler(request: web.Request) -> web.StreamResponse:
        requests.append(
            {
                "remote": request.remote or "",
                "range": request.headers.get("Range", ""),
                "userAgent": request.headers.get("User-Agent", ""),
            }
        )
        return web.FileResponse(fixture)

    app.router.add_get("/fixture.mp4", fixture_handler)
    app.router.add_get("/status", lambda _: web.json_response({"requests": requests}))

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, bind, port)
    await site.start()
    host = advertise_host or local_address()
    ready.write_text(
        json.dumps(
            {
                "url": f"http://{host}:{port}/",
                "media": f"http://{host}:{port}/fixture.mp4",
            }
        ),
        encoding="utf-8",
    )
    try:
        while not stop.exists():
            await asyncio.sleep(0.25)
    finally:
        ready.unlink(missing_ok=True)
        stop.unlink(missing_ok=True)
        await runner.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the AirPlay test fixture")
    parser.add_argument("--bind", default="0.0.0.0", help="Listening address")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--advertise-host",
        help="LAN address written to the ready file (normally detected automatically)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.bind, args.port, args.advertise_host))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
