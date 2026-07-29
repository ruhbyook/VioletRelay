from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Callable, Protocol
from urllib.parse import quote

try:
    import winreg
except ImportError:  # pragma: no cover - the application targets Windows
    winreg = None


REGISTERED_NAME = "xMediaPlayerx"
PROG_ID = "xMediaPlayerx.Video"
CAPABILITIES_PATH = r"Software\xMediaPlayerx\Capabilities"
REGISTERED_APPS_PATH = r"Software\RegisteredApplications"
PROG_ID_PATH = rf"Software\Classes\{PROG_ID}"
APPLICATION_PATH = r"Software\Classes\Applications\xMediaPlayerx.exe"
VIDEO_EXTENSIONS = (
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".vob",
    ".flv",
    ".ogv",
    ".3gp",
    ".mts",
    ".ts",
    ".m2ts",
    ".mp3",
    ".m4a",
    ".m4b",
    ".aac",
    ".flac",
    ".wav",
    ".ogg",
    ".opus",
    ".wma",
)


class RegistryStore(Protocol):
    def get_value(self, path: str, name: str = "") -> str | None: ...

    def set_value(self, path: str, name: str, value: str) -> None: ...

    def delete_value(self, path: str, name: str) -> None: ...

    def delete_tree(self, path: str) -> None: ...


class WinRegistryStore:
    """Small HKCU-only registry adapter so registration logic is testable."""

    def __init__(self) -> None:
        if winreg is None:
            raise RuntimeError("Windows registry APIs are unavailable")

    def get_value(self, path: str, name: str = "") -> str | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                value, _kind = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def set_value(self, path: str, name: str, value: str) -> None:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_value(self, path: str, name: str) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    def delete_tree(self, path: str) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                path,
                0,
                winreg.KEY_READ | winreg.KEY_WRITE,
            ) as key:
                children: list[str] = []
                index = 0
                while True:
                    try:
                        children.append(winreg.EnumKey(key, index))
                        index += 1
                    except OSError:
                        break
            for child in children:
                self.delete_tree(path + "\\" + child)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


@dataclass(frozen=True, slots=True)
class RegistrationState:
    available: bool
    registered: bool
    needs_repair: bool
    executable: str = ""
    open_with_registered: bool = False


def portable_executable() -> Path | None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    return executable if executable.suffix.lower() == ".exe" else None


def _notify_association_change() -> None:
    # SHCNE_ASSOCCHANGED | SHCNF_IDLIST tells Explorer and Settings to refresh.
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


