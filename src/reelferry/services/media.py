from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from reelferry import __version__
from reelferry.logging_utils import redact_text
from reelferry.paths import executable_search_roots


class PreparationKind(StrEnum):
    DIRECT = "direct"
    REMUX = "remux"
    TRANSCODE = "transcode"


@dataclass(slots=True)
class MediaStream:
    index: int
    codec_type: str
    codec_name: str
    width: int = 0
    height: int = 0
    color_transfer: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    disposition: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class MediaInfo:
    source: str
    duration_seconds: float
    format_name: str
    size: int
    streams: list[MediaStream]

    @property
    def video(self) -> MediaStream | None:
        return next((stream for stream in self.streams if stream.codec_type == "video"), None)

    @property
    def audio(self) -> MediaStream | None:
        return next((stream for stream in self.streams if stream.codec_type == "audio"), None)

    @property
    def audio_streams(self) -> list[MediaStream]:
        return [stream for stream in self.streams if stream.codec_type == "audio"]

    @property
    def subtitle_streams(self) -> list[MediaStream]:
        return [stream for stream in self.streams if stream.codec_type == "subtitle"]

    @property
    def hdr(self) -> bool:
        return bool(self.video and self.video.color_transfer.lower() in {"smpte2084", "arib-std-b67"})


@dataclass(frozen=True, slots=True)
class PreparationDecision:
    kind: PreparationKind
    reason: str


@dataclass(frozen=True, slots=True)
class RemoteMediaIdentity:
    final_url: str
    content_length: int
    content_type: str = ""
    etag: str = ""
    last_modified: str = ""

    @property
    def is_webpage(self) -> bool:
        media_type = self.content_type.partition(";")[0].strip().casefold()
        return media_type in {"text/html", "application/xhtml+xml"}

    @property
    def is_hls(self) -> bool:
        media_type = self.content_type.partition(";")[0].strip().casefold()
        return media_type in {
            "application/vnd.apple.mpegurl",
            "application/x-mpegurl",
            "audio/mpegurl",
            "audio/x-mpegurl",
        }

    @property
    def stable(self) -> bool:
        return self.content_length > 0 and bool(self.etag or self.last_modified)

    def cache_identity(self) -> dict[str, object]:
        return {
            "final_url": self.final_url,
            "content_length": self.content_length,
            "etag": self.etag,
            "last_modified": self.last_modified,
        }


class FFmpegNotFoundError(RuntimeError):
    pass


class FFmpegLocator:
    def __init__(self) -> None:
        self.ffmpeg: Path | None = None
        self.ffprobe: Path | None = None
        self.refresh()

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    def refresh(self) -> bool:
        self.ffmpeg = self._find("ffmpeg")
        self.ffprobe = self._find("ffprobe")
        return self.available

    @staticmethod
    def _find(name: str) -> Path | None:
        executable = f"{name}.exe" if __import__("os").name == "nt" else name
        for root in executable_search_roots():
            for candidate in (root / executable, root / "vendor" / "ffmpeg" / "bin" / executable):
                try:
                    if candidate.is_file():
                        return candidate
                except OSError:
                    continue
        if found := shutil.which(executable):
            return Path(found)
        return None

    def require(self) -> tuple[Path, Path]:
        if not self.ffmpeg or not self.ffprobe:
            raise FFmpegNotFoundError(
                "FFmpeg media tools are not installed. Open Settings and install "
                "the verified media tools, then try again."
            )
        return self.ffmpeg, self.ffprobe


