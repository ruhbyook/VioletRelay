from __future__ import annotations

import asyncio
import base64
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path

from pyatv.storage.file_storage import FileStorage


_LOGGER = logging.getLogger("reelferry.secure_storage")
_HEADER = "REELFERRY-DPAPI-1\n"
_LEGACY_HEADERS = ("XMEDIAPLAYERX-DPAPI-1\n",)
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class CredentialStorageError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("DPAPI credential storage requires Windows")


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    return blob, buffer


def _dpapi_protect(data: bytes) -> bytes:
    _require_windows()
    source, source_buffer = _input_blob(data)
    result = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "ReelFerry Apple TV pairing data",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    ):
        raise ctypes.WinError()
    del source_buffer
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    _require_windows()
    source, source_buffer = _input_blob(data)
    result = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    description = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        ctypes.byref(description),
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    ):
        raise ctypes.WinError()
    del source_buffer
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        if description:
            ctypes.windll.kernel32.LocalFree(description)
        ctypes.windll.kernel32.LocalFree(result.pbData)


class SecureFileStorage(FileStorage):
    """pyatv storage encrypted for the current Windows account with DPAPI."""

    def __init__(self, filename: str, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(filename, loop)
        self._needs_migration = False

    def _read_file(self) -> str:
        raw = Path(self._filename).read_text(encoding="utf-8")
        header = next(
            (
                candidate
                for candidate in (_HEADER, *_LEGACY_HEADERS)
                if raw.startswith(candidate)
            ),
            None,
        )
        if header is None:
            self._needs_migration = True
            return raw
        if header != _HEADER:
            self._needs_migration = True
        try:
            encoded = raw[len(header) :].strip()
            encrypted = base64.b64decode(encoded, validate=True)
            return _dpapi_unprotect(encrypted).decode("utf-8")
        except Exception as error:
            raise CredentialStorageError(
                "Apple TV pairing data could not be decrypted for this Windows account"
            ) from error

    def _save_file(self, dumped: dict) -> None:
        plaintext = (json.dumps(dumped, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        encrypted = _dpapi_protect(plaintext)
        payload = _HEADER + base64.b64encode(encrypted).decode("ascii") + "\n"
        target = Path(self._filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, target)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    async def load(self) -> None:
        try:
            await super().load()
        except (CredentialStorageError, json.JSONDecodeError, ValueError) as error:
            target = Path(self._filename)
            quarantine = target.with_name(
                f"{target.name}.unreadable-{os.urandom(6).hex()}"
            )
            try:
                target.replace(quarantine)
            except OSError:
                raise error
            self._needs_migration = False
            _LOGGER.error(
                "Unreadable Apple TV pairing data was moved to %s; pairing is required again",
                quarantine.name,
            )
            await super().load()
        if not self._needs_migration:
            return
        dumped = dict(self)
        try:
            await self._loop.run_in_executor(None, self._save_file, dumped)
        except Exception:
            # Loading existing pairing data is more important than migration. A later
            # save will retry encryption; never destroy a readable plaintext file.
            _LOGGER.warning(
                "Could not migrate Apple TV pairing data to DPAPI encryption",
                exc_info=True,
            )
            return
        self.update_hash(dumped)
        self._needs_migration = False
        _LOGGER.info("Migrated Apple TV pairing data to Windows DPAPI encryption")
