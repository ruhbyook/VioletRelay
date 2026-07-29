from __future__ import annotations

import json
import logging
import math
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "volume": 0.8,
    "muted": False,
    "playback_rate": 1.0,
    "cache_limit_gb": 20,
    "preferred_device_id": "",
    "window": {"width": 1280, "height": 780, "maximized": False},
}

_LOGGER = logging.getLogger("xmediaplayerx.settings")


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._data = deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return
            except (json.JSONDecodeError, OSError) as error:
                _LOGGER.warning("Settings could not be loaded; using defaults: %s", error)
                return
            if not isinstance(loaded, dict):
                _LOGGER.warning("Settings root is not an object; using defaults")
                return
            self._merge(self._data, loaded)

    @staticmethod
    def _merge(
        target: dict[str, Any], source: dict[str, Any], prefix: str = ""
    ) -> None:
        for key, value in source.items():
            if key in target and isinstance(target[key], dict):
                if isinstance(value, dict):
                    SettingsStore._merge(target[key], value, f"{prefix}{key}.")
            elif key in target:
                target[key] = SettingsStore._validated_value(
                    f"{prefix}{key}", value, target[key]
                )

    @staticmethod
    def _validated_value(key: str, value: Any, default: Any) -> Any:
        if isinstance(default, bool):
            return value if isinstance(value, bool) else default
        if isinstance(default, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return default
            number = float(value)
            if not math.isfinite(number):
                return default
            bounds = {
                "volume": (0.0, 1.0),
                "playback_rate": (0.25, 3.0),
            }.get(key)
            return max(bounds[0], min(bounds[1], number)) if bounds else number
        if isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                return default
            bounds = {
                "cache_limit_gb": (1, 1000),
                "window.width": (640, 7680),
                "window.height": (360, 4320),
            }.get(key)
            return max(bounds[0], min(bounds[1], value)) if bounds else value
        if isinstance(default, str):
            return value if isinstance(value, str) else default
        return value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            current: Any = self._data
            for part in key.split("."):
                if not isinstance(current, dict) or part not in current:
                    return default
                current = current[part]
            return current

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            parts = key.split(".")
            current = self._data
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            existing = current.get(parts[-1], value)
            current[parts[-1]] = self._validated_value(key, value, existing)
            self.save()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            try:
                temporary.write_text(
                    json.dumps(self._data, indent=2), encoding="utf-8"
                )
                temporary.replace(self.path)
            except Exception:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
