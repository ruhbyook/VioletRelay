from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, QUrl, Signal, Slot


@dataclass(slots=True)
class QueueItem:
    source: str
    title: str
    kind: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    duration_ms: int = 0
    audio_stream: int = -1
    subtitle: str = ""
    status: str = "ready"
    error: str = ""


class QueueModel(QAbstractListModel):
    IdRole = Qt.ItemDataRole.UserRole + 1
    SourceRole = IdRole + 1
    TitleRole = IdRole + 2
    KindRole = IdRole + 3
    DurationRole = IdRole + 4
    AudioStreamRole = IdRole + 5
    SubtitleRole = IdRole + 6
    StatusRole = IdRole + 7
    ErrorRole = IdRole + 8
    CurrentRole = IdRole + 9

    currentIndexChanged = Signal()
    countChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._items: list[QueueItem] = []
        self._current_index = -1

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.IdRole: b"itemId",
            self.SourceRole: b"source",
            self.TitleRole: b"title",
            self.KindRole: b"kind",
            self.DurationRole: b"durationMs",
            self.AudioStreamRole: b"audioStream",
            self.SubtitleRole: b"subtitle",
            self.StatusRole: b"status",
            self.ErrorRole: b"error",
            self.CurrentRole: b"isCurrent",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        values = {
            self.IdRole: item.id,
            self.SourceRole: item.source,
            self.TitleRole: item.title,
            self.KindRole: item.kind,
            self.DurationRole: item.duration_ms,
            self.AudioStreamRole: item.audio_stream,
            self.SubtitleRole: item.subtitle,
            self.StatusRole: item.status,
            self.ErrorRole: item.error,
            self.CurrentRole: index.row() == self._current_index,
        }
        return values.get(role, item.title if role == Qt.ItemDataRole.DisplayRole else None)

    @property
    def current_index(self) -> int:
        return self._current_index

    def current_item(self) -> QueueItem | None:
        return self.item_at(self._current_index)

    def item_at(self, index: int) -> QueueItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def index_of_id(self, item_id: str) -> int:
        return next(
            (
                index
                for index, item in enumerate(self._items)
                if item.id == item_id
            ),
            -1,
        )

    @Slot("QVariantList", result=int)
    def addFiles(self, sources: list[str]) -> int:
        first = len(self._items)
        new_items: list[QueueItem] = []
        for source in sources:
            if isinstance(source, QUrl):
                source = source.toLocalFile() if source.isLocalFile() else source.toString()
            else:
                source = str(source)
                if source.startswith("file:"):
                    source = QUrl(source).toLocalFile()
            path = Path(source)
            new_items.append(QueueItem(str(path), path.stem or path.name, "file"))
        if not new_items:
            return -1
        self.beginInsertRows(QModelIndex(), first, first + len(new_items) - 1)
        self._items.extend(new_items)
        self.endInsertRows()
        self.countChanged.emit()
        if self._current_index < 0:
            self.setCurrentIndex(0)
        return first

    @Slot(str, result=int)
    def addUrl(self, source: str) -> int:
        parsed = urlparse(source)
        title = Path(parsed.path).stem or parsed.hostname or "Network video"
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(QueueItem(source, title, "url"))
        self.endInsertRows()
        self.countChanged.emit()
        if self._current_index < 0:
            self.setCurrentIndex(0)
        return row

    @Slot(int)
    def setCurrentIndex(self, index: int) -> None:
        if index == self._current_index or not -1 <= index < len(self._items):
            return
        old = self._current_index
        self._current_index = index
        for row in (old, index):
            if 0 <= row < len(self._items):
                model_index = self.index(row)
                self.dataChanged.emit(model_index, model_index, [self.CurrentRole])
        self.currentIndexChanged.emit()

    @Slot(int)
    def remove(self, index: int) -> None:
        if not 0 <= index < len(self._items):
            return
        self.beginRemoveRows(QModelIndex(), index, index)
        self._items.pop(index)
        self.endRemoveRows()
        if not self._items:
            self._current_index = -1
        elif index < self._current_index:
            self._current_index -= 1
        elif index == self._current_index:
            self._current_index = min(index, len(self._items) - 1)
        self.currentIndexChanged.emit()
        self.countChanged.emit()

    @Slot(int, int)
    def move(self, source: int, destination: int) -> None:
        if source == destination or not (0 <= source < len(self._items) and 0 <= destination < len(self._items)):
            return
        current_id = self.current_item().id if self.current_item() else ""
        qt_destination = destination + 1 if destination > source else destination
        self.beginMoveRows(QModelIndex(), source, source, QModelIndex(), qt_destination)
        item = self._items.pop(source)
        self._items.insert(destination, item)
        self.endMoveRows()
        self._current_index = next(
            (index for index, queued in enumerate(self._items) if queued.id == current_id), -1
        )
        self.currentIndexChanged.emit()

    @Slot()
    def clear(self) -> None:
        if not self._items:
            return
        self.beginResetModel()
        self._items.clear()
        self._current_index = -1
        self.endResetModel()
        self.currentIndexChanged.emit()
        self.countChanged.emit()

    def update_item(self, index: int, **changes) -> None:
        item = self.item_at(index)
        if not item:
            return
        for key, value in changes.items():
            if hasattr(item, key):
                setattr(item, key, value)
        model_index = self.index(index)
        self.dataChanged.emit(model_index, model_index)

    def next_index(self) -> int:
        return self._current_index + 1 if self._current_index + 1 < len(self._items) else -1

    def previous_index(self) -> int:
        return self._current_index - 1 if self._current_index > 0 else -1
