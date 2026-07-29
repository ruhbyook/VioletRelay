from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_log_dir


@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    cache_dir: Path
    log_dir: Path
    settings_file: Path
    playback_history_file: Path
    airplay_storage_file: Path
    cast_cache_dir: Path
    tools_dir: Path

    @classmethod
    def default(cls) -> "AppPaths":
        config = Path(user_config_dir("xMediaPlayerx", appauthor=False, roaming=False))
        cache = Path(user_cache_dir("xMediaPlayerx", appauthor=False))
        logs = Path(user_log_dir("xMediaPlayerx", appauthor=False))
        return cls(
            config_dir=config,
            cache_dir=cache,
            log_dir=logs,
            settings_file=config / "settings.json",
            playback_history_file=config / "playback_history.json",
            airplay_storage_file=config / "pyatv.json",
            cast_cache_dir=cache / "casts",
            tools_dir=config / "tools",
        )

    def ensure(self) -> None:
        for directory in (
            self.config_dir,
            self.cache_dir,
            self.log_dir,
            self.cast_cache_dir,
            self.tools_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidate = base.joinpath(*parts)
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parent.joinpath(*parts)


def executable_search_roots() -> list[Path]:
    roots = [Path.cwd(), Path(sys.executable).resolve().parent, Path(__file__).resolve().parents[2]]
    if bundle_root := getattr(sys, "_MEIPASS", None):
        roots.insert(0, Path(bundle_root))
    if bundle := os.environ.get("XMEDIAPLAYERX_FFMPEG_DIR"):
        roots.insert(0, Path(bundle))
    return roots
