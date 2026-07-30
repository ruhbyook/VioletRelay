from violetrelay.settings import SettingsStore


def test_settings_merge_defaults_and_persist(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert store.get("cache_limit_gb") == 20
    assert store.get("window.width") == 1280

    store.set("window.width", 1440)
    store.set("volume", 0.35)

    reloaded = SettingsStore(path)
    assert reloaded.get("window.width") == 1440
    assert reloaded.get("window.height") == 780
    assert reloaded.get("volume") == 0.35


def test_settings_ignore_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"unknown": true, "window": {"height": 900}}', encoding="utf-8")
    store = SettingsStore(path)
    assert store.get("unknown") is None
    assert store.get("window.height") == 900
