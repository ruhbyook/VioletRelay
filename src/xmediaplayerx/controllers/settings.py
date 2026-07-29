from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from xmediaplayerx.services.cache import CastCache
from xmediaplayerx.settings import SettingsStore


class AppSettingsController(QObject):
    """Small QML boundary for persistent non-playback settings."""

    changed = Signal()
    errorOccurred = Signal(str)

    def __init__(
        self,
        settings: SettingsStore,
        cache: CastCache,
        diagnostics_directory: Path | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.cache = cache
        self.diagnostics_directory = diagnostics_directory
        self._status = ""
        self.log = logging.getLogger("xmediaplayerx.controller.settings")

    @Property(int, notify=changed)
    def cacheLimitGb(self) -> int:
        return int(self.settings.get("cache_limit_gb", 20))

    @Property(str, notify=changed)
    def cacheUsageText(self) -> str:
        return self._format_bytes(self.cache.usage_bytes())

    @Property(str, notify=changed)
    def cacheStatus(self) -> str:
        return self._status

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, value))
        units = ("bytes", "KB", "MB", "GB", "TB")
        unit = units[0]
        for candidate in units:
            unit = candidate
            if size < 1024 or candidate == units[-1]:
                break
            size /= 1024
        if unit == "bytes":
            return f"{int(size)} {unit}"
        return f"{size:.1f} {unit}"

    @Slot(int)
    def setCacheLimitGb(self, value: int) -> None:
        try:
            self.settings.set("cache_limit_gb", int(value))
            limit = int(self.settings.get("cache_limit_gb", 20))
            self.cache.limit_bytes = limit * 1024**3
            removed = self.cache.enforce_limit()
            self._status = (
                f"Cache limit set to {limit} GB"
                + (f"; removed {len(removed)} old file(s)" if removed else "")
            )
            self.changed.emit()
        except Exception as error:
            self.log.warning("Cache limit could not be updated", exc_info=True)
            self.errorOccurred.emit(f"Cache limit could not be updated: {error}")

    @Slot()
    def clearCastCache(self) -> None:
        try:
            removed = self.cache.clear()
            self._status = (
                f"Removed {len(removed)} prepared cast "
                f"{'copy' if len(removed) == 1 else 'copies'}"
            )
            self.changed.emit()
        except Exception as error:
            self.log.warning("Cast cache could not be cleared", exc_info=True)
            self.errorOccurred.emit(f"Cast cache could not be cleared: {error}")

    @Slot()
    def refresh(self) -> None:
        self.changed.emit()

    @Slot()
    def openDiagnosticsFolder(self) -> None:
        if self.diagnostics_directory is None:
            self.errorOccurred.emit("The diagnostic log folder is unavailable")
            return
        try:
            self.diagnostics_directory.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(self.diagnostics_directory))  # type: ignore[attr-defined]
            else:
                raise OSError("Opening folders is only supported in the Windows build")
        except OSError as error:
            self.errorOccurred.emit(
                f"The diagnostic log folder could not be opened: {error}"
            )