class MediaProbe:
    def __init__(self, locator: FFmpegLocator):
        self.locator = locator

    def probe(self, source: str, timeout: float = 30.0) -> MediaInfo:
        _, ffprobe = self.locator.require()
        try:
            result = subprocess.run(
                [
                    str(ffprobe), "-v", "error", "-print_format", "json",
                    "-show_format", "-show_streams", source,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=max(0.1, timeout),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(
                f"Media inspection timed out after {timeout:g} seconds"
            ) from error
        except OSError as error:
            raise RuntimeError(f"Unable to start FFprobe: {error}") from error
        if result.returncode != 0:
            detail = redact_text(result.stderr.strip())
            raise RuntimeError(detail or "Unable to inspect this media source")
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError("FFprobe returned a non-object response")
            raw_streams = payload.get("streams", [])
            media_format = payload.get("format", {})
            if not isinstance(raw_streams, list) or not isinstance(media_format, dict):
                raise ValueError("FFprobe returned an unexpected response shape")
            streams = [
                MediaStream(
                    index=int(stream.get("index", 0)),
                    codec_type=str(stream.get("codec_type", "")),
                    codec_name=str(stream.get("codec_name", "")),
                    width=int(stream.get("width", 0) or 0),
                    height=int(stream.get("height", 0) or 0),
                    color_transfer=str(stream.get("color_transfer", "")),
                    tags={str(k): str(v) for k, v in stream.get("tags", {}).items()},
                    disposition={
                        str(k): int(v or 0)
                        for k, v in stream.get("disposition", {}).items()
                    },
                )
                for stream in raw_streams
                if isinstance(stream, dict)
            ]
            return MediaInfo(
                source=source,
                duration_seconds=float(media_format.get("duration", 0) or 0),
                format_name=str(media_format.get("format_name", "")),
                size=int(media_format.get("size", 0) or 0),
                streams=streams,
            )
        except (
            AttributeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            OverflowError,
        ) as error:
            raise RuntimeError("FFprobe returned invalid media information") from error


def validate_media_url(source: str) -> str:
    normalized = source.strip()
    try:
        parsed = urlparse(normalized)
    except ValueError as error:
        raise ValueError("The media URL is malformed") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a direct HTTP or HTTPS media URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Media URLs containing sign-in credentials are not supported")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("The media URL contains invalid control characters")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("The media URL contains an invalid port") from error
    return normalized


def inspect_remote_media(
    source: str, timeout: float = 10.0
) -> RemoteMediaIdentity:
    """Inspect an unauthenticated URL without downloading the media body."""
    source = validate_media_url(source)
    timeout = max(0.1, float(timeout))
    user_agent = f"ReelFerry/{__version__} direct-media-check"

    def open_request(method: str):
        headers = {"User-Agent": user_agent, "Accept": "*/*"}
        if method == "GET":
            headers["Range"] = "bytes=0-0"
        request = Request(source, headers=headers, method=method)
        return urlopen(request, timeout=timeout)

    response = None
    head_error: Exception | None = None

    def identity_from_response(value) -> RemoteMediaIdentity:
        headers = value.headers
        length_text = str(headers.get("Content-Length", "") or "").strip()
        try:
            content_length = max(0, int(length_text))
        except ValueError:
            content_length = 0
        content_range = str(headers.get("Content-Range", "") or "")
        range_match = re.search(r"/(\d+)\s*$", content_range)
        if range_match:
            content_length = max(content_length, int(range_match.group(1)))
        return RemoteMediaIdentity(
            final_url=str(value.geturl()),
            content_length=content_length,
            content_type=str(headers.get("Content-Type", "") or ""),
            etag=str(headers.get("ETag", "") or ""),
            last_modified=str(headers.get("Last-Modified", "") or ""),
        )

    try:
        head_identity: RemoteMediaIdentity | None = None
        try:
            response = open_request("HEAD")
            head_identity = identity_from_response(response)
        except HTTPError as error:
            head_error = error
            if error.code not in {400, 403, 405, 501}:
                raise
            error.close()
        needs_range_probe = (
            head_identity is None
            or head_identity.content_length <= 0
            or not (head_identity.etag or head_identity.last_modified)
        )
        if needs_range_probe:
            if response is not None:
                response.close()
                response = None
            try:
                response = open_request("GET")
            except (HTTPError, URLError, OSError, TimeoutError) as error:
                if isinstance(error, HTTPError):
                    error.close()
                if head_identity is not None:
                    return head_identity
                raise
        assert response is not None
        identity = identity_from_response(response)
        # A server may ignore Range and begin returning the full body. Reading
        # one byte proves the response is usable while close() prevents a
        # large media download.
        if (
            needs_range_probe
            and getattr(response, "status", 200) != 204
            and response.getcode() != 204
        ):
            response.read(1)
        if head_identity is not None:
            return RemoteMediaIdentity(
                final_url=identity.final_url or head_identity.final_url,
                content_length=max(
                    identity.content_length,
                    head_identity.content_length,
                ),
                content_type=(
                    identity.content_type or head_identity.content_type
                ),
                etag=identity.etag or head_identity.etag,
                last_modified=(
                    identity.last_modified or head_identity.last_modified
                ),
            )
        return identity
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        reason = getattr(error, "reason", None)
        detail = redact_text(str(reason or error)).strip()
        if head_error is not None and not detail:
            detail = redact_text(str(head_error)).strip()
        raise RuntimeError(
            "The URL could not be verified as directly reachable media"
            + (f": {detail}" if detail else "")
        ) from error
    finally:
        if response is not None:
            response.close()


def is_hls_url(source: str, content_type: str = "") -> bool:
    if Path(urlparse(source).path).suffix.lower() == ".m3u8":
        return True
    return RemoteMediaIdentity(
        source, 0, content_type=content_type
    ).is_hls


def selected_audio_stream(info: MediaInfo, audio_stream: int = -1) -> MediaStream | None:
    streams = info.audio_streams
    if not streams:
        return None
    if 0 <= audio_stream < len(streams):
        return streams[audio_stream]
    default = next(
        (stream for stream in streams if stream.disposition.get("default", 0)), None
    )
    return default or streams[0]


def default_audio_stream_index(info: MediaInfo) -> int:
    if not info.audio_streams:
        return -1
    return next(
        (
            index
            for index, stream in enumerate(info.audio_streams)
            if stream.disposition.get("default", 0)
        ),
        0,
    )


def embedded_subtitle_stream(info: MediaInfo, subtitle: str) -> MediaStream | None:
    if not subtitle.startswith("embedded:"):
        return None
    try:
        index = int(subtitle.split(":", 1)[1])
    except ValueError:
        return None
    streams = info.subtitle_streams
    return streams[index] if 0 <= index < len(streams) else None


def subtitle_is_bitmap(info: MediaInfo, subtitle: str) -> bool:
    stream = embedded_subtitle_stream(info, subtitle)
    if stream is not None:
        return stream.codec_name.lower() in {
            "dvb_subtitle",
            "dvd_subtitle",
            "hdmv_pgs_subtitle",
            "xsub",
        }
    return bool(subtitle) and Path(subtitle).suffix.lower() in {".idx", ".sup"}


def classify_media(
    info: MediaInfo,
    source: str,
    subtitle: str = "",
    audio_stream: int = -1,
) -> PreparationDecision:
    video = info.video
    if video is None:
        return PreparationDecision(PreparationKind.TRANSCODE, "No compatible video stream was found")
    if subtitle:
        return PreparationDecision(PreparationKind.TRANSCODE, "Selected subtitles must be burned in")
    video_ok = video.codec_name.lower() in {"h264", "hevc"}
    audio = selected_audio_stream(info, audio_stream)
    audio_ok = audio is None or audio.codec_name.lower() in {"aac", "ac3", "eac3", "alac"}
    suffix = Path(urlparse(source).path).suffix.lower()
    format_names = {
        name.strip().casefold()
        for name in info.format_name.split(",")
    }
    container_ok = (
        suffix in {".mp4", ".m4v", ".mov"}
        or bool(format_names.intersection({"mov", "mp4", "m4a", "3gp"}))
    )
    if video_ok and audio_ok and container_ok and audio_stream in {-1, 0}:
        return PreparationDecision(PreparationKind.DIRECT, "Apple TV compatible streams and container")
    if video_ok and audio_ok:
        return PreparationDecision(PreparationKind.REMUX, "Compatible streams need an MP4 container")
    return PreparationDecision(PreparationKind.TRANSCODE, "One or more codecs need conversion")
