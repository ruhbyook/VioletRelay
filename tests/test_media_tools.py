from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path
import zipfile

import pytest

from reelferry.services.media_tools import MediaToolsInstaller


class Response(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def archive_bytes(ffmpeg: bytes = b"ffmpeg", ffprobe: bytes = b"ffprobe") -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("ffmpeg-test/bin/ffmpeg.exe", ffmpeg)
        archive.writestr("ffmpeg-test/bin/ffprobe.exe", ffprobe)
        archive.writestr("ffmpeg-test/LICENSE", "GPL")
        archive.writestr("ffmpeg-test/README.txt", "source information")
    return output.getvalue()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def installer(tmp_path: Path, payload: bytes) -> MediaToolsInstaller:
    return MediaToolsInstaller(
        tmp_path / "tools",
        archive_url="https://example.test/ffmpeg.zip",
        archive_sha256=digest(payload),
        ffmpeg_sha256=digest(b"ffmpeg"),
        ffprobe_sha256=digest(b"ffprobe"),
        opener=lambda _request, timeout: Response(payload),
    )


def test_verified_media_tools_install_atomically(tmp_path):
    payload = archive_bytes()
    progress = []
    service = installer(tmp_path, payload)

    ffmpeg, ffprobe = service.install(
        lambda received, total: progress.append((received, total))
    )

    assert ffmpeg.read_bytes() == b"ffmpeg"
    assert ffprobe.read_bytes() == b"ffprobe"
    assert (ffmpeg.parent / "FFMPEG_LICENSE.txt").read_text() == "GPL"
    assert service.installed()
    assert progress[-1] == (len(payload), len(payload))
    assert not (ffmpeg.parent / ".ffmpeg-download.partial").exists()
    assert not (ffmpeg.parent / ".installing").exists()


def test_tampered_media_tools_archive_is_rejected_and_cleaned(tmp_path):
    payload = archive_bytes()
    service = MediaToolsInstaller(
        tmp_path / "tools",
        archive_url="https://example.test/ffmpeg.zip",
        archive_sha256="0" * 64,
        ffmpeg_sha256=digest(b"ffmpeg"),
        ffprobe_sha256=digest(b"ffprobe"),
        opener=lambda _request, timeout: Response(payload),
    )

    with pytest.raises(RuntimeError, match="SHA-256"):
        service.install()

    assert not service.ffmpeg.exists()
    assert not service.ffprobe.exists()
    assert not (service.tools_dir / ".ffmpeg-download.partial").exists()
