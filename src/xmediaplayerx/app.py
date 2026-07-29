from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from xmediaplayerx.controllers.airplay import AirPlayController
from xmediaplayerx.controllers.playback import PlaybackController
from xmediaplayerx.controllers.media_tools import MediaToolsController
from xmediaplayerx.controllers.settings import AppSettingsController
from xmediaplayerx.controllers.windows_integration import WindowsIntegrationController
from xmediaplayerx import __version__
from xmediaplayerx.errors import error_message
from xmediaplayerx.logging_utils import configure_logging
from xmediaplayerx.models import QueueModel
from xmediaplayerx.paths import AppPaths, resource_path
from xmediaplayerx.services.airplay import AsyncRuntime, UnavailableAsyncRuntime
from xmediaplayerx.services.cache import CastCache
from xmediaplayerx.services.converter import MediaPreparer
from xmediaplayerx.services.media import FFmpegLocator, MediaProbe, validate_media_url
from xmediaplayerx.services.playback_history import PlaybackHistory
from xmediaplayerx.settings import SettingsStore


def startup_media(arguments: list[str]) -> list[tuple[str, str]]:
    """Return validated file/URL arguments passed by Explorer or a terminal."""
    media: list[tuple[str, str]] = []
    for argument in arguments:
        value = str(argument).strip()
        if not value or value.startswith("-"):
            continue
        lowered = value.lower()
        if lowered.startswith(("http://", "https://")):
            try:
                media.append(("url", validate_media_url(value)))
            except ValueError:
                pass
            continue
        if lowered.startswith("file:"):
            value = QUrl(value).toLocalFile()
        path = Path(value).expanduser()
        if path.is_file():
            media.append(("file", str(path.resolve())))
    return media


def open_startup_media(
    media: list[tuple[str, str]], queue: QueueModel, playback: PlaybackController
) -> None:
    first_row = -1
    files = [source for kind, source in media if kind == "file"]
    if files:
        first_row = queue.addFiles(files)
    for kind, source in media:
        if kind != "url":
            continue
        row = queue.addUrl(source)
        if first_row < 0:
            first_row = row
    if first_row >= 0:
        playback.playIndex(first_row)


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#080B12"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#F4F6FB"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#101522"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#F4F6FB"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#171D2A"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#F4F6FB"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#7C5CFF"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    return palette


def _enable_dark_title_bar(window) -> None:
    if os.name != "nt":
        return
    try:
        hwnd = int(window.winId())
        enabled = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
    except Exception:
        logging.getLogger("xmediaplayerx").debug("Dark title bar could not be enabled", exc_info=True)


def _show_fatal_error(message: str) -> None:
    message = message.strip() or "xMediaPlayerx could not start"
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(
                None, message, "xMediaPlayerx could not start", 0x10
            )
            return
        except Exception:
            pass
    print(f"xMediaPlayerx: {message}", file=sys.stderr)


def _install_exception_logging(logger: logging.Logger) -> None:
    def unhandled(error_type, error, traceback) -> None:
        logger.critical(
            "Unhandled application exception",
            exc_info=(error_type, error, traceback),
        )

    def thread_unhandled(arguments: threading.ExceptHookArgs) -> None:
        logger.critical(
            "Unhandled exception in thread %s",
            arguments.thread.name if arguments.thread else "unknown",
            exc_info=(
                arguments.exc_type,
                arguments.exc_value,
                arguments.exc_traceback,
            ),
        )

    sys.excepthook = unhandled
    threading.excepthook = thread_unhandled


def _shutdown_components(
    settings: SettingsStore,
    window,
    playback: PlaybackController,
    airplay: AirPlayController,
    logger: logging.Logger,
    media_tools: MediaToolsController | None = None,
) -> None:
    window_settings = {
        "window.width": int(window.property("width")),
        "window.height": int(window.property("height")),
        "window.maximized": bool(window.property("visibility") == 4),
    }
    for key, value in window_settings.items():
        try:
            settings.set(key, value)
        except Exception:
            logger.warning("Could not save %s during shutdown", key, exc_info=True)
    try:
        playback.close()
    except Exception:
        logger.warning("Local playback cleanup failed", exc_info=True)
    try:
        airplay.close()
    except Exception:
        logger.warning("AirPlay cleanup failed", exc_info=True)
    if media_tools is not None:
        try:
            media_tools.close()
        except Exception:
            logger.warning("Media-tools cleanup failed", exc_info=True)


def _close_startup_components(
    playback: PlaybackController | None,
    runtime: AsyncRuntime | UnavailableAsyncRuntime | None,
    airplay: AirPlayController | None,
    logger: logging.Logger,
    media_tools: MediaToolsController | None = None,
) -> None:
    if airplay is not None:
        try:
            airplay.close()
        except Exception:
            logger.warning("AirPlay startup cleanup failed", exc_info=True)
    elif runtime is not None:
        try:
            runtime.close()
        except Exception:
            logger.warning("AirPlay runtime startup cleanup failed", exc_info=True)
    if playback is not None:
        try:
            playback.close()
        except Exception:
            logger.warning("Playback startup cleanup failed", exc_info=True)
    if media_tools is not None:
        try:
            media_tools.close()
        except Exception:
            logger.warning("Media-tools startup cleanup failed", exc_info=True)


