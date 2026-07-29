from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import math
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from .cache import CastCache
from .media import (
    FFmpegLocator,
    MediaInfo,
    MediaProbe,
    PreparationDecision,
    PreparationKind,
    classify_media,
    default_audio_stream_index,
    inspect_remote_media,
    is_hls_url,
    subtitle_is_bitmap,
    validate_media_url,
)


ProgressCallback = Callable[[float, str], None]

@dataclass(frozen=True, slots=True)
class PreparedMedia:
    source: str
    kind: PreparationKind
    cached: bool
    media_info: MediaInfo | None
    streaming: bool = False
    stream_session: "HlsSession | None" = None
    start_position_seconds: float = 0.0


class ConversionCancelled(RuntimeError):
    pass


class EncoderBackend(StrEnum):
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    CPU = "cpu"


HARDWARE_BACKENDS = (
    EncoderBackend.NVIDIA,
    EncoderBackend.AMD,
    EncoderBackend.INTEL,
)

BACKEND_LABELS = {
    EncoderBackend.NVIDIA: "NVIDIA NVENC",
    EncoderBackend.AMD: "AMD AMF",
    EncoderBackend.INTEL: "Intel Quick Sync",
    EncoderBackend.CPU: "CPU",
}


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def conversion_progress(
    out_seconds: float, duration_seconds: float, speed: float
) -> tuple[float, str]:
    """Return truthful timeline progress and a human-readable conversion status."""
    if duration_seconds <= 0:
        return 0.0, "Preparing cast copy"
    ratio = min(0.999, max(0.0, out_seconds / duration_seconds))
    details: list[str] = []
    if speed > 0:
        details.append(f"{speed:.2f}×")
        remaining = max(0.0, duration_seconds - out_seconds) / speed
        if math.isfinite(remaining):
            details.append(f"about {_format_duration(remaining)} left")
    status = "Preparing cast copy"
    if details:
        status += " · " + " · ".join(details)
    return ratio, status


def streaming_buffer_progress(
    out_seconds: float, speed: float, target_seconds: float = 8.0
) -> tuple[float, str]:
    """Report the short startup buffer, not the remaining movie encode time."""
    target_seconds = max(0.1, target_seconds)
    ratio = min(0.95, max(0.0, out_seconds / target_seconds))
    status = f"Building initial {target_seconds:g}-second buffer"
    if speed > 0:
        status += f" · {speed:.2f}×"
    return ratio, status


