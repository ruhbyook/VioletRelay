import pytest

from violetrelay.paths import AppPaths, migrate_legacy_app_data


@pytest.mark.parametrize("legacy_name", ("ReelFerry", "xMediaPlayerx"))
def test_legacy_app_data_migration_preserves_user_state_and_cache(
    tmp_path,
    legacy_name,
):
    legacy = tmp_path / legacy_name
    current = tmp_path / "VioletRelay"
    (legacy / "Cache" / "casts").mkdir(parents=True)
    (legacy / "Logs").mkdir()
    (legacy / "settings.json").write_text('{"volume": 0.4}', encoding="utf-8")
    (legacy / "playback_history.json").write_text(
        '{"version": 1, "items": {}}',
        encoding="utf-8",
    )
    (legacy / "pyatv.json").write_text("encrypted", encoding="utf-8")
    (legacy / "Cache" / "casts" / "prepared.mp4").write_bytes(b"cast")

    migrate_legacy_app_data(
        legacy,
        legacy / "Cache",
        legacy / "Logs",
        current,
        current / "Cache",
        current / "Logs",
    )

    assert not legacy.exists()
    assert (current / "settings.json").read_text(encoding="utf-8") == (
        '{"volume": 0.4}'
    )
    assert (current / "playback_history.json").is_file()
    assert (current / "pyatv.json").read_text(encoding="utf-8") == "encrypted"
    assert (current / "Cache" / "casts" / "prepared.mp4").read_bytes() == (
        b"cast"
    )


@pytest.mark.parametrize("legacy_name", ("ReelFerry", "xMediaPlayerx"))
def test_legacy_migration_never_overwrites_newer_brand_data(
    tmp_path,
    legacy_name,
):
    legacy = tmp_path / legacy_name
    current = tmp_path / "VioletRelay"
    legacy.mkdir()
    current.mkdir()
    (legacy / "settings.json").write_text("legacy", encoding="utf-8")
    (legacy / "pyatv.json").write_text("pairing", encoding="utf-8")
    (current / "settings.json").write_text("current", encoding="utf-8")

    migrate_legacy_app_data(
        legacy,
        legacy / "Cache",
        legacy / "Logs",
        current,
        current / "Cache",
        current / "Logs",
    )

    assert (current / "settings.json").read_text(encoding="utf-8") == "current"
    assert (current / "pyatv.json").read_text(encoding="utf-8") == "pairing"
    assert (legacy / "settings.json").read_text(encoding="utf-8") == "legacy"


def test_explicit_data_directory_is_isolated_and_skips_migration(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "isolated"
    monkeypatch.setenv("VIOLETRELAY_DATA_DIR", str(target))

    paths = AppPaths.default()

    assert paths.config_dir == target.resolve()
    assert paths.cache_dir == target.resolve() / "Cache"
    assert paths.log_dir == target.resolve() / "Logs"
