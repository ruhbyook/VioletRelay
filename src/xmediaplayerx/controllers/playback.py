from __future__ import annotations

import concurrent.futures
import logging
from pathlib import Path
import threading
import time

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from xmediaplayerx.models import QueueModel
from xmediaplayerx.errors import error_message
from xmediaplayerx.services.converter import (
    ConversionCancelled,
    MediaPreparer,
    PreparedMedia,
)
from xmediaplayerx.services.media import (
    MediaInfo,
    MediaStream,
    RemoteMediaIdentity,
    default_audio_stream_index,
    inspect_remote_media,
    is_hls_url,
    subtitle_is_bitmap,
    validate_media_url,
)
from xmediaplayerx.services.playback_history import (
    MIN_RESUME_MS,
    MediaIdentity,
    PlaybackHistory,
)
from xmediaplayerx.services.subtitles import SubtitleTrack
from xmediaplayerx.settings import SettingsStore


class PlaybackController(QObject):
    positionChanged = Signal()
    durationChanged = Signal()
    playingChanged = Signal()
    sourceChanged = Signal()
    titleChanged = Signal()
    volumeChanged = Signal()
    mutedChanged = Signal()
    rateChanged = Signal()
    subtitleTextChanged = Signal()
    tracksChanged = Signal()
    fallbackChanged = Signal()
    urlOpeningChanged = Signal()
    fallbackSuggested = Signal(str)
    resumeSuggested = Signal(str, str)
    errorOccurred = Signal(str)
    naturalEnd = Signal()

    _probeFinished = Signal(str, object)
    _fallbackProgress = Signal(float, str)
    _fallbackFinished = Signal(str, object)
    _fallbackFailed = Signal(str)
    _urlInspectionFinished = Signal(int, str, object)

    def __init__(
        self,
        queue: QueueModel,
        settings: SettingsStore,
        preparer: MediaPreparer | None = None,
        history: PlaybackHistory | None = None,
    ):
        super().__init__()
        self.log = logging.getLogger("xmediaplayerx.playback")
        self.queue = queue
        self.settings = settings
        self.preparer = preparer
        self.history = history
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(float(settings.get("volume", 0.8)))
        self.audio.setMuted(bool(settings.get("muted", False)))
        self.player.setPlaybackRate(float(settings.get("playback_rate", 1.0)))
        self._subtitle_track: SubtitleTrack | None = None
        self._subtitle_text = ""
        self._manual_stop = False
        self._media_info: dict[str, MediaInfo] = {}
        self._local_overrides: dict[str, str] = {}
        self._using_fallback = False
        self._pending_seek_ms = -1
        self._source_transition = False
        self._resume_identity: MediaIdentity | None = None
        self._resume_offer_identity: MediaIdentity | None = None
        self._resume_offer_position_ms = -1
        self._last_history_save_at = 0.0
        self._history_error_reported = False
        self._fallback_preparing = False
        self._fallback_progress_value = 0.0
        self._fallback_status = ""
        self._fallback_resume_ms = 0
        self._fallback_was_playing = False
        self._subtitle_offer_key: tuple[str, str] | None = None
        self._url_opening = False
        self._url_generation = 0
        self._fallback_cancel = threading.Event()
        self._closed = False
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="LocalMedia"
        )
        self._history_timer = QTimer(self)
        self._history_timer.setInterval(15_000)
        self._history_timer.timeout.connect(self._periodic_history_checkpoint)
        if self.history is not None:
            self._history_timer.start()

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.tracksChanged.connect(self._on_qt_tracks_changed)
        self.player.activeTracksChanged.connect(self.tracksChanged)
        self.audio.volumeChanged.connect(self.volumeChanged)
        self.audio.mutedChanged.connect(self.mutedChanged)
        self.player.playbackRateChanged.connect(self.rateChanged)
        self._probeFinished.connect(self._on_probe_finished)
        self._fallbackProgress.connect(self._on_fallback_progress)
        self._fallbackFinished.connect(self._on_fallback_finished)
        self._fallbackFailed.connect(self._on_fallback_failed)
        self._urlInspectionFinished.connect(self._on_url_inspection_finished)

    @Property(int, notify=positionChanged)
    def position(self) -> int:
        return self.player.position()

    @Property(int, notify=durationChanged)
    def duration(self) -> int:
        return self.player.duration()

    @Property(bool, notify=playingChanged)
    def playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @Property(str, notify=sourceChanged)
    def source(self) -> str:
        item = self.queue.current_item()
        return item.source if item else ""

    @Property(str, notify=titleChanged)
    def title(self) -> str:
        item = self.queue.current_item()
        return item.title if item else "Nothing playing"

    @Property(float, notify=volumeChanged)
    def volume(self) -> float:
        return self.audio.volume()

    @Property(bool, notify=mutedChanged)
    def muted(self) -> bool:
        return self.audio.isMuted()

    @Property(float, notify=rateChanged)
    def playbackRate(self) -> float:
        return self.player.playbackRate()

    @Property(str, notify=subtitleTextChanged)
    def subtitleText(self) -> str:
        return self._subtitle_text

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self) -> list[dict[str, object]]:
        info = self._current_media_info()
        if info is not None:
            return [
                {"index": index, "label": self._stream_label(stream, "Audio", index)}
                for index, stream in enumerate(info.audio_streams)
            ]
        return [
            {"index": index, "label": f"Audio {index + 1}"}
            for index, _metadata in enumerate(self.player.audioTracks())
        ]

    @Property(int, notify=tracksChanged)
    def audioTrackModelIndex(self) -> int:
        item = self.queue.current_item()
        selected = item.audio_stream if item else -1
        return next(
            (
                index
                for index, track in enumerate(self.audioTracks)
                if track["index"] == selected
            ),
            0 if self.audioTracks else -1,
        )

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self) -> list[dict[str, str]]:
        tracks: list[dict[str, str]] = [{"value": "", "label": "Off"}]
        info = self._current_media_info()
        if info is not None:
            tracks.extend(
                {
                    "value": f"embedded:{index}",
                    "label": self._stream_label(stream, "Subtitles", index),
                }
                for index, stream in enumerate(info.subtitle_streams)
            )
        else:
            tracks.extend(
                {
                    "value": f"embedded:{index}",
                    "label": f"Subtitles {index + 1}",
                }
                for index, _metadata in enumerate(self.player.subtitleTracks())
            )
        item = self.queue.current_item()
        if item and item.subtitle and not item.subtitle.startswith("embedded:"):
            tracks.append(
                {
                    "value": item.subtitle,
                    "label": f"External · {Path(item.subtitle).name}",
                }
            )
        return tracks

    @Property(int, notify=tracksChanged)
    def subtitleTrackModelIndex(self) -> int:
        item = self.queue.current_item()
        selected = item.subtitle if item else ""
        return next(
            (
                index
                for index, track in enumerate(self.subtitleTracks)
                if track["value"] == selected
            ),
            0,
        )

    @Property(bool, notify=fallbackChanged)
    def fallbackPreparing(self) -> bool:
        return self._fallback_preparing

    @Property(float, notify=fallbackChanged)
    def fallbackProgress(self) -> float:
        return self._fallback_progress_value

    @Property(str, notify=fallbackChanged)
    def fallbackStatus(self) -> str:
        return self._fallback_status

    @Property(bool, notify=urlOpeningChanged)
    def urlOpening(self) -> bool:
        return self._url_opening

    def _current_media_info(self) -> MediaInfo | None:
        item = self.queue.current_item()
        return self._media_info.get(item.id) if item else None

    @staticmethod
    def _stream_label(stream: MediaStream, kind: str, index: int) -> str:
        tags = {key.casefold(): value for key, value in stream.tags.items()}
        title = tags.get("title") or tags.get("handler_name") or ""
        language = tags.get("language", "").upper()
        codec = stream.codec_name.replace("hdmv_pgs_subtitle", "PGS").upper()
        parts = [part for part in (language, title, codec) if part]
        if stream.disposition.get("default", 0):
            parts.append("Default")
        if stream.disposition.get("forced", 0):
            parts.append("Forced")
        return " · ".join(parts) or f"{kind} {index + 1}"

    @Slot(QObject)
    def attachVideoOutput(self, output: QObject) -> None:
        self.player.setVideoOutput(output)

    @Slot("QVariantList")
    def openFiles(self, sources: list[str]) -> None:
        self._cancel_url_opening()
        index = self.queue.addFiles(sources)
        if index >= 0:
            self.playIndex(index)

    @Slot(str)
    def openUrl(self, source: str) -> None:
        try:
            source = validate_media_url(source)
        except ValueError as error:
            self.errorOccurred.emit(str(error))
            return
        if is_hls_url(source):
            self._cancel_url_opening()
            self.playIndex(self.queue.addUrl(source))
            return
        self._url_generation += 1
        generation = self._url_generation
        self._url_opening = True
        self.urlOpeningChanged.emit()
        try:
            future = self._executor.submit(inspect_remote_media, source)
        except RuntimeError as error:
            self._url_opening = False
            self.urlOpeningChanged.emit()
            self.errorOccurred.emit(
                error_message(error, "The media URL could not be checked")
            )
            return

        def completed(done) -> None:
            if self._closed:
                return
            try:
                result: object = done.result()
            except Exception as error:
                result = error
            self._urlInspectionFinished.emit(generation, source, result)

        future.add_done_callback(completed)

    def _cancel_url_opening(self) -> None:
        self._url_generation += 1
        if self._url_opening:
            self._url_opening = False
            self.urlOpeningChanged.emit()

    def _on_url_inspection_finished(
        self, generation: int, source: str, result: object
    ) -> None:
        if generation != self._url_generation:
            return
        self._url_opening = False
        self.urlOpeningChanged.emit()
        if isinstance(result, Exception):
            self.errorOccurred.emit(
                error_message(result, "The media URL could not be verified")
            )
            return
        if not isinstance(result, RemoteMediaIdentity):
            self.errorOccurred.emit(
                "The media URL returned an unexpected response"
            )
            return
        if result.is_webpage:
            self.errorOccurred.emit(
                "This URL is a web page, not a direct media file. Paste the "
                "direct MP4, MOV, or HLS address instead."
            )
            return
        self.playIndex(self.queue.addUrl(source))

    @Slot(int)
    def playIndex(self, index: int) -> None:
        self._cancel_url_opening()
        item = self.queue.item_at(index)
        if not item:
            return
        if item.kind == "file" and not Path(item.source).is_file():
            self.queue.update_item(index, status="error", error="File not found")
            self.errorOccurred.emit("This file no longer exists")
            return
        self._checkpoint_resume(force=True)
        self._clear_resume_offer()
        self._resume_identity = None
        resume_position = -1
        if item.kind == "file" and self.history is not None:
            try:
                self._resume_identity = self.history.identify(item.source)
                record = self.history.get(self._resume_identity)
                if record is not None:
                    resume_position = record.position_ms
            except OSError as error:
                self.log.warning(
                    "Could not identify media for resume history: %s",
                    error,
                )
        self._manual_stop = False
        self.queue.setCurrentIndex(index)
        override = self._local_overrides.get(item.id, "")
        if override and not Path(override).is_file():
            self._local_overrides.pop(item.id, None)
            override = ""
        self._using_fallback = bool(override)
        if self._using_fallback:
            self._subtitle_track = None
            self._set_subtitle_text("")
        else:
            self._load_subtitle(item.subtitle)
        playback_source = override or item.source
        url = (
            QUrl.fromLocalFile(playback_source)
            if item.kind == "file"
            else QUrl(playback_source)
        )
        self._source_transition = True
        try:
            self.player.setSource(url)
        finally:
            self._source_transition = False
        if resume_position >= MIN_RESUME_MS and self._resume_identity is not None:
            self._resume_offer_identity = self._resume_identity
            self._resume_offer_position_ms = resume_position
            self.resumeSuggested.emit(
                item.title,
                self._format_position(resume_position),
            )
        else:
            self.player.play()
        self._probe_item(item.id, item.source, item.kind)
        self.sourceChanged.emit()
        self.titleChanged.emit()
        self.tracksChanged.emit()

    @Slot()
    def playPause(self) -> None:
        if not self.source:
            return
        if self._resume_offer_position_ms >= 0:
            self.resumeFromSavedPosition()
            return
        if self.playing:
            self.player.pause()
        else:
            self.player.play()

    @Slot()
    def pause(self) -> None:
        self.player.pause()

    @Slot()
    def stop(self) -> None:
        self._manual_stop = True
        self._checkpoint_resume(force=True)
        self.player.stop()

    @Slot(int)
    def seek(self, position_ms: int) -> None:
        position_ms = max(0, min(position_ms, self.duration))
        if position_ms < MIN_RESUME_MS:
            self._remove_current_resume()
        self.player.setPosition(position_ms)

    @Slot()
    def resumeFromSavedPosition(self) -> None:
        if self._resume_offer_position_ms < 0:
            return
        position = self._resume_offer_position_ms
        self._clear_resume_offer()
        if self.player.mediaStatus() in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            self.player.setPosition(position)
            self.player.play()
        else:
            self._pending_seek_ms = position
            self.player.play()

    @Slot()
    def startFromBeginning(self) -> None:
        identity = self._resume_offer_identity or self._resume_identity
        self._clear_resume_offer()
        self._pending_seek_ms = -1
        if identity is not None and self.history is not None:
            try:
                self.history.remove(identity)
            except OSError as error:
                self._report_history_error(error)
        self.player.setPosition(0)
        self.player.play()

    @Slot(float)
    def setVolume(self, volume: float) -> None:
        volume = max(0.0, min(1.0, volume))
        self.audio.setVolume(volume)
        self._save_setting("volume", volume)

    @Slot()
    def toggleMute(self) -> None:
        muted = not self.audio.isMuted()
        self.audio.setMuted(muted)
        self._save_setting("muted", muted)

    @Slot(float)
    def setPlaybackRate(self, rate: float) -> None:
        rate = max(0.25, min(3.0, rate))
        self.player.setPlaybackRate(rate)
        self._save_setting("playback_rate", rate)

    def _save_setting(self, key: str, value: object) -> None:
        try:
            self.settings.set(key, value)
        except Exception as error:
            self.errorOccurred.emit(
                "The setting changed for this session but could not be saved: "
                + error_message(error, "unknown storage error")
            )

    @Slot(int)
    def selectAudioTrack(self, index: int) -> None:
        item = self.queue.current_item()
        if not item or index < 0:
            return
        item.audio_stream = index
        self.queue.update_item(self.queue.current_index, audio_stream=index)
        self._invalidate_local_override(item.id)
        if index < len(self.player.audioTracks()):
            self.player.setActiveAudioTrack(index)
        self.tracksChanged.emit()

    @Slot(str)
    def selectSubtitleTrack(self, value: str) -> None:
        item = self.queue.current_item()
        if not item:
            return
        value = str(value)
        if self._subtitle_offer_key != (item.id, value):
            self._subtitle_offer_key = None
        item.subtitle = value
        self.queue.update_item(self.queue.current_index, subtitle=value)
        self._invalidate_local_override(item.id)
        self._load_subtitle(value)
        if value.startswith("embedded:"):
            try:
                index = int(value.split(":", 1)[1])
            except ValueError:
                index = -1
            self.player.setActiveSubtitleTrack(index)
            info = self._current_media_info()
            if info is not None and subtitle_is_bitmap(info, value):
                self._offer_subtitle_fallback(
                    "This image-based subtitle track needs a compatibility copy "
                    "to display locally. Convert it now?"
                )
        else:
            self.player.setActiveSubtitleTrack(-1)
        self.tracksChanged.emit()

    @Slot()
    def next(self) -> None:
        if (index := self.queue.next_index()) >= 0:
            self.playIndex(index)

    @Slot()
    def previous(self) -> None:
        if self.position > 5000:
            self.seek(0)
        elif (index := self.queue.previous_index()) >= 0:
            self.playIndex(index)

    @Slot("QVariant")
    def selectExternalSubtitle(self, value) -> None:
        if isinstance(value, QUrl):
            value = value.toLocalFile() if value.isLocalFile() else value.toString()
        else:
            value = str(value)
            if value.startswith("file:"):
                value = QUrl(value).toLocalFile()
        item = self.queue.current_item()
        if not item:
            return
        if value and not Path(value).is_file():
            self.errorOccurred.emit("The selected subtitle file is no longer available")
            return
        if self._subtitle_offer_key != (item.id, value):
            self._subtitle_offer_key = None
        item.subtitle = value
        self.queue.update_item(self.queue.current_index, subtitle=value)
        self._invalidate_local_override(item.id)
        self.player.setActiveSubtitleTrack(-1)
        self._load_subtitle(value)
        if value and Path(value).suffix.lower() != ".srt":
            self._offer_subtitle_fallback(
                f"{Path(value).suffix.upper().lstrip('.')} subtitles need a "
                "compatibility copy to display locally. Convert it now?"
            )
        elif not value:
            self._subtitle_offer_key = None
        self.tracksChanged.emit()

    @Slot()
    def clearSubtitle(self) -> None:
        self.selectExternalSubtitle("")

    def _load_subtitle(self, path: str) -> None:
        self._subtitle_track = None
        if (
            path
            and not path.startswith("embedded:")
            and Path(path).suffix.lower() == ".srt"
        ):
            try:
                self._subtitle_track = SubtitleTrack.from_srt(Path(path))
            except OSError as error:
                self.errorOccurred.emit(f"Unable to load subtitles: {error}")
        self._set_subtitle_text("")

    def _invalidate_local_override(self, item_id: str) -> None:
        if item_id not in self._local_overrides:
            return
        self._local_overrides.pop(item_id, None)
        item = self.queue.current_item()
        if item and item.id == item_id:
            position = self.position
            self._using_fallback = False
            self._pending_seek_ms = position
            self.player.setSource(QUrl.fromLocalFile(item.source))
            self.player.play()

    def _offer_subtitle_fallback(self, message: str) -> None:
        item = self.queue.current_item()
        if not item:
            return
        key = (item.id, item.subtitle)
        if key == self._subtitle_offer_key:
            return
        self._subtitle_offer_key = key
        self.fallbackSuggested.emit(message)

    def _refresh_subtitle_text(self) -> None:
        if self._subtitle_track is not None:
            self._set_subtitle_text(self._subtitle_track.text_at(self.position))
        else:
            # Qt's VideoOutput renders selected embedded subtitle tracks itself.
            # Mirroring QVideoSink.subtitleText in QML draws the same caption twice.
            self._set_subtitle_text("")

    def _set_subtitle_text(self, text: str) -> None:
        if text != self._subtitle_text:
            self._subtitle_text = text
            self.subtitleTextChanged.emit()

    def _probe_item(self, item_id: str, source: str, kind: str) -> None:
        if (
            self._closed
            or self.preparer is None
            or kind != "file"
            or item_id in self._media_info
        ):
            return
        try:
            future = self._executor.submit(self.preparer.probe.probe, source)
        except RuntimeError:
            return

        def completed(done) -> None:
            if self._closed:
                return
            try:
                self._probeFinished.emit(item_id, done.result())
            except Exception:
                # QMediaPlayer remains authoritative for local playback errors;
                # probing is only used to enrich track selection.
                return

        future.add_done_callback(completed)

    def _on_probe_finished(self, item_id: str, info: MediaInfo) -> None:
        self._media_info[item_id] = info
        row = self.queue.index_of_id(item_id)
        item = self.queue.item_at(row)
        if item is not None and item.audio_stream < 0:
            item.audio_stream = default_audio_stream_index(info)
            if row >= 0:
                self.queue.update_item(row, audio_stream=item.audio_stream)
        current = self.queue.current_item()
        if current and current.id == item_id:
            self._apply_selected_tracks()
            self.tracksChanged.emit()
            if current.subtitle and subtitle_is_bitmap(info, current.subtitle):
                self._offer_subtitle_fallback(
                    "This image-based subtitle track needs a compatibility copy "
                    "to display locally. Convert it now?"
                )

    def _apply_selected_tracks(self) -> None:
        if self._using_fallback:
            return
        item = self.queue.current_item()
        if not item:
            return
        if 0 <= item.audio_stream < len(self.player.audioTracks()):
            self.player.setActiveAudioTrack(item.audio_stream)
        if item.subtitle.startswith("embedded:"):
            try:
                index = int(item.subtitle.split(":", 1)[1])
            except ValueError:
                index = -1
            if index < len(self.player.subtitleTracks()):
                self.player.setActiveSubtitleTrack(index)
        else:
            self.player.setActiveSubtitleTrack(-1)

    def _on_qt_tracks_changed(self) -> None:
        item = self.queue.current_item()
        if item and item.audio_stream < 0 and self.player.audioTracks():
            item.audio_stream = max(0, self.player.activeAudioTrack())
            self.queue.update_item(
                self.queue.current_index, audio_stream=item.audio_stream
            )
        self._apply_selected_tracks()
        self.tracksChanged.emit()

    def _on_player_error(self, _error, text: str) -> None:
        item = self.queue.current_item()
        if (
            item
            and item.kind == "file"
            and self.preparer is not None
            and not self._using_fallback
            and not self._fallback_preparing
        ):
            self.fallbackSuggested.emit(
                (text or "Qt could not play this file")
                + ". Create a compatible local copy and continue?"
            )
            return
        self.errorOccurred.emit(text or "Unable to play this media")

    @Slot()
    def prepareLocalFallback(self) -> None:
        item = self.queue.current_item()
        if self.preparer is None or item is None or item.kind != "file":
            return
        if self._fallback_preparing:
            return
        self._fallback_was_playing = self.playing
        self.player.pause()
        self._fallback_preparing = True
        self._fallback_progress_value = 0.0
        self._fallback_status = "Inspecting media"
        self._fallback_resume_ms = self.position
        self._fallback_cancel.clear()
        self.fallbackChanged.emit()
        try:
            future = self._executor.submit(
                self.preparer.prepare_local_fallback,
                item.source,
                item.subtitle,
                item.audio_stream,
                lambda value, status: (
                    None
                    if self._closed
                    else self._fallbackProgress.emit(value, status)
                ),
                self._fallback_cancel,
            )
        except RuntimeError as error:
            self._fallback_preparing = False
            self.fallbackChanged.emit()
            self.errorOccurred.emit(
                error_message(error, "Local conversion could not be started")
            )
            return

        def completed(done) -> None:
            if self._closed:
                return
            try:
                self._fallbackFinished.emit(item.id, done.result())
            except ConversionCancelled:
                self._fallbackFailed.emit("Local compatibility conversion cancelled")
            except Exception as error:
                self._fallbackFailed.emit(
                    error_message(error, "Local compatibility conversion failed")
                )

        future.add_done_callback(completed)

    @Slot()
    def cancelLocalFallback(self) -> None:
        self._fallback_cancel.set()

    def _on_fallback_progress(self, value: float, status: str) -> None:
        self._fallback_progress_value = value
        self._fallback_status = status
        self.fallbackChanged.emit()

    def _on_fallback_finished(
        self, item_id: str, prepared: PreparedMedia
    ) -> None:
        self._fallback_preparing = False
        self._fallback_progress_value = 1.0
        self._fallback_status = "Local compatibility copy ready"
        self._local_overrides[item_id] = prepared.source
        current = self.queue.current_item()
        if current and current.id == item_id:
            self._using_fallback = True
            self._subtitle_track = None
            self._set_subtitle_text("")
            self._pending_seek_ms = self._fallback_resume_ms
            self.player.setSource(QUrl.fromLocalFile(prepared.source))
            self.player.play()
        self.fallbackChanged.emit()
        self.tracksChanged.emit()

    def _on_fallback_failed(self, message: str) -> None:
        self._fallback_preparing = False
        self._fallback_status = ""
        self.fallbackChanged.emit()
        if self._fallback_was_playing:
            self.player.play()
        if "cancel" not in message.casefold():
            self.errorOccurred.emit(message)

    def _on_position(self, _position: int) -> None:
        self.positionChanged.emit()
        self._refresh_subtitle_text()

    def _on_duration_changed(self, duration_ms: int) -> None:
        item = self.queue.current_item()
        if item is not None and self.queue.current_index >= 0:
            self.queue.update_item(
                self.queue.current_index,
                duration_ms=max(0, int(duration_ms)),
            )
        self.durationChanged.emit()

    def _on_playback_state(
        self, state: QMediaPlayer.PlaybackState
    ) -> None:
        self.playingChanged.emit()
        if (
            not self._source_transition
            and state != QMediaPlayer.PlaybackState.PlayingState
        ):
            self._checkpoint_resume(force=True)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if (
            self._pending_seek_ms >= 0
            and status
            in {
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.BufferedMedia,
            }
        ):
            position = self._pending_seek_ms
            self._pending_seek_ms = -1
            self.player.setPosition(position)
            self.player.play()
        if status == QMediaPlayer.MediaStatus.EndOfMedia and not self._manual_stop:
            self.clear_resume_position()
            self.naturalEnd.emit()
            self.next()

    @staticmethod
    def _format_position(position_ms: int) -> str:
        seconds = max(0, int(position_ms) // 1000)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def _clear_resume_offer(self) -> None:
        self._resume_offer_identity = None
        self._resume_offer_position_ms = -1

    def _periodic_history_checkpoint(self) -> None:
        if self.playing:
            self._checkpoint_resume()

    def _checkpoint_resume(
        self,
        *,
        force: bool = False,
        position_ms: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        if (
            self.history is None
            or self._resume_identity is None
            or self._resume_offer_position_ms >= 0
        ):
            return
        item = self.queue.current_item()
        if item is None or item.kind != "file":
            return
        now = time.monotonic()
        if not force and now - self._last_history_save_at < 15.0:
            return
        position = self.position if position_ms is None else int(position_ms)
        duration = self.duration if duration_ms is None else int(duration_ms)
        try:
            self.history.save(
                self._resume_identity,
                position,
                duration,
                item.title,
            )
            self._last_history_save_at = now
            self._history_error_reported = False
        except OSError as error:
            self._report_history_error(error)

    def checkpoint_remote_position(
        self,
        position_ms: int,
        duration_ms: int,
        *,
        force: bool = False,
    ) -> None:
        self._checkpoint_resume(
            force=force,
            position_ms=position_ms,
            duration_ms=duration_ms,
        )

    def _remove_current_resume(self) -> None:
        if self.history is None or self._resume_identity is None:
            return
        try:
            self.history.remove(self._resume_identity)
        except OSError as error:
            self._report_history_error(error)

    def clear_resume_position(self) -> None:
        self._remove_current_resume()
        self._clear_resume_offer()

    def _report_history_error(self, error: OSError) -> None:
        self.log.warning("Playback position could not be saved", exc_info=True)
        if self._history_error_reported:
            return
        self._history_error_reported = True
        self.errorOccurred.emit(
            "Playback continues, but its resume position could not be saved: "
            + error_message(error, "storage error")
        )

    def close(self) -> None:
        if self._closed:
            return
        self._checkpoint_resume(force=True)
        self._closed = True
        self._cancel_url_opening()
        self._history_timer.stop()
        self._fallback_cancel.set()
        self.player.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