class WindowsDefaultApps:
    def __init__(
        self,
        executable: Path | None = None,
        store: RegistryStore | None = None,
        opener: Callable[[str], object] | None = None,
        notifier: Callable[[], None] | None = None,
    ) -> None:
        self.executable = (executable or portable_executable())
        if self.executable is not None:
            self.executable = self.executable.resolve()
        self.store = store or WinRegistryStore()
        self.opener = opener or getattr(os, "startfile", None)
        self.notifier = notifier or _notify_association_change

    @property
    def expected_command(self) -> str:
        if self.executable is None:
            return ""
        return f'"{self.executable}" "%1"'

    def state(self) -> RegistrationState:
        available = self.executable is not None
        if not available:
            return RegistrationState(False, False, False)
        registered_path = self.store.get_value(
            REGISTERED_APPS_PATH, REGISTERED_NAME
        )
        registered = registered_path is not None
        command = self.store.get_value(PROG_ID_PATH + r"\shell\open\command")
        application_command = self.store.get_value(
            APPLICATION_PATH + r"\shell\open\command"
        )
        supported_types_valid = all(
            self.store.get_value(
                APPLICATION_PATH + r"\SupportedTypes", extension
            )
            is not None
            for extension in VIDEO_EXTENSIONS
        )
        open_with_progids_valid = all(
            self.store.get_value(
                self._open_with_progids_path(extension), PROG_ID
            )
            is not None
            for extension in VIDEO_EXTENSIONS
        )
        commands_valid = all(
            value is not None
            and os.path.normcase(value) == os.path.normcase(self.expected_command)
            for value in (command, application_command)
        )
        open_with_registered = (
            commands_valid
            and supported_types_valid
            and open_with_progids_valid
        )
        open_with_present = any(
            (
                command is not None,
                application_command is not None,
                any(
                    self.store.get_value(
                        self._open_with_progids_path(extension), PROG_ID
                    )
                    is not None
                    for extension in VIDEO_EXTENSIONS
                ),
            )
        )
        associations_valid = all(
            self.store.get_value(CAPABILITIES_PATH + r"\FileAssociations", extension)
            == PROG_ID
            for extension in VIDEO_EXTENSIONS
        )
        needs_repair = (
            open_with_present and not open_with_registered
        ) or (
            registered
            and (
                registered_path != CAPABILITIES_PATH
                or not open_with_registered
                or not associations_valid
            )
        )
        return RegistrationState(
            True,
            registered,
            needs_repair,
            str(self.executable),
            open_with_registered,
        )

    @staticmethod
    def _open_with_progids_path(extension: str) -> str:
        return rf"Software\Classes\{extension}\OpenWithProgids"

    def _write_open_with_registration(self) -> None:
        if self.executable is None:
            raise RuntimeError(
                "Windows file registration is available in the portable build"
            )
        executable = str(self.executable)
        icon = f'"{executable}",0'

        self.store.set_value(PROG_ID_PATH, "", "xMediaPlayerx Video")
        self.store.set_value(PROG_ID_PATH, "FriendlyTypeName", "xMediaPlayerx Video")
        self.store.set_value(PROG_ID_PATH + r"\DefaultIcon", "", icon)
        self.store.set_value(
            PROG_ID_PATH + r"\shell\open\command", "", self.expected_command
        )

        self.store.set_value(APPLICATION_PATH, "FriendlyAppName", REGISTERED_NAME)
        self.store.set_value(
            APPLICATION_PATH + r"\shell\open\command", "", self.expected_command
        )
        for extension in VIDEO_EXTENSIONS:
            self.store.set_value(
                APPLICATION_PATH + r"\SupportedTypes", extension, ""
            )
            # Microsoft recommends OpenWithProgids over the legacy
            # OpenWithList. An empty REG_SZ value makes xMediaPlayerx an
            # available handler without taking ownership of the extension.
            self.store.set_value(
                self._open_with_progids_path(extension), PROG_ID, ""
            )

    def register_open_with(self) -> RegistrationState:
        self._write_open_with_registration()
        self.notifier()
        return self.state()

    def register(self) -> RegistrationState:
        self._write_open_with_registration()
        assert self.executable is not None
        executable = str(self.executable)
        icon = f'"{executable}",0'

        self.store.set_value(
            CAPABILITIES_PATH,
            "ApplicationDescription",
            "Local media playback and Apple TV casting",
        )
        self.store.set_value(CAPABILITIES_PATH, "ApplicationName", REGISTERED_NAME)
        self.store.set_value(CAPABILITIES_PATH, "ApplicationIcon", icon)
        for extension in VIDEO_EXTENSIONS:
            self.store.set_value(
                CAPABILITIES_PATH + r"\FileAssociations", extension, PROG_ID
            )
        self.store.set_value(
            REGISTERED_APPS_PATH, REGISTERED_NAME, CAPABILITIES_PATH
        )
        self.notifier()
        return self.state()

    def unregister(self) -> None:
        errors: list[Exception] = []
        operations: list[Callable[[], None]] = [
            lambda: self.store.delete_value(REGISTERED_APPS_PATH, REGISTERED_NAME),
            lambda: self.store.delete_tree(CAPABILITIES_PATH),
            lambda: self.store.delete_tree(PROG_ID_PATH),
            lambda: self.store.delete_tree(APPLICATION_PATH),
        ]
        operations.extend(
            lambda extension=extension: self.store.delete_value(
                self._open_with_progids_path(extension), PROG_ID
            )
            for extension in VIDEO_EXTENSIONS
        )
        operations.append(self.notifier)
        for operation in operations:
            try:
                operation()
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError(
                "Default-player registration could not be completely removed"
            ) from errors[0]

    def open_default_apps(self) -> str:
        if self.opener is None:
            raise RuntimeError("Windows Settings could not be opened")
        uri = (
            "ms-settings:defaultapps?registeredAppUser="
            + quote(REGISTERED_NAME, safe="")
        )
        self.opener(uri)
        return uri