class HlsSession:
    """A running FFmpeg process producing an event-style HLS presentation."""

    def __init__(
        self,
        directory: Path,
        command: list[str],
        duration_seconds: float,
        progress: ProgressCallback,
    ) -> None:
        self.directory = directory
        self.manifest = directory / "index.m3u8"
        self.duration_seconds = duration_seconds
        self.progress = progress
        self.stderr_lines: list[str] = []
        self.error = ""
        self.done = threading.Event()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            command,
            cwd=str(directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread = threading.Thread(target=self._read_progress, daemon=True)
        self._stderr_thread.start()
        self._stdout_thread.start()

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        try:
            for line in self.process.stderr:
                self.stderr_lines.append(line.rstrip())
                if len(self.stderr_lines) > 100:
                    self.stderr_lines.pop(0)
        finally:
            self.process.stderr.close()

    def _read_progress(self) -> None:
        assert self.process.stdout is not None
        out_seconds = 0.0
        speed = 0.0
        try:
            for raw in self.process.stdout:
                key, _, value = raw.strip().partition("=")
                if key in {"out_time_us", "out_time_ms"}:
                    try:
                        out_seconds = int(value or 0) / 1_000_000
                    except ValueError:
                        pass
                elif key == "speed":
                    try:
                        speed = float(value.rstrip("x"))
                    except ValueError:
                        speed = 0.0
                elif key == "progress":
                    ratio, status = streaming_buffer_progress(
                        out_seconds,
                        speed,
                    )
                    try:
                        self.progress(ratio, status)
                    except Exception:
                        # UI teardown must not stop draining FFmpeg's progress pipe.
                        pass
            return_code = self.process.wait()
            self._stderr_thread.join(timeout=1)
            if return_code != 0:
                self.error = "\n".join(self.stderr_lines[-14:]) or f"FFmpeg exited with code {return_code}"
        finally:
            self.process.stdout.close()
            self.done.set()

    def wait_until_ready(
        self,
        segments: int = 2,
        timeout: float = 90.0,
        cancel: threading.Event | None = None,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                self.stop()
                raise ConversionCancelled("Cast preparation cancelled")
            if self.manifest.exists() and (self.directory / "init.mp4").exists():
                try:
                    playlist = self.manifest.read_text(encoding="utf-8")
                    if playlist.count("#EXTINF:") >= segments or (
                        "#EXT-X-ENDLIST" in playlist and "#EXTINF:" in playlist
                    ):
                        return
                except OSError:
                    pass
            if self.done.is_set():
                raise RuntimeError(self.error or "The streaming encoder stopped before producing a playable buffer")
            time.sleep(0.2)
        raise TimeoutError("Timed out while building the initial Apple TV streaming buffer")

    def stop(self, remove_files: bool = True) -> None:
        try:
            running = self.process.poll() is None
        except OSError:
            running = False
        if running:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            except OSError:
                pass
        try:
            self.done.wait(timeout=3)
        finally:
            if remove_files:
                shutil.rmtree(self.directory, ignore_errors=True)


class MediaPreparer:
    def __init__(self, locator: FFmpegLocator, probe: MediaProbe, cache: CastCache):
        self.locator = locator
        self.probe = probe
        self.cache = cache
        self.log = logging.getLogger("xmediaplayerx.converter")
        self._backend_probe: dict[EncoderBackend, bool] = {}
        self._backend_probe_lock = threading.Lock()

    @staticmethod
    def _h264_encoder(backend: EncoderBackend) -> str:
        return {
            EncoderBackend.NVIDIA: "h264_nvenc",
            EncoderBackend.AMD: "h264_amf",
            EncoderBackend.INTEL: "h264_qsv",
            EncoderBackend.CPU: "libx264",
        }[backend]

    def _probe_hardware_backend(self, backend: EncoderBackend) -> bool:
        if backend == EncoderBackend.CPU:
            return True
        with self._backend_probe_lock:
            if backend in self._backend_probe:
                return self._backend_probe[backend]
            ffmpeg, _ = self.locator.require()
            command = [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                # Modern NVENC drivers reject frames below their minimum
                # coded dimensions, so use a small but universally valid size.
                "color=c=black:s=256x256:r=1",
                "-frames:v",
                "1",
                "-an",
                "-c:v",
                self._h264_encoder(backend),
                "-f",
                "null",
                "-",
            ]
            try:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=12,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                available = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                available = False
            self._backend_probe[backend] = available
        self.log.info(
            "%s encoder %s",
            BACKEND_LABELS[backend],
            "available" if available else "unavailable",
        )
        return available

    def _hardware_candidates(self, progress: ProgressCallback):
        for backend in HARDWARE_BACKENDS:
            progress(0.0, f"Checking {BACKEND_LABELS[backend]}")
            if self._probe_hardware_backend(backend):
                yield backend
            else:
                progress(0.0, f"{BACKEND_LABELS[backend]} unavailable")

    def prepare(
        self,
        source: str,
        subtitle: str = "",
        progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
        start_position_seconds: float = 0.0,
        audio_stream: int = -1,
    ) -> PreparedMedia:
        progress = progress or (lambda _value, _status: None)
        cancel = cancel or threading.Event()
        is_url = source.lower().startswith(("http://", "https://"))
        remote_identity = None
        remote_inspection_error: Exception | None = None
        if is_url:
            source = validate_media_url(source)
            if is_hls_url(source):
                return PreparedMedia(source, PreparationKind.DIRECT, False, None)
            progress(0.0, "Checking direct media URL")
            try:
                remote_identity = inspect_remote_media(source)
            except Exception as error:
                # FFprobe may still prove a normal direct MP4/MOV playable.
                # A conversion, however, is forbidden without stable HTTP
                # identity data because its cached result could become stale.
                remote_inspection_error = error
            else:
                if remote_identity.is_webpage:
                    raise ValueError(
                        "This URL points to a web page, not a direct media file. "
                        "YouTube, streaming-service pages, and DRM are unsupported."
                    )
                if remote_identity.is_hls:
                    return PreparedMedia(
                        source, PreparationKind.DIRECT, False, None
                    )
        elif not Path(source).is_file():
            raise FileNotFoundError(f"Media file no longer exists: {source}")

        self._validate_tracks(subtitle, audio_stream)

        progress(0.0, "Inspecting media")
        info = self.probe.probe(source)
        resolved_audio = (
            audio_stream
            if audio_stream >= 0
            else default_audio_stream_index(info)
        )
        self._validate_probed_tracks(info, subtitle, resolved_audio)
        if is_url and "hls" in {
            part.strip().casefold()
            for part in info.format_name.split(",")
        }:
            progress(1.0, "Ready to cast")
            return PreparedMedia(
                source, PreparationKind.DIRECT, False, info
            )
        decision = classify_media(info, source, subtitle, resolved_audio)
        if decision.kind == PreparationKind.DIRECT:
            if not is_url:
                return self._local_file_stream(
                    Path(source),
                    decision.kind,
                    False,
                    info,
                    max(0.0, start_position_seconds),
                    progress,
                    cancel,
                    resolved_audio,
                )
            progress(1.0, "Ready to cast")
            return PreparedMedia(source, decision.kind, False, info)

        if is_url:
            if info.duration_seconds <= 0:
                raise RuntimeError(
                    "This remote source requires conversion, but FFprobe could "
                    "not establish a finite duration. Only direct HLS streams "
                    "or finite remote files are supported."
                )
            if remote_identity is None:
                detail = (
                    f" ({remote_inspection_error})"
                    if remote_inspection_error is not None
                    else ""
                )
                raise RuntimeError(
                    "This remote file requires conversion, but its size and "
                    "cache identity could not be verified"
                    + detail
                )
            if not remote_identity.stable:
                raise RuntimeError(
                    "This remote file requires conversion, but the server does "
                    "not provide both a file size and an ETag or Last-Modified "
                    "validator. Download it locally first."
                )

        # Compatible streams do not need a complete intermediate MP4. FFmpeg
        # can copy them directly from MKV/AVI/alternate-track MP4 into the
        # fragmented HLS presentation Apple TV consumes. This turns a
        # multi-minute remux into only the initial streaming buffer.
        if decision.kind == PreparationKind.REMUX and not is_url:
            return self._local_file_stream(
                Path(source),
                decision.kind,
                False,
                info,
                max(0.0, start_position_seconds),
                progress,
                cancel,
                resolved_audio,
            )

        key = self.cache.key_for(
            source,
            subtitle,
            resolved_audio,
            remote_identity=(
                remote_identity.cache_identity()
                if remote_identity is not None
                else None
            ),
        )
        if cached := self.cache.get(key):
            return self._local_file_stream(
                cached,
                decision.kind,
                True,
                info,
                max(0.0, start_position_seconds),
                progress,
                cancel,
            )

        # Burning subtitles used to require completing an entire cached MP4
        # before AirPlay could start. Produce the same H.264/AAC conversion as
        # paced fragmented HLS instead, so Apple TV can begin after the first
        # two segments while the GPU keeps encoding slightly ahead of playback.
        if subtitle and not is_url:
            prepared_stream = self._prepare_transcode_stream(
                source,
                info,
                subtitle,
                resolved_audio,
                max(0.0, start_position_seconds),
                progress,
                cancel,
            )
            if prepared_stream is not None:
                return prepared_stream

        if (
            info.hdr
            and not subtitle
            and info.video is not None
            and info.video.codec_name.lower() in {"av1", "hevc", "h264"}
        ):
            prepared_stream = self._prepare_hdr_stream(
                source,
                info,
                resolved_audio,
                max(0.0, start_position_seconds),
                progress,
                cancel,
            )
            if prepared_stream is not None:
                return prepared_stream

        output = self.cache.output_path(key)
        partial = output.with_name(f"{output.stem}.partial.mp4")
        self._clear_partial(partial)
        try:
            if decision.kind == PreparationKind.REMUX:
                progress(0.0, "Preparing compatible MP4")
                self._run_remux(
                    source, partial, info, resolved_audio, progress, cancel
                )
            else:
                progress(0.0, "Converting for Apple TV")
                self._transcode_with_fallback(
                    source,
                    partial,
                    info,
                    subtitle,
                    resolved_audio,
                    progress,
                    cancel,
                )
            if cancel.is_set():
                raise ConversionCancelled("Conversion cancelled")
            self._publish_partial(partial, output)
            self.cache.enforce_limit({output})
            return self._local_file_stream(
                output,
                decision.kind,
                False,
                info,
                max(0.0, start_position_seconds),
                progress,
                cancel,
            )
        except Exception:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                self.log.warning("Could not remove partial cast file: %s", partial)
            raise

    def prepare_local_fallback(
        self,
        source: str,
        subtitle: str = "",
        audio_stream: int = -1,
        progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> PreparedMedia:
        """Create a broadly playable local MP4 after Qt rejects the source."""
        progress = progress or (lambda _value, _status: None)
        cancel = cancel or threading.Event()
        if not Path(source).is_file():
            raise FileNotFoundError(f"Media file no longer exists: {source}")
        self._validate_tracks(subtitle, audio_stream)
        progress(0.0, "Inspecting media")
        info = self.probe.probe(source)
        resolved_audio = (
            audio_stream
            if audio_stream >= 0
            else default_audio_stream_index(info)
        )
        self._validate_probed_tracks(info, subtitle, resolved_audio)
        key = self.cache.key_for(
            source,
            subtitle,
            resolved_audio,
            profile="local-fallback-1080p-v2",
        )
        if cached := self.cache.get(key):
            progress(1.0, "Using local compatibility copy")
            return PreparedMedia(
                str(cached), PreparationKind.TRANSCODE, True, info
            )

        output = self.cache.output_path(key)
        partial = output.with_name(f"{output.stem}.partial.mp4")
        self._clear_partial(partial)

        def local_progress(value: float, status: str) -> None:
            progress(
                value,
                status.replace("Preparing cast copy", "Preparing local copy"),
            )

        try:
            progress(0.0, "Creating local compatibility copy")
            self._transcode_with_fallback(
                source,
                partial,
                info,
                subtitle,
                resolved_audio,
                local_progress,
                cancel,
            )
            if cancel.is_set():
                raise ConversionCancelled("Conversion cancelled")
            self._publish_partial(partial, output)
            self.cache.enforce_limit({output})
            progress(1.0, "Local compatibility copy ready")
            return PreparedMedia(
                str(output), PreparationKind.TRANSCODE, False, info
            )
        except Exception:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                self.log.warning("Could not remove partial local file: %s", partial)
            raise

    def _validate_tracks(self, subtitle: str, audio_stream: int) -> None:
        if subtitle and not subtitle.startswith("embedded:"):
            if not Path(subtitle).is_file():
                raise FileNotFoundError(
                    f"Selected subtitle file no longer exists: {subtitle}"
                )
        if subtitle.startswith("embedded:"):
            try:
                index = int(subtitle.split(":", 1)[1])
            except ValueError as error:
                raise ValueError("The selected subtitle track is invalid") from error
            if index < 0:
                raise ValueError("The selected subtitle track is invalid")
        if audio_stream < -1:
            raise ValueError("The selected audio track is invalid")

    @staticmethod
    def _validate_probed_tracks(
        info: MediaInfo, subtitle: str, audio_stream: int
    ) -> None:
        if audio_stream >= len(info.audio_streams) and audio_stream >= 0:
            raise ValueError("The selected audio track is no longer available")
        if subtitle.startswith("embedded:"):
            index = int(subtitle.split(":", 1)[1])
            if index >= len(info.subtitle_streams):
                raise ValueError("The selected subtitle track is no longer available")

    @staticmethod
    def _clear_partial(partial: Path) -> None:
        try:
            partial.unlink(missing_ok=True)
        except OSError as error:
            raise RuntimeError(
                "An incomplete cache file is locked by another process"
            ) from error

    @staticmethod
    def _publish_partial(partial: Path, output: Path) -> None:
        try:
            partial.replace(output)
        except OSError as error:
            raise RuntimeError(
                f"Unable to save the prepared media copy: {error}"
            ) from error

    def _transcode_with_fallback(
        self,
        source: str,
        output: Path,
        info: MediaInfo,
        subtitle: str,
        audio_stream: int,
        progress: ProgressCallback,
        cancel: threading.Event,
    ) -> EncoderBackend:
        for backend in self._hardware_candidates(progress):
            if cancel.is_set():
                raise ConversionCancelled("Conversion cancelled")
            label = BACKEND_LABELS[backend]
            progress(0.0, f"Encoding with {label}")
            try:
                self._run_transcode(
                    source,
                    output,
                    info,
                    subtitle,
                    audio_stream,
                    backend,
                    progress,
                    cancel,
                )
                return backend
            except ConversionCancelled:
                raise
            except RuntimeError as error:
                if not self._is_hardware_failure(error):
                    raise
                output.unlink(missing_ok=True)
                self.log.warning(
                    "%s conversion failed; trying the next encoder: %s",
                    label,
                    error,
                )
                progress(0.0, f"{label} failed; trying another encoder")

        progress(0.0, "Using CPU compatibility encoder")
        self._run_transcode(
            source,
            output,
            info,
            subtitle,
            audio_stream,
            EncoderBackend.CPU,
            progress,
            cancel,
        )
        return EncoderBackend.CPU

    @staticmethod
    def _is_hardware_failure(error: RuntimeError) -> bool:
        detail = str(error).casefold()
        if any(
            marker in detail
            for marker in (
                "no space left",
                "disk full",
                "not enough space",
                "permission denied",
                "access is denied",
                "read-only file system",
                "error opening input",
                "no such file or directory",
            )
        ):
            return False
        return any(
            marker in detail
            for marker in (
                "nvenc",
                "nvdec",
                "cuda",
                "amf",
                "quick sync",
                "qsv",
                "mfx",
                "hardware device",
                "device setup failed",
                "driver rejected encoder",
                "initializeencoder failed",
            )
        )

    def _prepare_hdr_stream(
        self,
        source: str,
        info: MediaInfo,
        audio_stream: int,
        start_position_seconds: float,
        progress: ProgressCallback,
        cancel: threading.Event,
    ) -> PreparedMedia | None:
        for backend in self._hardware_candidates(progress):
            if cancel.is_set():
                raise ConversionCancelled("Cast preparation cancelled")
            label = BACKEND_LABELS[backend]
            progress(0.0, f"Starting {label} HDR stream")
            session: HlsSession | None = None
            try:
                session = self._start_hardware_hls(
                    source,
                    info,
                    progress,
                    start_position_seconds,
                    audio_stream,
                    backend,
                )
                session.wait_until_ready(cancel=cancel)
                session.progress = lambda _value, _status: None
                progress(1.0, f"{label} HDR stream ready")
                return PreparedMedia(
                    str(session.manifest),
                    PreparationKind.DIRECT,
                    False,
                    info,
                    streaming=True,
                    stream_session=session,
                    start_position_seconds=start_position_seconds,
                )
            except ConversionCancelled:
                if session is not None:
                    session.stop()
                raise
            except OSError as error:
                if session is not None:
                    session.stop()
                raise RuntimeError(f"Unable to start HDR streaming: {error}") from error
            except (RuntimeError, TimeoutError) as error:
                if session is not None:
                    session.stop()
                if isinstance(error, RuntimeError) and not (
                    self._is_hardware_failure(error)
                    or "streaming encoder stopped" in str(error).casefold()
                ):
                    raise
                self.log.warning(
                    "%s HDR streaming failed; trying the next backend: %s",
                    label,
                    error,
                )
                progress(0.0, f"{label} HDR stream failed; trying another GPU")

        progress(0.0, "GPU HDR streaming unavailable; converting to SDR")
        return None

    def _prepare_transcode_stream(
        self,
        source: str,
        info: MediaInfo,
        subtitle: str,
        audio_stream: int,
        start_position_seconds: float,
        progress: ProgressCallback,
        cancel: threading.Event,
    ) -> PreparedMedia | None:
        """Start a paced H.264/AAC HLS transcode without waiting for the movie."""
        for backend in self._hardware_candidates(progress):
            if cancel.is_set():
                raise ConversionCancelled("Cast preparation cancelled")
            label = BACKEND_LABELS[backend]
            accelerated_input = self._nvidia_subtitle_pipeline_supported(
                info, subtitle, backend
            )
            while True:
                mode = " accelerated" if accelerated_input else ""
                progress(0.0, f"Starting {label}{mode} subtitle stream")
                session: HlsSession | None = None
                try:
                    session = self._start_transcode_hls(
                        source,
                        info,
                        subtitle,
                        progress,
                        start_position_seconds,
                        audio_stream,
                        backend,
                        accelerated_input,
                    )
                    session.wait_until_ready(cancel=cancel)
                    session.progress = lambda _value, _status: None
                    progress(1.0, f"{label} subtitle stream ready")
                    return PreparedMedia(
                        str(session.manifest),
                        PreparationKind.TRANSCODE,
                        False,
                        info,
                        streaming=True,
                        stream_session=session,
                        start_position_seconds=start_position_seconds,
                    )
                except ConversionCancelled:
                    if session is not None:
                        session.stop()
                    raise
                except OSError as error:
                    if session is not None:
                        session.stop()
                    raise RuntimeError(
                        f"Unable to start subtitle streaming: {error}"
                    ) from error
                except (RuntimeError, TimeoutError) as error:
                    if session is not None:
                        session.stop()
                    if (
                        accelerated_input
                        and self._is_nvidia_subtitle_pipeline_failure(error)
                    ):
                        self.log.warning(
                            "Accelerated NVIDIA subtitle filtering failed; "
                            "retrying with compatible filters: %s",
                            error,
                        )
                        progress(
                            0.0,
                            "NVIDIA accelerated filtering unavailable; retrying",
                        )
                        accelerated_input = False
                        continue
                    if isinstance(error, RuntimeError) and not (
                        self._is_hardware_failure(error)
                        or "streaming encoder stopped" in str(error).casefold()
                    ):
                        raise
                    self.log.warning(
                        "%s subtitle streaming failed; trying the next backend: %s",
                        label,
                        error,
                    )
                    progress(
                        0.0,
                        f"{label} subtitle stream failed; trying another GPU",
                    )
                    break

        progress(
            0.0,
            "GPU subtitle streaming unavailable; preparing compatibility copy",
        )
        return None

    def _local_file_stream(
        self,
        source: Path,
        kind: PreparationKind,
        cached: bool,
        info: MediaInfo,
        start_position_seconds: float,
        progress: ProgressCallback,
        cancel: threading.Event,
        audio_stream: int = -1,
    ) -> PreparedMedia:
        try:
            if not source.is_file() or source.stat().st_size <= 0:
                raise FileNotFoundError(source)
        except OSError as error:
            raise RuntimeError(
                f"Unable to inspect the prepared cast file: {error}"
            ) from error

        # tvOS 26 can request a complete MP4 range more than once and abandon
        # it without ever entering playback, even when the codecs and file are
        # valid. Fragmented HLS has proven reliable on the same receiver. This
        # is a stream copy, so it creates the initial buffer without encoding.
        progress(0.0, "Building Apple TV streaming buffer")
        session: HlsSession | None = None
        try:
            session = self._start_copy_hls(
                source,
                info,
                progress,
                start_position_seconds,
                audio_stream,
            )
            session.wait_until_ready(cancel=cancel)
            session.progress = lambda _value, _status: None
            progress(1.0, "Apple TV streaming buffer ready")
            return PreparedMedia(
                str(session.manifest),
                kind,
                cached,
                info,
                streaming=True,
                stream_session=session,
                start_position_seconds=start_position_seconds,
            )
        except Exception:
            if session is not None:
                session.stop()
            raise

    def _start_copy_hls(
        self,
        source: Path,
        info: MediaInfo,
        progress: ProgressCallback,
        start_position_seconds: float,
        audio_stream: int = -1,
    ) -> HlsSession:
        ffmpeg, _ = self.locator.require()
        directory = (self.cache.directory / f"hls-{uuid.uuid4().hex}").resolve()
        segment_pattern = directory / "segment_%06d.m4s"
        command = [
            str(ffmpeg),
            "-hide_banner",
            "-y",
            # Keep the EVENT playlist's live edge moving at approximately
            # playback speed. Without pacing, stream-copy can generate hours
            # of segments in seconds; tvOS then chases the moving live edge
            # and abandons playback. Burst enough input for a quick startup,
            # then retain a small lead over the receiver.
            "-readrate",
            "1.05",
            "-readrate_initial_burst",
            "30",
            "-readrate_catchup",
            "1.5",
        ]
        if start_position_seconds > 0:
            command.extend(["-ss", f"{start_position_seconds:.3f}"])
        command.extend(
            [
                "-i",
                str(source.resolve()),
                "-map",
                "0:v:0",
                "-map",
                self._audio_map(audio_stream),
                "-c",
                "copy",
                "-sn",
                "-dn",
                "-avoid_negative_ts",
                "make_zero",
                *(
                    ["-tag:v", "hvc1"]
                    if info.video is not None
                    and info.video.codec_name.casefold() == "hevc"
                    else []
                ),
                "-f",
                "hls",
                "-hls_time",
                "4",
                "-hls_playlist_type",
                "event",
                "-hls_segment_type",
                "fmp4",
                "-hls_flags",
                "independent_segments+temp_file",
                "-hls_fmp4_init_filename",
                "init.mp4",
                "-hls_segment_filename",
                str(segment_pattern),
                "-progress",
                "pipe:1",
                "-nostats",
                str(directory / "index.m3u8"),
            ]
        )
        remaining_duration = max(0.0, info.duration_seconds - start_position_seconds)
        try:
            return HlsSession(directory, command, remaining_duration, progress)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    @staticmethod
    def _h264_video_options(backend: EncoderBackend) -> list[str]:
        if backend == EncoderBackend.NVIDIA:
            return [
                "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20", "-b:v", "0",
                "-g", "96", "-forced-idr", "1",
            ]
        if backend == EncoderBackend.AMD:
            return [
                "-c:v", "h264_amf",
                "-usage", "transcoding",
                "-quality", "quality",
                "-rc", "cqp",
                "-qp_i", "20",
                "-qp_p", "20",
                "-qp_b", "22",
                "-g", "96",
            ]
        if backend == EncoderBackend.INTEL:
            return [
                "-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "20",
                "-g", "96",
            ]
        return [
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-g", "96",
        ]

    @staticmethod
    def _hdr_video_options(
        backend: EncoderBackend, codec_name: str
    ) -> tuple[list[str], list[str], list[str]]:
        if backend == EncoderBackend.NVIDIA:
            decoder = {
                "av1": "av1_cuvid",
                "hevc": "hevc_cuvid",
                "h264": "h264_cuvid",
            }[codec_name.lower()]
            return (
                ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-c:v", decoder],
                [
                    "-vf",
                    "scale_cuda=w='min(3840,iw)':h=-2:format=p010le:"
                    "force_original_aspect_ratio=decrease:force_divisible_by=2",
                ],
                [
                    "-c:v", "hevc_nvenc", "-profile:v", "main10",
                    "-preset", "p2", "-tune", "hq", "-rc", "vbr",
                    "-cq", "24", "-b:v", "0", "-g", "96", "-forced-idr", "1",
                ],
            )
        if backend == EncoderBackend.AMD:
            scale = "min(1,min(3840/iw,2160/ih))"
            return (
                ["-hwaccel", "amf", "-hwaccel_output_format", "amf"],
                [
                    "-vf",
                    "vpp_amf="
                    f"w='trunc(iw*{scale}/2)*2':"
                    f"h='trunc(ih*{scale}/2)*2':format=p010le",
                ],
                [
                    "-c:v", "hevc_amf", "-profile:v", "main10", "-bitdepth", "10",
                    "-usage", "transcoding", "-quality", "balanced", "-rc", "cqp",
                    "-qp_i", "24", "-qp_p", "24", "-g", "96",
                ],
            )
        if backend == EncoderBackend.INTEL:
            scale = "min(1,min(3840/iw,2160/ih))"
            return (
                ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"],
                [
                    "-vf",
                    "scale_qsv="
                    f"w='trunc(iw*{scale}/2)*2':"
                    f"h='trunc(ih*{scale}/2)*2':format=p010le",
                ],
                [
                    "-c:v", "hevc_qsv", "-profile:v", "main10",
                    "-preset", "faster", "-global_quality", "24", "-g", "96",
                ],
            )
        raise ValueError("HDR streaming requires a hardware encoder")

    def _start_hardware_hls(
        self,
        source: str,
        info: MediaInfo,
        progress: ProgressCallback,
        start_position_seconds: float,
        audio_stream: int = -1,
        backend: EncoderBackend = EncoderBackend.NVIDIA,
    ) -> HlsSession:
        ffmpeg, _ = self.locator.require()
        if info.video is None:
            raise RuntimeError("HDR stream has no video track")
        input_options, filter_options, encoder_options = self._hdr_video_options(
            backend, info.video.codec_name
        )
        # FFmpeg runs with the HLS directory as its working directory so that
        # the relative init-file URI lands beside the playlist. Keep every
        # command path absolute even when a test or custom cache uses a
        # relative base directory.
        directory = (self.cache.directory / f"hls-{uuid.uuid4().hex}").resolve()
        segment_pattern = directory / "segment_%06d.m4s"
        command = [
            str(ffmpeg),
            "-hide_banner",
            "-y",
            # Hardware HDR conversion can run many times faster than playback.
            # Pace the input exactly like stream-copy HLS so tvOS never sees
            # hundreds of future EVENT segments and tries to fetch them at once.
            "-readrate",
            "1.05",
            "-readrate_initial_burst",
            "30",
            "-readrate_catchup",
            "1.5",
        ]
        if start_position_seconds > 0:
            command.extend(["-ss", f"{start_position_seconds:.3f}"])
        command.extend([
            *input_options,
            "-i", source,
            "-map", "0:v:0",
            "-map", self._audio_map(audio_stream),
            *filter_options,
            *encoder_options,
            "-tag:v", "hvc1",
            "-color_primaries", "bt2020",
            "-color_trc", "smpte2084",
            "-colorspace", "bt2020nc",
            "-force_key_frames", "expr:gte(t,n_forced*4)",
            "-c:a", "aac",
            "-b:a", "256k",
            "-ac", "2",
            "-f", "hls",
            "-hls_time", "4",
            "-hls_playlist_type", "event",
            "-hls_segment_type", "fmp4",
            "-hls_flags", "independent_segments+temp_file",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(segment_pattern),
            "-progress", "pipe:1",
            "-nostats",
            str(directory / "index.m3u8"),
        ])
        remaining_duration = max(0.0, info.duration_seconds - start_position_seconds)
        try:
            return HlsSession(directory, command, remaining_duration, progress)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def _start_transcode_hls(
        self,
        source: str,
        info: MediaInfo,
        subtitle: str,
        progress: ProgressCallback,
        start_position_seconds: float,
        audio_stream: int = -1,
        backend: EncoderBackend = EncoderBackend.NVIDIA,
        accelerated_input: bool = True,
    ) -> HlsSession:
        ffmpeg, _ = self.locator.require()
        directory = (self.cache.directory / f"hls-{uuid.uuid4().hex}").resolve()
        segment_pattern = directory / "segment_%06d.m4s"
        input_options: list[str] = []
        accelerated_filters = None
        if accelerated_input and self._nvidia_subtitle_pipeline_supported(
            info, subtitle, backend
        ):
            accelerated_filters = self._nvidia_subtitle_filter_arguments(
                info,
                subtitle,
                start_position_seconds,
            )
        if accelerated_filters is not None:
            input_options, filter_arguments = accelerated_filters
            extra_inputs: list[str] = []
        else:
            extra_inputs, filter_arguments = self._filter_arguments(
                info,
                subtitle,
                start_position_seconds,
            )
        if start_position_seconds > 0 and extra_inputs:
            # External bitmap subtitles are a separate demuxer input and must
            # be seeked alongside the main media input.
            extra_inputs = [
                "-ss",
                f"{start_position_seconds:.3f}",
                *extra_inputs,
            ]
        command = [
            str(ffmpeg),
            "-hide_banner",
            "-y",
            # Build an initial burst quickly, then keep a stable lead over tvOS.
            # An unpaced EVENT playlist can move its live edge faster than the
            # receiver consumes it and cause playback to be abandoned.
            "-readrate",
            "1.05",
            "-readrate_initial_burst",
            "30",
            "-readrate_catchup",
            "1.5",
        ]
        if start_position_seconds > 0:
            command.extend(["-ss", f"{start_position_seconds:.3f}"])
        command.extend(
            [
                *input_options,
                "-i",
                source,
                *extra_inputs,
                *filter_arguments,
                "-map",
                self._audio_map(audio_stream),
                *self._h264_video_options(backend),
                "-tag:v",
                "avc1",
                "-force_key_frames",
                "expr:gte(t,n_forced*4)",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ac",
                "2",
                "-sn",
                "-dn",
                "-avoid_negative_ts",
                "make_zero",
                "-f",
                "hls",
                "-hls_time",
                "4",
                "-hls_playlist_type",
                "event",
                "-hls_segment_type",
                "fmp4",
                "-hls_flags",
                "independent_segments+temp_file",
                "-hls_fmp4_init_filename",
                "init.mp4",
                "-hls_segment_filename",
                str(segment_pattern),
                "-progress",
                "pipe:1",
                "-nostats",
                str(directory / "index.m3u8"),
            ]
        )
        remaining_duration = max(0.0, info.duration_seconds - start_position_seconds)
        try:
            return HlsSession(directory, command, remaining_duration, progress)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def _base_command(self, source: str) -> list[str]:
        ffmpeg, _ = self.locator.require()
        return [str(ffmpeg), "-hide_banner", "-y", "-i", source]

    @staticmethod
    def _audio_map(audio_stream: int) -> str:
        return f"0:a:{audio_stream}?" if audio_stream >= 0 else "0:a:0?"

    def _run_remux(
        self,
        source: str,
        output: Path,
        info: MediaInfo,
        audio_stream: int,
        progress: ProgressCallback,
        cancel: threading.Event,
    ) -> None:
        command = self._base_command(source) + [
            "-map", "0:v:0", "-map", self._audio_map(audio_stream), "-c", "copy", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", str(output),
        ]
        self._run(command, info.duration_seconds, progress, cancel)

    @staticmethod
    def _escape_subtitle_path(path: str) -> str:
        normalized = Path(path).resolve().as_posix()
        for character in ("\\", ":", "'", ",", "[", "]", ";"):
            normalized = normalized.replace(character, f"\\{character}")
        return normalized

    def _subtitle_filters(
        self,
        info: MediaInfo,
        subtitle: str,
        subtitle_offset_seconds: float,
    ) -> list[str]:
        if not subtitle:
            return []
        filters: list[str] = []
        offset = max(0.0, subtitle_offset_seconds)
        if offset > 0:
            # Input seeking resets the video timeline to zero, while the
            # subtitles filter opens the original caption source from its
            # beginning. Temporarily restore the absolute movie timestamp for
            # caption evaluation, then reset output PTS for HLS.
            filters.append(f"setpts=PTS+{offset:.3f}/TB")
        if subtitle.startswith("embedded:"):
            stream = subtitle.split(":", 1)[1]
            filters.append(
                f"subtitles='{self._escape_subtitle_path(info.source)}':si={stream}"
            )
        else:
            filters.append(f"subtitles='{self._escape_subtitle_path(subtitle)}'")
        if offset > 0:
            filters.append("setpts=PTS-STARTPTS")
        return filters

    def _video_filters(
        self,
        info: MediaInfo,
        subtitle: str,
        subtitle_offset_seconds: float = 0.0,
    ) -> str:
        filters = self._subtitle_filters(
            info,
            subtitle,
            subtitle_offset_seconds,
        )
        if info.hdr:
            filters.extend([
                "zscale=t=linear:npl=100",
                "format=gbrpf32le",
                "zscale=p=bt709",
                "tonemap=hable:desat=0",
                "zscale=t=bt709:m=bt709:r=tv",
            ])
        filters.extend([
            "scale=w='min(1920,iw)':h=-2:force_original_aspect_ratio=decrease",
            "format=yuv420p",
        ])
        return ",".join(filters)

    @staticmethod
    def _nvidia_subtitle_pipeline_supported(
        info: MediaInfo,
        subtitle: str,
        backend: EncoderBackend,
    ) -> bool:
        video = info.video
        return bool(
            backend == EncoderBackend.NVIDIA
            and subtitle
            and video is not None
            and video.codec_name.casefold() in {"av1", "hevc", "h264"}
            and not subtitle_is_bitmap(info, subtitle)
        )

    @staticmethod
    def _is_nvidia_subtitle_pipeline_failure(
        error: RuntimeError | TimeoutError,
    ) -> bool:
        detail = str(error).casefold()
        return any(
            marker in detail
            for marker in (
                "cuda",
                "cuvid",
                "nvdec",
                "hwdownload",
                "scale_cuda",
                "device setup failed",
                "impossible to convert between the formats",
            )
        )

    def _nvidia_subtitle_filter_arguments(
        self,
        info: MediaInfo,
        subtitle: str,
        subtitle_offset_seconds: float,
    ) -> tuple[list[str], list[str]] | None:
        video = info.video
        if video is None:
            return None
        decoder = {
            "av1": "av1_cuvid",
            "hevc": "hevc_cuvid",
            "h264": "h264_cuvid",
        }.get(video.codec_name.casefold())
        if decoder is None or subtitle_is_bitmap(info, subtitle):
            return None

        download_format = "p010le" if info.hdr else "nv12"
        filters = [
            "scale_cuda=w='min(1920,iw)':h=-2:"
            f"format={download_format}:"
            "force_original_aspect_ratio=decrease:force_divisible_by=2",
            "hwdownload",
            f"format={download_format}",
            *self._subtitle_filters(
                info,
                subtitle,
                subtitle_offset_seconds,
            ),
        ]
        if info.hdr:
            # Tone-map after the CUDA resize. Performing libass and float HDR
            # filtering at 1080p instead of 4K is the difference between a
            # producer that eventually starves Apple TV and one with ample
            # real-time headroom.
            filters.extend(
                [
                    "zscale=t=linear:npl=100",
                    "format=gbrpf32le",
                    "zscale=p=bt709",
                    "tonemap=hable:desat=0",
                    "zscale=t=bt709:m=bt709:r=tv",
                ]
            )
        filters.append("format=yuv420p")
        return (
            [
                "-hwaccel",
                "cuda",
                "-hwaccel_output_format",
                "cuda",
                "-c:v",
                decoder,
            ],
            ["-map", "0:v:0", "-vf", ",".join(filters)],
        )

    def _filter_arguments(
        self,
        info: MediaInfo,
        subtitle: str,
        subtitle_offset_seconds: float = 0.0,
    ) -> tuple[list[str], list[str]]:
        if not subtitle_is_bitmap(info, subtitle):
            return [], [
                "-map",
                "0:v:0",
                "-vf",
                self._video_filters(
                    info,
                    subtitle,
                    subtitle_offset_seconds,
                ),
            ]

        if subtitle.startswith("embedded:"):
            subtitle_index = int(subtitle.split(":", 1)[1])
            extra_inputs: list[str] = []
            subtitle_input = f"[0:s:{subtitle_index}]"
        else:
            extra_inputs = ["-i", subtitle]
            subtitle_input = "[1:s:0]"
        filters = self._video_filters(info, "")
        graph = (
            f"[0:v:0]{subtitle_input}"
            f"overlay=eof_action=pass:repeatlast=0,{filters}[vout]"
        )
        return extra_inputs, ["-filter_complex", graph, "-map", "[vout]"]

    def _run_transcode(
        self,
        source: str,
        output: Path,
        info: MediaInfo,
        subtitle: str,
        audio_stream: int,
        backend: EncoderBackend,
        progress: ProgressCallback,
        cancel: threading.Event,
    ) -> None:
        video = self._h264_video_options(backend)
        extra_inputs, filter_arguments = self._filter_arguments(info, subtitle)
        command = self._base_command(source) + extra_inputs + [
            *filter_arguments,
            "-map", self._audio_map(audio_stream),
            *video, "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", str(output),
        ]
        self._run(command, info.duration_seconds, progress, cancel)

    @staticmethod
    def _run(
        command: list[str],
        duration_seconds: float,
        progress: ProgressCallback,
        cancel: threading.Event,
    ) -> None:
        startup = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if cancel.is_set():
            raise ConversionCancelled("Conversion cancelled")
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=startup,
            )
        except OSError as error:
            raise RuntimeError(f"Unable to start FFmpeg: {error}") from error
        stderr_lines: list[str] = []

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                stderr_lines.append(line.rstrip())
                if len(stderr_lines) > 80:
                    stderr_lines.pop(0)

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()
        watcher_stop = threading.Event()

        def watch_cancel() -> None:
            while not watcher_stop.wait(0.1):
                if not cancel.is_set():
                    continue
                try:
                    if process.poll() is None:
                        process.terminate()
                except OSError:
                    pass
                return

        cancel_thread = threading.Thread(target=watch_cancel, daemon=True)
        cancel_thread.start()
        assert process.stdout is not None
        out_seconds = 0.0
        speed = 0.0
        try:
            for raw in process.stdout:
                key, _, value = raw.strip().partition("=")
                if key in {"out_time_us", "out_time_ms"} and duration_seconds > 0:
                    try:
                        out_seconds = int(value or 0) / 1_000_000
                    except ValueError:
                        continue
                elif key == "speed":
                    try:
                        speed = float(value.rstrip("x"))
                    except ValueError:
                        speed = 0.0
                elif key == "progress":
                    ratio, status = conversion_progress(out_seconds, duration_seconds, speed)
                    try:
                        progress(ratio, status)
                    except Exception:
                        pass
            return_code = process.wait()
            stderr_thread.join(timeout=1)
            if cancel.is_set():
                raise ConversionCancelled("Conversion cancelled")
            if return_code != 0:
                detail = "\n".join(stderr_lines[-12:])
                raise RuntimeError(detail or f"FFmpeg exited with code {return_code}")
        finally:
            watcher_stop.set()
            cancel_thread.join(timeout=1)
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
            stderr_thread.join(timeout=1)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    try:
                        stream.close()
                    except OSError:
                        pass
