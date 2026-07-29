from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging
from pathlib import Path
import threading
from typing import Callable

from PySide6.QtCore import QObject, Property, Signal, Slot

from xmediaplayerx.errors import error_message
from xmediaplayerx.services.media import FFmpegLocator
from xmediaplayerx.services.media_tools import (
    MediaToolsCancelled,
    MediaToolsInstaller,
)


class MediaToolsController(QObject):
    changed = Signal()
    promptRequested = Signal()
    errorOccurred = Signal(str)
    _completed = Signal(object)

    def __init__(
        self,
        locator: FFmpegLocator,
        tools_dir: Path,
        installer_factory: Callable[[Path], MediaToolsInstaller] = MediaToolsInstaller,
    ) -> None:
        super().__init__()
        self.locator = locator
        self.installer = installer_factory(tools_dir)
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="media-tools"
        )
        self.cancel_event = threading.Event()
        self.future: Future | None = None
        self._downloading = False
        self._progress = 0.0
        self._status = (
            "Media tools are ready"
            if locator.available
            else "Media tools are not installed"
        )
        self.log = logging.getLogger("xmediaplayerx.media_tools")
        self._completed.connect(self._finish)

    @Property(bool, notify=changed)
    def available(self) -> bool:
        return self.locator.available

    @Property(bool, notify=changed)
    def downloading(self) -> bool:
        return self._downloading

    @Property(float, notify=changed)
    def progress(self) -> float:
        return self._progress

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Slot()
    def requestInstallPrompt(self) -> None:
        if not self.available:
            self.promptRequested.emit()

    @Slot()
    def install(self) -> None:
        if self._downloading or self.available:
            return
        self.cancel_event.clear()
        self._downloading = True
        self._progress = 0.0
        self._status = "Downloading verified FFmpeg media tools…"
        self.changed.emit()

        def update(received: int, total: int) -> None:
            self._progress = min(1.0, received / max(1, total))
            self.changed.emit()

        self.future = self.executor.submit(
            self.installer.install, update, self.cancel_event
        )
        self.future.add_done_callback(self._completed.emit)

    @Slot()
    def cancel(self) -> None:
        if self._downloading:
            self.cancel_event.set()
            self._status = "Cancelling…"
            self.changed.emit()

    @Slot(object)
    def _finish(self, future: Future) -> None:
        self._downloading = False
        try:
            future.result()
            self.locator.refresh()
            if not self.locator.available:
                raise RuntimeError("Installed media tools could not be located")
            self._progress = 1.0
            self._status = "Media tools installed and ready"
        except MediaToolsCancelled:
            self._progress = 0.0
            self._status = "Media-tools installation cancelled"
        except Exception as error:
            self._progress = 0.0
            self._status = "Media-tools installation failed"
            self.log.warning("Media-tools installation failed", exc_info=True)
            self.errorOccurred.emit(
                error_message(error, "Media tools could not be installed")
            )
        self.changed.emit()

    def close(self) -> None:
        self.cancel_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
