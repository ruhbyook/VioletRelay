from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path


_LOGGER = logging.getLogger("xmediaplayerx.cache")


class CastCache:
    def __init__(self, directory: Path, limit_bytes: int):
        self.directory = directory
        self.limit_bytes = limit_bytes
        self._lock = threading.RLock()
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_for(
        source: str,
        subtitle: str = "",
        audio_stream: int = -1,
        profile: str = "airplay-1080p-v3",
        remote_identity: dict[str, object] | None = None,
    ) -> str:
        identity: dict[str, object] = {
            "source": source,
            "subtitle": subtitle,
            "audio_stream": audio_stream,
            "profile": profile,
        }
        if remote_identity:
            identity["remote_identity"] = remote_identity
        for key, value in (("source", source), ("subtitle", subtitle)):
            path = Path(value)
            try:
                if value and path.is_file():
                    stat = path.stat()
                    identity[f"{key}_size"] = stat.st_size
                    identity[f"{key}_mtime_ns"] = stat.st_mtime_ns
            except OSError:
                # The source is validated again before conversion. A racing file
                # deletion must not make cache-key generation crash the worker.
                pass
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def output_path(self, key: str) -> Path:
        return self.directory / f"{key}.mp4"

    def get(self, key: str) -> Path | None:
        with self._lock:
            path = self.output_path(key)
            try:
                if not path.is_file() or path.stat().st_size == 0:
                    return None
                now = time.time()
                os.utime(path, (now, now))
            except OSError as error:
                _LOGGER.warning("Cached cast copy is inaccessible: %s", error)
                return None
            return path

    def enforce_limit(self, protected: set[Path] | None = None) -> list[Path]:
        with self._lock:
            resolved_protected: set[Path] = set()
            for path in protected or set():
                try:
                    resolved_protected.add(path.resolve())
                except OSError:
                    continue
            entries = self._entries()
            total = sum(size for _path, size, _atime in entries)
            removed: list[Path] = []
            for path, size, _atime in sorted(entries, key=lambda item: item[2]):
                if total <= self.limit_bytes:
                    break
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if resolved in resolved_protected:
                    continue
                try:
                    path.unlink()
                    total -= size
                    removed.append(path)
                except OSError:
                    continue
            return removed

    def _entries(self) -> list[tuple[Path, int, float]]:
        entries: list[tuple[Path, int, float]] = []
        for path in self.directory.glob("*.mp4"):
            try:
                if path.is_file():
                    stat = path.stat()
                    entries.append((path, stat.st_size, stat.st_atime))
            except OSError:
                continue
        return entries

    def usage_bytes(self) -> int:
        with self._lock:
            return sum(size for _path, size, _atime in self._entries())

    def clear(self, protected: set[Path] | None = None) -> list[Path]:
        """Remove completed prepared copies, preserving explicitly active files."""
        with self._lock:
            protected_resolved: set[Path] = set()
            for path in protected or set():
                try:
                    protected_resolved.add(path.resolve())
                except OSError:
                    continue
            removed: list[Path] = []
            for path, _size, _atime in self._entries():
                try:
                    if path.resolve() in protected_resolved:
                        continue
                    path.unlink()
                    removed.append(path)
                except OSError:
                    _LOGGER.info("Prepared cast copy is currently in use: %s", path)
            return removed

    def clear_partials(self) -> None:
        with self._lock:
            for path in self.directory.glob("*.partial.mp4"):
                try:
                    path.unlink()
                except OSError:
                    _LOGGER.warning("Could not remove partial cast file: %s", path)
            for directory in self.directory.glob("hls-*"):
                if directory.is_dir():
                    import shutil

                    shutil.rmtree(directory, ignore_errors=True)
