import os

from reelferry.services.cache import CastCache


def test_cache_key_changes_with_source_and_subtitle_mtime(tmp_path):
    source = tmp_path / "movie.mkv"
    subtitle = tmp_path / "movie.srt"
    source.write_bytes(b"movie")
    subtitle.write_text("caption", encoding="utf-8")
    first = CastCache.key_for(str(source), str(subtitle))
    subtitle.write_text("changed caption", encoding="utf-8")
    second = CastCache.key_for(str(source), str(subtitle))
    assert first != second


def test_cache_key_separates_audio_track_and_profile(tmp_path):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"movie")
    first = CastCache.key_for(str(source), audio_stream=0)
    second = CastCache.key_for(str(source), audio_stream=1)
    local = CastCache.key_for(
        str(source), audio_stream=0, profile="local-fallback-1080p-v1"
    )
    assert len({first, second, local}) == 3


def test_remote_cache_key_includes_http_revision_identity():
    first = CastCache.key_for(
        "https://example.test/movie",
        remote_identity={
            "content_length": 100,
            "etag": '"revision-1"',
            "last_modified": "",
        },
    )
    second = CastCache.key_for(
        "https://example.test/movie",
        remote_identity={
            "content_length": 100,
            "etag": '"revision-2"',
            "last_modified": "",
        },
    )
    assert first != second


def test_lru_eviction_respects_protected_file(tmp_path):
    cache = CastCache(tmp_path, limit_bytes=8)
    oldest = tmp_path / "old.mp4"
    protected = tmp_path / "protected.mp4"
    newest = tmp_path / "new.mp4"
    for path in (oldest, protected, newest):
        path.write_bytes(b"12345")
    os.utime(oldest, (1, 1))
    os.utime(protected, (2, 2))
    os.utime(newest, (3, 3))

    removed = cache.enforce_limit({protected})
    assert oldest in removed
    assert protected.exists()
    assert not newest.exists()


def test_startup_cleanup_removes_incomplete_hls_sessions(tmp_path):
    cache = CastCache(tmp_path, limit_bytes=100)
    stale = tmp_path / "hls-stale"
    stale.mkdir()
    (stale / "index.m3u8").write_text("#EXTM3U", encoding="utf-8")
    cache.clear_partials()
    assert not stale.exists()


def test_inaccessible_cache_entry_is_treated_as_a_miss(tmp_path, monkeypatch):
    cache = CastCache(tmp_path, limit_bytes=100)
    path = cache.output_path("entry")
    path.write_bytes(b"video")

    monkeypatch.setattr(
        "reelferry.services.cache.os.utime",
        lambda *_args: (_ for _ in ()).throw(PermissionError("locked")),
    )
    assert cache.get("entry") is None
