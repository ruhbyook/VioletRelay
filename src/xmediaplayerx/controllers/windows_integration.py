from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Property, Signal, Slot

from xmediaplayerx.services.windows_integration import (
    RegistrationState,
    WindowsDefaultApps,
)
from xmediaplayerx.errors import error_message


class WindowsIntegrationController(QObject):
    changed = Signal()
    errorOccurred = Signal(str)

    def __init__(self, service: WindowsDefaultApps | None = None) -> None:
        super().__init__()
        self.log = logging.getLogger("xmediaplayerx.windows")
        self.service: WindowsDefaultApps | None = None
        self._initial_error = ""
        try:
            self.service = service or WindowsDefaultApps()
            self._state = self.service.state()
        except Exception as error:
            self._initial_error = error_message(
                error, "Windows default-player integration is unavailable"
            )
            self._state = RegistrationState(False, False, False)

    @Property(bool, notify=changed)
    def available(self) -> bool:
        return self._state.available

    @Property(bool, notify=changed)
    def registered(self) -> bool:
        return self._state.registered

    @Property(bool, notify=changed)
    def openWithRegistered(self) -> bool:
        return self._state.open_with_registered

    @Property(bool, notify=changed)
    def needsRepair(self) -> bool:
        return self._state.needs_repair

    @Property(str, notify=changed)
    def statusText(self) -> str:
        if not self._state.available:
            if self._initial_error:
                return f"Default-player setup is unavailable: {self._initial_error}"
            return "Default-player setup is available in the portable Windows build."
        if self._state.needs_repair:
            return "The portable folder moved or Windows registration is incomplete. Repair it to restore Open with."
        if self._state.registered:
            return "Available in Open with. Choose which video types use it by default in Windows Settings."
        if self._state.open_with_registered:
            return "Available in the Windows Open with menu. Your current defaults are unchanged."
        return "Register xMediaPlayerx to add it to the Windows Open with menu."

    @Property(str, notify=changed)
    def actionText(self) -> str:
        if self._state.registered:
            return "Choose default video types"
        return "Make xMediaPlayerx a default player"

    @Property(str, notify=changed)
    def openWithActionText(self) -> str:
        if self._state.needs_repair:
            return "Repair Open with registration"
        if self._state.open_with_registered:
            return "Registered for Open with"
        return "Register for Open with"

    def _set_state(self, state: RegistrationState) -> None:
        self._state = state
        self.changed.emit()

    @Slot()
    def refresh(self) -> None:
        if self.service is None:
            self.errorOccurred.emit(
                self._initial_error or "Windows default-player integration is unavailable"
            )
            return
        try:
            self._set_state(self.service.state())
            self._initial_error = ""
        except Exception as error:
            self.errorOccurred.emit(
                error_message(error, "Default-player status could not be read")
            )

    @Slot()
    def ensureOpenWith(self) -> None:
        """Register silently at startup without changing any file defaults."""
        if self.service is None or not self._state.available:
            return
        try:
            if not self._state.open_with_registered or self._state.needs_repair:
                if self._state.registered:
                    # Preserve and repair the Default Apps capabilities if a
                    # previously registered portable folder was moved.
                    self._set_state(self.service.register())
                else:
                    self._set_state(self.service.register_open_with())
        except Exception:
            # Startup integration must never prevent media playback or show a
            # disruptive dialog. The Settings panel keeps the explicit retry.
            self.log.warning(
                "Automatic Open with registration failed",
                exc_info=True,
            )
            try:
                self._set_state(self.service.state())
            except Exception:
                pass

    @Slot()
    def registerForOpenWith(self) -> None:
        if self.service is None:
            self.errorOccurred.emit(
                self._initial_error or "Windows file integration is unavailable"
            )
            return
        try:
            if self._state.registered:
                self._set_state(self.service.register())
            else:
                self._set_state(self.service.register_open_with())
        except Exception as error:
            self.errorOccurred.emit(
                error_message(error, "Open with registration failed")
            )

    @Slot()
    def registerAndChooseDefaults(self) -> None:
        if self.service is None:
            self.errorOccurred.emit(
                self._initial_error or "Windows default-player integration is unavailable"
            )
            return
        if self._initial_error and not self._state.available:
            self.errorOccurred.emit(self._initial_error)
            return
        try:
            if not self._state.registered or self._state.needs_repair:
                self._set_state(self.service.register())
            self.service.open_default_apps()
        except Exception as error:
            self.errorOccurred.emit(
                error_message(error, "Default-player setup failed")
            )

    @Slot()
    def unregister(self) -> None:
        if self.service is None:
            self.errorOccurred.emit(
                self._initial_error or "Windows file integration is unavailable"
            )
            return
        try:
            self.service.unregister()
            self._set_state(self.service.state())
        except Exception as error:
            self.errorOccurred.emit(
                error_message(error, "Windows file integration could not be removed")
            )
