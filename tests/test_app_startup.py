from PySide6.QtCore import QUrl

from xmediaplayerx.app import open_startup_media, startup_media


class FakeQueue:
    def __init__(self):
        self.files = []
        self.urls = []

    def addFiles(self, files):
        self.files.extend(files)
        return 0

    def addUrl(self, url):
        self.urls.append(url)
        return len(self.files) + len(self.urls) - 1


class FakePlayback:
    def __init__(self):
        self.played = []

    def playIndex(self, index):
        self.played.append(index)


def test_startup_media_accepts_explorer_paths_file_urls_and_http(tmp_path):
    first = tmp_path / "A Film.mkv"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"video")
    second.write_bytes(b"video")
    result = startup_media(
        [
            str(first),
            QUrl.fromLocalFile(str(second)).toString(),
            "https://example.test/movie.mp4",
            "--ignored-option",
            str(tmp_path / "missing.mp4"),
        ]
    )
    assert result == [
        ("file", str(first.resolve())),
        ("file", str(second.resolve())),
        ("url", "https://example.test/movie.mp4"),
    ]


def test_open_startup_media_queues_everything_and_plays_first():
    queue = FakeQueue()
    playback = FakePlayback()
    open_startup_media(
        [("file", "one.mkv"), ("url", "https://example.test/two.mp4")],
        queue,
        playback,
    )
    assert queue.files == ["one.mkv"]
    assert queue.urls == ["https://example.test/two.mp4"]
    assert playback.played == [0]
