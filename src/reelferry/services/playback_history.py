from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


HISTORY_VERSION = 1
SAMPLE_BYTES = 64 * 1024
MIN_RESUME_MS = 10_000
MAX_FINISH_WINDOW_MS = 120_000
MIN_FINISH_WINDOW_MS = 15_000
AUDIO_MAX_FINISH_WINDOW_MS = 10_000
AUDIO_MIN_FINISH_WINDOW_MS = 3_000
DEFAULT_MAX_ENTRIES = 500
DEFAULT_RETENTION_DAYS = 730
AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".m4b",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
# This salt is part of the durable on-disk media identity introduced before
# the ReelFerry rename. Changing it would orphan every saved resume position.
MEDIA_IDENTITY_SALT = b"xMediaPlayerx-media-v1\0"


@dataclass(frozen=True, slots=True)
class MediaIdentity:
    key: str
    path: str
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class ResumeRecord:
    identity: MediaIdentity
    position_ms: int
    duration_ms: int
    title: str
    updated_at: float


def finish_window_ms(duration_ms: int, *, audio: bool = False) -> int:
    if duration_ms <= 0:
        return 0
    if audio:
        return min(
            AUDIO_MAX_FINISH_WINDOW_MS,
            max(AUDIO_MIN_FINISH_WINDOW_MS, int(duration_ms * 0.001)),
        )
    return min(
        MAX_FINISH_WINDOW_MS,
        max(MIN_FINISH_WINDOW_MS, int(duration_ms * 0.02)),
    )


def is_effectively_complete(
    position_ms: int,
    duration_ms: int,
    *,
    audio: bool = False,
) -> bool:
    return (
        duration_ms > 0
        and position_ms
        >= max(0, duration_ms - finish_window_ms(duration_ms, audio=audio))
    )


class PlaybackHistory:
    """Durable resume positions for local media, stored as one atomic JSON file."""

    def __init__(
        self,
        path: Path,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.max_entries = max(1, int(max_entries))
        self.retention_seconds = max(1, int(retention_days)) * 86_400
        self.clock = clock
        self.log = logging.getLogger("reelferry.playback_history")
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, object]] = {}
        self._load()

    @staticmethod
    def identify(path: str | Path) -> MediaIdentity:
        resolved = Path(path).resolve()
        stat = resolved.stat()
        digest = hashlib.sha256()
        digest.update(MEDIA_IDENTITY_SALT)
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        with resolved.open("rb") as stream:
            digest.update(stream.read(SAMPLE_BYTES))
            if stat.st_size > SAMPLE_BYTES:
                stream.seek(max(0, stat.st_size - SAMPLE_BYTES))
                digest.update(stream.read(SAMPLE_BYTES))
        return MediaIdentity(
            digest.hexdigest(),
            str(resolved),
            int(stat.st_size),
            int(stat.st_mtime_ns),
        )

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, identity: MediaIdentity) -> ResumeRecord | None:
        with self._lock:
            raw = self._entries.get(identity.key)
            if raw is None:
                return None
            try:
                position_ms = int(raw["position_ms"])
                duration_ms = int(raw.get("duration_ms", 0))
                updated_at = float(raw["updated_at"])
                is_audio = Path(identity.path).suffix.casefold() in AUDIO_EXTENSIONS
                if (
                    position_ms < MIN_RESUME_MS
                    or is_effectively_complete(
                        position_ms,
                        duration_ms,
                        audio=is_audio,
                    )
                    or updated_at < self.clock() - self.retention_seconds
                ):
                    return None
                return ResumeRecord(
                    identity,
                    position_ms,
                    duration_ms,
                    str(raw.get("title", Path(identity.path).stem)),
                    updated_at,
                )
            except (KeyError, TypeError, ValueError):
                return None

    def save(
        self,
        identity: MediaIdentity,
        position_ms: int,
        duration_ms: int,
        title: str,
    ) -> bool:
        position_ms = max(0, int(position_ms))
        duration_ms = max(0, int(duration_ms))
        with self._lock:
            is_audio = (
                Path(identity.path).suffix.casefold() in AUDIO_EXTENSIONS
            )
            if is_effectively_complete(
                position_ms,
                duration_ms,
                audio=is_audio,
            ):
                changed = self._entries.pop(identity.key, None) is not None
                if changed:
                    self._write()
                return changed
            # Do not destroy a useful checkpoint when a receiver briefly
            # reports zero or QMediaPlayer resets during a source transition.
            if position_ms < MIN_RESUME_MS:
                return False
            self._entries[identity.key] = {
                "path": identity.path,
                "size": identity.size,
                "modified_ns": identity.modified_ns,
                "position_ms": position_ms,
                "duration_ms": duration_ms,
                "title": str(title),
                "updated_at": self.clock(),
            }
            self._prune()
            self._write()
            return True

    def remove(self, identity: MediaIdentity) -> bool:
        with self._lock:
            changed = self._entries.pop(identity.key, None) is not None
            if changed:
                self._write()
            return changed

    def clear(self) -> None:
        with self._lock:
            if not self._entries:
                return
            self._entries.clear()
            self._write()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("playback-history root is not an object")
            entries = payload.get("items", {})
            if (
                payload.get("version") != HISTORY_VERSION
                or not isinstance(entries, dict)
            ):
                raise ValueError("unsupported playback-history format")
            self._entries = {
                str(key): value
                for key, value in entries.items()
                if isinstance(key, str) and isinstance(value, dict)
            }
            self._prune()
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
            self.log.warning(
                "Playback history could not be loaded; starting clean: %s",
                error,
            )
            self._entries = {}

    def _prune(self) -> None:
        cutoff = self.clock() - self.retention_seconds
        valid: list[tuple[str, dict[str, object], float]] = []
        for key, value in self._entries.items():
            try:
                updated_at = float(value["updated_at"])
                position_ms = int(value["position_ms"])
                duration_ms = int(value.get("duration_ms", 0))
                is_audio = (
                    Path(str(value.get("path", ""))).suffix.casefold()
                    in AUDIO_EXTENSIONS
                )
            except (KeyError, TypeError, ValueError):
                continue
            if (
                updated_at < cutoff
                or position_ms < MIN_RESUME_MS
                or is_effectively_complete(
                    position_ms,
                    duration_ms,
                    audio=is_audio,
                )
            ):
                continue
            valid.append((key, value, updated_at))
        valid.sort(key=lambda item: item[2], reverse=True)
        self._entries = {
            key: value for key, value, _updated_at in valid[: self.max_entries]
        }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "version": HISTORY_VERSION,
            "items": self._entries,
        }
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
