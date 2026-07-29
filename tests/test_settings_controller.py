from xmediaplayerx.controllers.settings import AppSettingsController
from xmediaplayerx.services.cache import CastCache
from xmediaplayerx.settings import SettingsStore


def test_cache_limit_is_persisted_and_enforced(qtbot, tmp_path):
    settings = SettingsStore(tmp_path / "settings.json")
    cache = CastCache(tmp_path / "cache", 20 * 1024**3)
    cached = cache.output_path("old")
    cached.write_bytes(b"x" * 32)
    controller = AppSettingsController(settings, cache)

    with qtbot.waitSignal(controller.changed):
        controller.setCacheLimitGb(1)

    assert settings.get("cache_limit_gb") == 1
    assert cache.limit_bytes == 1024**3
    assert controller.cacheUsageText == "32 bytes"


def test_clear_cast_cache_reports_result(qtbot, tmp_path):
    settings = SettingsStore(tmp_path / "settings.json")
    cache = CastCache(tmp_path / "cache", 20 * 1024**3)
    cache.output_path("one").write_bytes(b"one")
    cache.output_path("two").write_bytes(b"two")
    controller = AppSettingsController(settings, cache)

    with qtbot.waitSignal(controller.changed):
        controller.clearCastCache()

    assert controller.cacheUsageText == "0 bytes"
    assert "2 prepared cast copies" in controller.cacheStatus