def main() -> int:
    requested_media = startup_media(sys.argv[1:])
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    QGuiApplication.setApplicationName("xMediaPlayerx")
    QGuiApplication.setApplicationVersion(__version__)
    QGuiApplication.setOrganizationName("xMediaPlayerx")
    QQuickStyle.setStyle("Material")
    app = QGuiApplication(sys.argv)
    app.setPalette(_dark_palette())
    app.setWindowIcon(
        QIcon(str(resource_path("qml", "assets", "xmediaplayerx-icon.png")))
    )

    logger = logging.getLogger("xmediaplayerx")
    playback: PlaybackController | None = None
    runtime: AsyncRuntime | UnavailableAsyncRuntime | None = None
    airplay: AirPlayController | None = None
    media_tools: MediaToolsController | None = None
    try:
        paths = AppPaths.default()
        paths.ensure()
        try:
            logger = configure_logging(paths.log_dir)
        except OSError:
            logging.basicConfig(level=logging.INFO)
            logger.exception("File logging could not be initialized")
        _install_exception_logging(logger)
        logger.info("Starting xMediaPlayerx")
        settings = SettingsStore(paths.settings_file)
        queue = QueueModel()
        os.environ.setdefault("XMEDIAPLAYERX_FFMPEG_DIR", str(paths.tools_dir))
        locator = FFmpegLocator()
        media_tools = MediaToolsController(locator, paths.tools_dir)
        cache = CastCache(
            paths.cast_cache_dir,
            int(settings.get("cache_limit_gb", 20)) * 1024**3,
        )
        cache.clear_partials()
        preparer = MediaPreparer(locator, MediaProbe(locator), cache)
        playback = PlaybackController(
            queue,
            settings,
            preparer,
            PlaybackHistory(paths.playback_history_file),
        )
        try:
            runtime = AsyncRuntime(paths.airplay_storage_file)
        except Exception as error:
            message = "AirPlay is unavailable: " + error_message(
                error, "its background worker could not start"
            )
            logger.exception(message)
            runtime = UnavailableAsyncRuntime(message)
        airplay = AirPlayController(queue, playback, settings, runtime, preparer)
        app_settings = AppSettingsController(settings, cache, paths.log_dir)
        windows_integration = WindowsIntegrationController()
    except Exception as error:
        logger.exception("Application initialization failed")
        _close_startup_components(
            playback, runtime, airplay, logger, media_tools
        )
        _show_fatal_error(error_message(error, "xMediaPlayerx could not initialize"))
        return 1

    engine = QQmlApplicationEngine()

    def log_qml_warnings(warnings) -> None:
        for warning in warnings:
            logger.warning("QML: %s", warning.toString())

    engine.warnings.connect(log_qml_warnings)
    context = engine.rootContext()
    context.setContextProperty("queueModel", queue)
    context.setContextProperty("playback", playback)
    context.setContextProperty("airplay", airplay)
    context.setContextProperty("appSettings", app_settings)
    context.setContextProperty("mediaTools", media_tools)
    context.setContextProperty("windowsIntegration", windows_integration)
    qml_path = resource_path("qml", "Main.qml")
    try:
        engine.load(QUrl.fromLocalFile(str(qml_path)))
    except Exception as error:
        logger.exception("QML interface failed to load")
        _close_startup_components(
            playback, runtime, airplay, logger, media_tools
        )
        _show_fatal_error(error_message(error, "The interface could not be loaded"))
        return 1
    if not engine.rootObjects():
        logger.error("QML interface created no root window: %s", qml_path)
        _close_startup_components(
            playback, runtime, airplay, logger, media_tools
        )
        _show_fatal_error("The xMediaPlayerx interface could not be loaded")
        return 1

    window = engine.rootObjects()[0]
    window.setProperty("width", int(settings.get("window.width", 1280)))
    window.setProperty("height", int(settings.get("window.height", 780)))
    if settings.get("window.maximized", False):
        window.showMaximized()
    QTimer.singleShot(0, lambda: _enable_dark_title_bar(window))
    # Register only as an available per-user handler. Windows retains complete
    # control over the user's current defaults and asks for consent separately.
    QTimer.singleShot(0, windows_integration.ensureOpenWith)
    QTimer.singleShot(500, media_tools.requestInstallPrompt)
    if requested_media:
        logger.info("Opening %d command-line media item(s)", len(requested_media))
        QTimer.singleShot(
            0, lambda: open_startup_media(requested_media, queue, playback)
        )
    if os.environ.get("XMEDIAPLAYERX_SMOKE_TEST") == "1":
        QTimer.singleShot(1500, app.quit)
    else:
        QTimer.singleShot(700, airplay.scan)

    shutdown_started = False

    def shutdown() -> None:
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        logger.info("Shutting down xMediaPlayerx")
        _shutdown_components(
            settings, window, playback, airplay, logger, media_tools
        )

    app.aboutToQuit.connect(shutdown)
    engine.quit.connect(app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
