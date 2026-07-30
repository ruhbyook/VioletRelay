from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from xmediaplayerx.services.cache import CastCache
from xmediaplayerx.settings import SettingsStore
from xmediaplayerx.support import BITCOIN_ADDRESS, ETHEREUM_ADDRESS


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
        self._support_status = ""
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

    @Property(str, constant=True)
    def bitcoinAddress(self) -> str:
        return BITCOIN_ADDRESS

    @Property(str, constant=True)
    def ethereumAddress(self) -> str:
        return ETHEREUM_ADDRESS

    @Property(str, notify=changed)
    def supportStatus(self) -> str:
        return self._support_status

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

    def _copy_support_address(self, address: str, label: str) -> None:
        try:
            clipboard = QGuiApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("the Windows clipboard is unavailable")
            clipboard.setText(address)
            self._support_status = f"{label} address copied"
            self.changed.emit()
        except Exception as error:
            self.log.warning("Support address could not be copied", exc_info=True)
            self.errorOccurred.emit(f"The support address could not be copied: {error}")

    @Slot()
    def copyBitcoinAddress(self) -> None:
        self._copy_support_address(BITCOIN_ADDRESS, "Bitcoin")

    @Slot()
    def copyEthereumAddress(self) -> None:
        self._copy_support_address(ETHEREUM_ADDRESS, "Ethereum / USDC")

    @Slot()
    def clearSupportStatus(self) -> None:
        if self._support_status:
            self._support_status = ""
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
