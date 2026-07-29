from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import threading
from typing import BinaryIO, Callable
from urllib.request import Request, urlopen
import zipfile


FFMPEG_VERSION = "8.1.2"
FFMPEG_ARCHIVE_URL = (
    "https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/"
    "ffmpeg-8.1.2-essentials_build.zip"
)
FFMPEG_ARCHIVE_SHA256 = (
    "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
)
FFMPEG_SHA256 = (
    "1326dde4c84ff1f96fe6b8916c5bed29e163e9b5dccf995f6f3db069d143ec5e"
)
FFPROBE_SHA256 = (
    "b49ccc7c6547b141ad5a2f6ec69cc04323d7133d7704d70b331b904c63eecb07"
)
FFMPEG_ARCHIVE_BYTES = 109_728_040


class MediaToolsCancelled(RuntimeError):
    pass


class MediaToolsInstaller:
    """Download and verify FFmpeg directly from its Windows build provider."""

    def __init__(
        self,
        tools_dir: Path,
        *,
        archive_url: str = FFMPEG_ARCHIVE_URL,
        archive_sha256: str = FFMPEG_ARCHIVE_SHA256,
        ffmpeg_sha256: str = FFMPEG_SHA256,
        ffprobe_sha256: str = FFPROBE_SHA256,
        opener: Callable[..., BinaryIO] = urlopen,
    ) -> None:
        self.tools_dir = tools_dir
        self.archive_url = archive_url
        self.archive_sha256 = archive_sha256
        self.ffmpeg_sha256 = ffmpeg_sha256
        self.ffprobe_sha256 = ffprobe_sha256
        self.opener = opener

    @property
    def ffmpeg(self) -> Path:
        return self.tools_dir / "ffmpeg.exe"

    @property
    def ffprobe(self) -> Path:
        return self.tools_dir / "ffprobe.exe"

    def installed(self) -> bool:
        return self._matches(self.ffmpeg, self.ffmpeg_sha256) and self._matches(
            self.ffprobe, self.ffprobe_sha256
        )

    @staticmethod
    def _matches(path: Path, expected: str) -> bool:
        try:
            return MediaToolsInstaller._digest(path) == expected
        except OSError:
            return False

    @staticmethod
    def _digest(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        return hasher.hexdigest()

    @staticmethod
    def _archive_entry(
        archive: zipfile.ZipFile, filename: str
    ) -> zipfile.ZipInfo:
        matches = [
            entry
            for entry in archive.infolist()
            if not entry.is_dir()
            and PurePosixPath(entry.filename.replace("\\", "/")).name.casefold()
            == filename.casefold()
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"The verified FFmpeg archive did not contain one {filename}"
            )
        return matches[0]

    @staticmethod
    def _copy_entry(
        archive: zipfile.ZipFile, entry: zipfile.ZipInfo, target: Path
    ) -> None:
        with archive.open(entry) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)

    def install(
        self,
        progress: Callable[[int, int], None] | None = None,
        cancelled: threading.Event | None = None,
    ) -> tuple[Path, Path]:
        if self.installed():
            if progress:
                progress(1, 1)
            return self.ffmpeg, self.ffprobe

        self.tools_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.tools_dir / ".ffmpeg-download.partial"
        staging = self.tools_dir / ".installing"
        archive_path.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()

        try:
            request = Request(
                self.archive_url,
                headers={"User-Agent": "xMediaPlayerx media-tools installer"},
            )
            hasher = hashlib.sha256()
            received = 0
            with self.opener(request, timeout=30) as response, archive_path.open(
                "wb"
            ) as output:
                total = int(
                    getattr(response, "headers", {}).get(
                        "Content-Length", FFMPEG_ARCHIVE_BYTES
                    )
                    or FFMPEG_ARCHIVE_BYTES
                )
                while True:
                    if cancelled and cancelled.is_set():
                        raise MediaToolsCancelled("Media-tools installation cancelled")
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    hasher.update(block)
                    received += len(block)
                    if progress:
                        progress(received, max(total, received))
            if hasher.hexdigest() != self.archive_sha256:
                raise RuntimeError(
                    "The FFmpeg download failed its SHA-256 verification"
                )

            with zipfile.ZipFile(archive_path) as archive:
                ffmpeg_entry = self._archive_entry(archive, "ffmpeg.exe")
                ffprobe_entry = self._archive_entry(archive, "ffprobe.exe")
                staged_ffmpeg = staging / "ffmpeg.exe"
                staged_ffprobe = staging / "ffprobe.exe"
                self._copy_entry(archive, ffmpeg_entry, staged_ffmpeg)
                self._copy_entry(archive, ffprobe_entry, staged_ffprobe)
                for source_name, target_name in (
                    ("LICENSE", "FFMPEG_LICENSE.txt"),
                    ("README.txt", "FFMPEG_README.txt"),
                ):
                    try:
                        self._copy_entry(
                            archive,
                            self._archive_entry(archive, source_name),
                            staging / target_name,
                        )
                    except RuntimeError:
                        # The executables and their hashes are mandatory; the
                        # upstream metadata files are copied whenever present.
                        pass

            if self._digest(staged_ffmpeg) != self.ffmpeg_sha256:
                raise RuntimeError("Downloaded ffmpeg.exe failed verification")
            if self._digest(staged_ffprobe) != self.ffprobe_sha256:
                raise RuntimeError("Downloaded ffprobe.exe failed verification")

            for name in (
                "ffmpeg.exe",
                "ffprobe.exe",
                "FFMPEG_LICENSE.txt",
                "FFMPEG_README.txt",
            ):
                source = staging / name
                if source.exists():
                    os.replace(source, self.tools_dir / name)
            return self.ffmpeg, self.ffprobe
        finally:
            archive_path.unlink(missing_ok=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
