from xmediaplayerx.models import QueueModel
from PySide6.QtCore import QUrl


def test_queue_add_remove_and_navigation(qtbot, tmp_path):
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mkv"
    queue = QueueModel()
    qtbot.addWidget if False else None
    assert queue.addFiles([str(first), str(second)]) == 0
    assert queue.count == 2
    assert queue.current_index == 0
    assert queue.next_index() == 1
    queue.setCurrentIndex(1)
    assert queue.previous_index() == 0
    queue.remove(0)
    assert queue.count == 1
    assert queue.current_index == 0


def test_queue_url_title():
    queue = QueueModel()
    queue.addUrl("https://example.test/media/My%20Film.mp4")
    assert queue.current_item().kind == "url"
    assert "My%20Film" in queue.current_item().title


def test_queue_accepts_qml_file_urls(tmp_path):
    source = tmp_path / "a video.mp4"
    queue = QueueModel()
    queue.addFiles([QUrl.fromLocalFile(str(source))])
    assert queue.current_item().source == str(source)


def test_move_keeps_same_current_item(tmp_path):
    queue = QueueModel()
    queue.addFiles([str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4"), str(tmp_path / "c.mp4")])
    queue.setCurrentIndex(1)
    current_id = queue.current_item().id
    queue.move(0, 2)
    assert queue.current_item().id == current_id
