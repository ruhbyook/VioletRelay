from __future__ import annotations

import argparse
import tempfile
import threading
import time
from pathlib import Path

from xmediaplayerx.services.cache import CastCache
from xmediaplayerx.services.converter import MediaPreparer
from xmediaplayerx.services.media import (
    FFmpegLocator,
    MediaProbe,
    PreparationKind,
)


def validate_case(
    preparer: MediaPreparer,
    source: Path,
    expected: PreparationKind,
    subtitle: str = "",
) -> None:
    started = time.monotonic()
    prepared = preparer.prepare(
        str(source.resolve()),
        subtitle,
        cancel=threading.Event(),
    )
    elapsed = time.monotonic() - started
    try:
        if prepared.kind != expected:
            raise AssertionError(
                f"{source.name}: expected {expected}, received {prepared.kind}"
            )
        if not prepared.streaming or prepared.stream_session is None:
            raise AssertionError(
                f"{source.name}: local cast preparation did not produce HLS"
            )
        manifest = Path(prepared.source)
        playlist = manifest.read_text(encoding="utf-8")
        if "#EXTM3U" not in playlist or "#EXTINF:" not in playlist:
            raise AssertionError(
                f"{source.name}: generated HLS manifest is incomplete"
            )
        print(
            f"PASS {source.name}: {prepared.kind} ready in {elapsed:.2f}s",
            flush=True,
        )
    finally:
        if prepared.stream_session is not None:
            prepared.stream_session.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fixtures",
        nargs="?",
        default="build/test-fixtures",
        type=Path,
    )
    args = parser.parse_args()
    fixtures = args.fixtures.resolve()
    required = [
        fixtures / "h264-aac.mp4",
        fixtures / "h264-aac-remux.mkv",
        fixtures / "unsupported-codecs.avi",
        fixtures / "embedded-subtitle.mkv",
        fixtures / "external.srt",
        fixtures / "malformed-media.mp4",
        fixtures / "unicode path 日本語" / "movie café with spaces.mp4",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Generate fixtures first; missing: " + ", ".join(missing)
        )

    locator = FFmpegLocator()
    locator.require()
    probe = MediaProbe(locator)
    with tempfile.TemporaryDirectory(prefix="xmediaplayerx-integration-") as root:
        cache = CastCache(Path(root), 2 * 1024**3)
        preparer = MediaPreparer(locator, probe, cache)
        validate_case(
            preparer,
            fixtures / "h264-aac.mp4",
            PreparationKind.DIRECT,
        )
        validate_case(
            preparer,
            fixtures / "h264-aac-remux.mkv",
            PreparationKind.REMUX,
        )
        validate_case(
            preparer,
            fixtures / "unsupported-codecs.avi",
            PreparationKind.TRANSCODE,
        )
        validate_case(
            preparer,
            fixtures / "embedded-subtitle.mkv",
            PreparationKind.TRANSCODE,
            "embedded:0",
        )
        validate_case(
            preparer,
            fixtures / "h264-aac.mp4",
            PreparationKind.TRANSCODE,
            str((fixtures / "external.srt").resolve()),
        )
        validate_case(
            preparer,
            fixtures / "unicode path 日本語" / "movie café with spaces.mp4",
            PreparationKind.DIRECT,
        )
        try:
            probe.probe(str(fixtures / "malformed-media.mp4"))
        except RuntimeError:
            print("PASS malformed media: rejected by FFprobe", flush=True)
        else:
            raise AssertionError("Malformed media was unexpectedly accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
