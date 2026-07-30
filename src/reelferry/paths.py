from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import sys

from platformdirs import user_cache_dir, user_config_dir, user_log_dir


APP_NAME = "ReelFerry"
LEGACY_APP_NAME = "xMediaPlayerx"
_LOGGER = logging.getLogger("reelferry.paths")


def _merge_legacy_tree(source: Path, target: Path) -> None:
    """Move legacy data into a new brand directory without overwriting files."""
    if not source.exists() or source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        try:
            source.replace(target)
        except OSError:
            shutil.move(str(source), str(target))
        return
    if not source.is_dir() or not target.is_dir():
        return
    for child in source.iterdir():
        _merge_legacy_tree(child, target / child.name)
    try:
        source.rmdir()
    except OSError:
        # Conflicting or locked legacy files are deliberately retained.
        pass


def migrate_legacy_app_data(
    legacy_config: Path,
    legacy_cache: Path,
    legacy_logs: Path,
    config: Path,
    cache: Path,
    logs: Path,
) -> None:
    """Adopt settings, credentials, history, tools, logs, and cast cache."""
    migrations = (
        (legacy_config, config),
        (legacy_cache, cache),
        (legacy_logs, logs),
    )
    for source, target in migrations:
        try:
            _merge_legacy_tree(source, target)
        except OSError:
            _LOGGER.warning(
                "Could not migrate legacy application data from %s to %s",
                source,
                target,
                exc_info=True,
            )


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
    def default(cls, *, migrate_legacy: bool = True) -> "AppPaths":
        if override := os.environ.get("REELFERRY_DATA_DIR"):
            config = Path(override).expanduser().resolve()
            cache = config / "Cache"
            logs = config / "Logs"
            migrate_legacy = False
        else:
            config = Path(
                user_config_dir(APP_NAME, appauthor=False, roaming=False)
            )
            cache = Path(user_cache_dir(APP_NAME, appauthor=False))
            logs = Path(user_log_dir(APP_NAME, appauthor=False))
        if migrate_legacy:
            migrate_legacy_app_data(
                Path(
                    user_config_dir(
                        LEGACY_APP_NAME,
                        appauthor=False,
                        roaming=False,
                    )
                ),
                Path(user_cache_dir(LEGACY_APP_NAME, appauthor=False)),
                Path(user_log_dir(LEGACY_APP_NAME, appauthor=False)),
                config,
                cache,
                logs,
            )
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
    if bundle := (
        os.environ.get("REELFERRY_FFMPEG_DIR")
        or os.environ.get("XMEDIAPLAYERX_FFMPEG_DIR")
    ):
        roots.insert(0, Path(bundle))
    return roots
