from __future__ import annotations

import concurrent.futures
import logging
import threading

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from violetrelay.controllers.playback import PlaybackController
from violetrelay.errors import error_message
from violetrelay.models import QueueModel
from violetrelay.services.airplay import (
    AirPlayDevice,
    AsyncRuntime,
    CastStatus,
    PairingPrompt,
)
from violetrelay.services.converter import ConversionCancelled, MediaPreparer, PreparedMedia
from violetrelay.settings import SettingsStore


class DeviceListModel(QAbstractListModel):
    IdentifierRole = Qt.ItemDataRole.UserRole + 1
    NameRole = IdentifierRole + 1
    AddressRole = IdentifierRole + 2
    ModelRole = IdentifierRole + 3
    PairedRole = IdentifierRole + 4
    PreferredRole = IdentifierRole + 5

    def __init__(self) -> None:
        super().__init__()
        self.devices: list[AirPlayDevice] = []
        self.preferred_identifier = ""

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.IdentifierRole: b"identifier",
            self.NameRole: b"name",
            self.AddressRole: b"address",
            self.ModelRole: b"deviceModel",
            self.PairedRole: b"paired",
            self.PreferredRole: b"preferred",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.devices)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.devices):
            return None
        device = self.devices[index.row()]
        return {
            self.IdentifierRole: device.identifier,
            self.NameRole: device.name,
            self.AddressRole: device.address,
            self.ModelRole: device.model,
            self.PairedRole: device.paired,
            self.PreferredRole: device.identifier == self.preferred_identifier,
        }.get(role, device.name if role == Qt.ItemDataRole.DisplayRole else None)

    def replace(
        self, devices: list[AirPlayDevice], preferred_identifier: str = ""
    ) -> None:
        self.beginResetModel()
        self.devices = devices
        self.preferred_identifier = preferred_identifier
        self.endResetModel()

    def at(self, row: int) -> AirPlayDevice | None:
        return self.devices[row] if 0 <= row < len(self.devices) else None


class AirPlayController(QObject):
    stateChanged = Signal()
    pairingChanged = Signal()
    progressChanged = Signal()
    castProgressChanged = Signal()
    errorOccurred = Signal(str)
    pairingSucceeded = Signal(str)
    recoveryNeeded = Signal(str)

    _scanCompleted = Signal(object)
    _operationFailed = Signal(str)
    _pairPromptReady = Signal(object)
    _pairFinished = Signal(bool)
    _preparationProgress = Signal(float, str)
    _preparationFinished = Signal(object)
    _castStarted = Signal()
    _statusReady = Signal(object)
    _stopped = Signal()
    _resumeLocal = Signal(int)
    _advanceQueue = Signal()
    _streamSeekReady = Signal(int)
    _streamSeekFailed = Signal(str, bool)

    def __init__(
        self,
        queue: QueueModel,
        playback: PlaybackController,
        settings: SettingsStore,
        runtime: AsyncRuntime,
        preparer: MediaPreparer,
    ) -> None:
        super().__init__()
        self.queue = queue
        self.playback = playback
        self.settings = settings
        self.runtime = runtime
        self.preparer = preparer
        self.devices = DeviceListModel()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="MediaPrepare")
        self.cancel_event = threading.Event()
        self._scanning = False
        self._pairing = False
        self._pair_protocol = ""
        self._pair_device_name = ""
        self._pair_instruction = ""
        self._pair_device_id = ""
        self._pair_queue: list[str] = []
        self._preparing = False
        self._preparation_progress_value = 0.0
        self._preparation_status = ""
        self._casting = False
        self._cast_state = "idle"
        self._cast_position = 0
        self._cast_duration = 0
        self._receiver_volume = 0.0
        self._receiver_volume_available = False
        self._transport_controls_available = True
        self._cast_device_name = ""
        self._cast_device_id = ""
        self._last_cast_row = -1
        self._stop_requested = False
        self._active_stream_session = None
        self._stream_start_seconds = 0.0
        self._stream_duration_seconds = 0
        self._stream_absolute_timeline = False
        self._stream_seek_target: int | None = None
        self._pending_stream_session = None
        self._pending_stream_duration_seconds = 0
        self._pending_stream_absolute_timeline = False
        self._requested_start_position_seconds: float | None = None
        self._connecting = False
        self._poll_in_flight = False
        self._cast_generation = 0
        self._local_was_playing = False
        self._closed = False
        self.log = logging.getLogger("violetrelay.controller.airplay")

        self._scanCompleted.connect(self._on_scan)
        self._operationFailed.connect(self._on_error)
        self._pairPromptReady.connect(self._on_pair_prompt)
        self._pairFinished.connect(self._on_pair_finished)
        self._preparationProgress.connect(self._on_preparation_progress)
        self._preparationFinished.connect(self._on_prepared)
        self._castStarted.connect(self._on_cast_started)
        self._statusReady.connect(self._on_status)
        self._stopped.connect(self._on_stopped)
        self._resumeLocal.connect(self._on_resume_local)
        self._advanceQueue.connect(self._advance_cast_queue)
        self._streamSeekReady.connect(self._on_stream_seek_ready)
        self._streamSeekFailed.connect(self._on_stream_seek_failed)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self._poll_status)

    @Property(QObject, constant=True)
    def deviceModel(self) -> QObject:
        return self.devices

    @Property(bool, notify=stateChanged)
    def scanning(self) -> bool:
        return self._scanning

    @Property(bool, notify=pairingChanged)
    def pairing(self) -> bool:
        return self._pairing

    @Property(str, notify=pairingChanged)
    def pairingProtocol(self) -> str:
        return self._pair_protocol

    @Property(str, notify=pairingChanged)
    def pairingDeviceName(self) -> str:
        return self._pair_device_name

    @Property(str, notify=pairingChanged)
    def pairingInstruction(self) -> str:
        return self._pair_instruction

    @Property(bool, notify=stateChanged)
    def preparing(self) -> bool:
        return self._preparing

    @Property(bool, notify=stateChanged)
    def connecting(self) -> bool:
        return self._connecting

    @Property(float, notify=progressChanged)
    def preparationProgress(self) -> float:
        return self._preparation_progress_value

    @Property(str, notify=progressChanged)
    def preparationStatus(self) -> str:
        return self._preparation_status

    @Property(bool, notify=stateChanged)
    def casting(self) -> bool:
        return self._casting

    @Property(str, notify=stateChanged)
    def castState(self) -> str:
        return self._cast_state

    @Property(str, notify=stateChanged)
    def castDeviceName(self) -> str:
        return self._cast_device_name

    @Property(int, notify=castProgressChanged)
    def castPosition(self) -> int:
        return self._cast_position

    @Property(int, notify=castProgressChanged)
    def castDuration(self) -> int:
        return self._cast_duration

    @Property(float, notify=castProgressChanged)
    def receiverVolume(self) -> float:
        return self._receiver_volume

    @Property(bool, notify=castProgressChanged)
    def receiverVolumeAvailable(self) -> bool:
        return self._receiver_volume_available

    @Property(bool, notify=stateChanged)
    def transportControlsAvailable(self) -> bool:
        return self._transport_controls_available

    @Property(bool, notify=stateChanged)
    def seekAvailable(self) -> bool:
        return (
            not self._casting
            or self._active_stream_session is not None
            or self._transport_controls_available
        )

    def _watch(self, future, success_signal: Signal | None = None) -> None:
        def finished(done) -> None:
            if self._closed:
                return
            try:
                value = done.result()
                if success_signal is not None:
                    try:
                        success_signal.emit(value)
                    except TypeError:
                        success_signal.emit()
            except Exception as error:
                self._operationFailed.emit(
                    error_message(error, "The AirPlay operation failed")
                )

        future.add_done_callback(finished)

    def _start_future(self, coroutine):
        if self._closed:
            coroutine.close()
            return None
        try:
            return self.runtime.submit(coroutine)
        except Exception as error:
            try:
                coroutine.close()
            except Exception:
                pass
            self._operationFailed.emit(
                error_message(error, "The AirPlay operation could not be started")
            )
            return None

    def _submit(self, coroutine, success_signal: Signal | None = None) -> None:
        future = self._start_future(coroutine)
        if future is not None:
            self._watch(future, success_signal)

    @Slot()
    def scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.stateChanged.emit()
        self._submit(self.runtime.service.scan(), self._scanCompleted)

    @Slot(int)
    def beginPair(self, row: int) -> None:
        if self._pairing:
            return
        device = self.devices.at(row)
        if not device:
            return
        self._pairing = True
        self._pair_device_id = device.identifier
        self._pair_device_name = device.name
        self._pair_queue = [name for name in ("AirPlay", "Companion") if name in device.protocols]
        self.pairingChanged.emit()
        self._begin_next_pair_protocol()

    def _begin_next_pair_protocol(self) -> None:
        if not self._pair_queue:
            self._pairing = False
            self.pairingChanged.emit()
            self.pairingSucceeded.emit(self._pair_device_name)
            self.scan()
            return
        protocol = self._pair_queue.pop(0)
        self._pair_protocol = protocol
        self.pairingChanged.emit()
        self._submit(
            self.runtime.service.begin_pair(self._pair_device_id, protocol),
            self._pairPromptReady,
        )

    @Slot(str)
    def submitPin(self, pin: str) -> None:
        if not self._pairing:
            self.errorOccurred.emit("No pairing request is active")
            return
        self._submit(self.runtime.service.finish_pair(pin), self._pairFinished)

    @Slot(int)
    def castTo(self, row: int) -> None:
        device = self.devices.at(row)
        item = self.queue.current_item()
        if not device or not item:
            self.errorOccurred.emit("Choose a video and an AirPlay TV first")
            return
        if self.playback.fallbackPreparing:
            self.errorOccurred.emit(
                "Wait for the local compatibility copy to finish or cancel it first"
            )
            return
        if not device.paired:
            self.beginPair(row)
            return
        if self._preparing or self._casting or self._connecting:
            return
        requested_start = self._requested_start_position_seconds
        self._requested_start_position_seconds = None
        start_position_seconds = (
            max(0.0, requested_start)
            if requested_start is not None
            else max(0.0, self.playback.position / 1000.0)
        )
        self._last_cast_row = row
        self._cast_device_id = device.identifier
        self._cast_device_name = device.name
        self._transport_controls_available = device.transport_controls
        try:
            self.settings.set("preferred_device_id", device.identifier)
        except Exception:
            self.log.warning("Preferred AirPlay receiver could not be saved", exc_info=True)
        self._preparing = True
        self._preparation_progress_value = 0.0
        self._preparation_status = "Inspecting media"
        self.cancel_event.clear()
        self._local_was_playing = self.playback.playing
        self.playback.pause()
        self.stateChanged.emit()
        self.progressChanged.emit()
        self._start_media_preparation(item, start_position_seconds)

    def _start_media_preparation(self, item, start_position_seconds: float) -> None:
        seeking = self._stream_seek_target is not None
        try:
            future = self.executor.submit(
                self.preparer.prepare,
                item.source,
                item.subtitle,
                lambda value, status: (
                    None
                    if self._closed
                    else self._preparationProgress.emit(value, status)
                ),
                self.cancel_event,
                start_position_seconds,
                item.audio_stream,
                # Built-in receivers need a correctly labelled HLS queue item
                # to use their full-screen MSE video path. The preparer streams
                # only an initial GPU buffer, so casting does not wait for a
                # complete compatibility copy.
                allow_hls_playback=True,
            )
        except RuntimeError as error:
            message = error_message(error, "Cast preparation could not be started")
            if seeking:
                self._on_stream_seek_failed(message, True)
            else:
                self._preparing = False
                self.stateChanged.emit()
                if self._local_was_playing:
                    self.playback.player.play()
                self.errorOccurred.emit(message)
            return

        def completed(done) -> None:
            if self._closed:
                try:
                    prepared = done.result()
                except Exception:
                    return
                if prepared.stream_session is not None:
                    try:
                        prepared.stream_session.stop()
                    except Exception:
                        self.log.warning(
                            "Prepared stream cleanup failed during shutdown",
                            exc_info=True,
                        )
                return
            try:
                self._preparationFinished.emit(done.result())
            except ConversionCancelled:
                if seeking:
                    self._streamSeekFailed.emit("Cast seek cancelled", True)
                else:
                    self._operationFailed.emit("Cast preparation cancelled")
            except Exception as error:
                message = error_message(error, "Cast preparation failed")
                if seeking:
                    self._streamSeekFailed.emit(message, True)
                else:
                    self._operationFailed.emit(message)

        future.add_done_callback(completed)

    @Slot()
    def cancelPreparation(self) -> None:
        self.cancel_event.set()

    @Slot()
    def playPause(self) -> None:
        command = "play" if self._cast_state == "paused" else "pause"
        self._submit(self.runtime.service.command(command))

    @Slot(float)
    def setReceiverVolume(self, level: float) -> None:
        if not self._casting or not self._receiver_volume_available:
            return
        self._receiver_volume = max(0.0, min(100.0, float(level)))
        self.castProgressChanged.emit()
        self._submit(self.runtime.service.set_volume(self._receiver_volume))

    @Slot(int)
    def seek(self, seconds: int) -> None:
        if not self._casting or self._preparing:
            return
        if self._active_stream_session is None:
            self._submit(self.runtime.service.command("seek", seconds))
            return

        # Generated EVENT-HLS only contains media from its producer's start
        # point through the current live edge. Apple TV cannot reliably seek
        # beyond that edge, so restart the producer at the requested absolute
        # movie position instead of sending a remote relative seek.
        target = max(0, int(seconds))
        if self._stream_duration_seconds > 0:
            target = min(target, max(0, self._stream_duration_seconds - 1))
        if abs(target - self._cast_position) < 2:
            return

        item = self.queue.current_item()
        if item is None:
            return
        self._stream_seek_target = target
        self._preparing = True
        self._preparation_progress_value = 0.0
        self._preparation_status = f"Seeking to {target // 60}:{target % 60:02d}"
        self.cancel_event.clear()
        self.stateChanged.emit()
        self.progressChanged.emit()
        self._start_media_preparation(item, float(target))

    @Slot()
    def stopCasting(self) -> None:
        if not self._casting:
            return
        self._stop_requested = True
        future = self._start_future(self.runtime.service.stop_cast())
        if future is None:
            self._stopped.emit()
            return

        def finished(done) -> None:
            if self._closed:
                return
            try:
                done.result()
            except Exception as error:
                self._operationFailed.emit(
                    error_message(error, "AirPlay could not be stopped cleanly")
                )
            finally:
                self._stopped.emit()

        future.add_done_callback(finished)

    @Slot()
    def continueLocally(self) -> None:
        position = self._cast_position
        self._stop_requested = True
        future = self._start_future(self.runtime.service.stop_cast())
        if future is None:
            self._stopped.emit()
            self._resumeLocal.emit(position)
            return

        def finished(done) -> None:
            try:
                done.result()
            except Exception as error:
                self._operationFailed.emit(
                    error_message(error, "AirPlay could not be stopped cleanly")
                )
            finally:
                self._stopped.emit()
                self._resumeLocal.emit(position)

        future.add_done_callback(finished)

    def _on_scan(self, devices: list[AirPlayDevice]) -> None:
        self._scanning = False
        preferred = str(self.settings.get("preferred_device_id", "") or "")
        if preferred:
            devices = sorted(
                devices,
                key=lambda device: (
                    device.identifier != preferred,
                    device.name.casefold(),
                ),
            )
        self.devices.replace(devices, preferred)
        self.stateChanged.emit()

    def _on_error(self, message: str) -> None:
        self.log.warning("AirPlay operation failed: %s", message)
        if self._casting:
            self._checkpoint_playback_position(force=True)
        was_preparing = self._preparing or (
            self._active_stream_session is not None and not self._casting
        ) or self._connecting
        self._scanning = False
        self._preparing = False
        self._connecting = False
        if self._pairing:
            self._pairing = False
            self._pair_instruction = ""
            self._pair_queue.clear()
            self.pairingChanged.emit()
        self.stateChanged.emit()
        if self._active_stream_session is not None and not self._casting:
            self._cleanup_stream_session()
            self._submit(self.runtime.service.stop_cast())
        if was_preparing and self._local_was_playing:
            self.playback.player.play()
        self.errorOccurred.emit(message or "The AirPlay operation failed")

    def _on_pair_prompt(self, prompt: PairingPrompt | None) -> None:
        if prompt is None:
            self._begin_next_pair_protocol()
            return
        self._pair_protocol = prompt.protocol
        self._pair_instruction = (
            f"Enter the PIN shown on {self._pair_device_name}"
            if prompt.device_provides_pin
            else f"Enter {prompt.pin_for_device} on {self._pair_device_name}, then continue"
        )
        self.pairingChanged.emit()

    def _on_pair_finished(self, paired: bool) -> None:
        if not paired:
            self._pairing = False
            self.pairingChanged.emit()
            self.errorOccurred.emit(f"{self._pair_protocol} pairing was not completed")
            return
        self._begin_next_pair_protocol()

    def _on_preparation_progress(self, value: float, status: str) -> None:
        self._preparation_progress_value = value
        self._preparation_status = status
        self.progressChanged.emit()

    def _on_prepared(self, prepared: PreparedMedia) -> None:
        if self._stream_seek_target is not None:
            self._on_stream_seek_prepared(prepared)
            return
        self._preparing = False
        self._preparation_progress_value = 1.0
        self._preparation_status = "Connecting to AirPlay TV"
        self.stateChanged.emit()
        self.progressChanged.emit()
        self._active_stream_session = prepared.stream_session
        absolute_timeline = bool(getattr(prepared, "absolute_timeline", False))
        if prepared.streaming:
            self._stream_absolute_timeline = absolute_timeline
            self._stream_start_seconds = max(
                0.0,
                prepared.start_position_seconds,
            )
            source_duration = (
                prepared.media_info.duration_seconds
                if prepared.media_info is not None
                else self.playback.duration / 1000.0
            )
            self._stream_duration_seconds = max(
                int(round(source_duration)),
                int(self._stream_start_seconds),
            )
        else:
            self._stream_absolute_timeline = False
            self._stream_start_seconds = 0.0
            self._stream_duration_seconds = 0
        self._connecting = True
        self.log.info(
            "Cast media prepared; connecting to receiver=%s streaming=%s",
            self._cast_device_name,
            prepared.streaming,
        )
        expected_duration = (
            prepared.media_info.duration_seconds
            if prepared.media_info is not None
            else self.playback.duration / 1000.0
        )
        if prepared.streaming and not absolute_timeline:
            expected_duration -= prepared.start_position_seconds
        cast_position = self.playback.position / 1000.0
        if prepared.streaming:
            cast_position = (
                prepared.start_position_seconds if absolute_timeline else 0.0
            )
        self.stateChanged.emit()
        self._submit(
            self.runtime.service.start_cast(
                self._cast_device_id,
                prepared.source,
                cast_position,
                max(0.0, expected_duration),
            ),
            self._castStarted,
        )

    def _on_stream_seek_prepared(self, prepared: PreparedMedia) -> None:
        target = self._stream_seek_target
        if target is None:
            if prepared.stream_session is not None:
                self._stop_stream_session(prepared.stream_session)
            return
        if (
            not self._casting
            or not prepared.streaming
            or prepared.stream_session is None
        ):
            if prepared.stream_session is not None:
                self._stop_stream_session(prepared.stream_session)
            self._streamSeekFailed.emit(
                "AirPlay seek could not create a replacement video stream",
                bool(self._casting),
            )
            return

        source_duration = (
            prepared.media_info.duration_seconds
            if prepared.media_info is not None
            else self.playback.duration / 1000.0
        )
        absolute_timeline = bool(getattr(prepared, "absolute_timeline", False))
        self._pending_stream_session = prepared.stream_session
        self._pending_stream_absolute_timeline = absolute_timeline
        self._pending_stream_duration_seconds = max(
            int(round(source_duration)),
            target,
        )
        self._preparation_progress_value = 1.0
        self._preparation_status = "Switching the TV to the new position"
        self.progressChanged.emit()
        remaining_duration = max(0.0, source_duration - target)
        coroutine = self.runtime.service.replace_stream(
            prepared.source,
            target if absolute_timeline else 0.0,
            source_duration if absolute_timeline else remaining_duration,
        )
        try:
            future = self.runtime.submit(coroutine)
        except Exception as error:
            try:
                coroutine.close()
            except Exception:
                pass
            self._streamSeekFailed.emit(
                error_message(error, "AirPlay seek could not be started"),
                True,
            )
            return

        def finished(done) -> None:
            if self._closed:
                return
            try:
                done.result()
            except Exception as error:
                self._streamSeekFailed.emit(
                    error_message(error, "AirPlay seek failed"),
                    bool(getattr(error, "cast_still_active", False)),
                )
            else:
                self._streamSeekReady.emit(target)

        future.add_done_callback(finished)

    def _on_cast_started(self) -> None:
        self._connecting = False
        self._cast_generation += 1
        self._casting = True
        self._cast_state = "playing"
        if self._active_stream_session is not None:
            self._cast_position = int(self._stream_start_seconds)
            self._cast_duration = self._stream_duration_seconds
        else:
            self._cast_position = 0
            self._cast_duration = 0
        self._stop_requested = False
        self.log.info("Cast confirmed on receiver=%s", self._cast_device_name)
        self.poll_timer.start()
        self.castProgressChanged.emit()
        self.stateChanged.emit()

    def _poll_status(self) -> None:
        if not self._casting or self._poll_in_flight:
            return
        future = self._start_future(self.runtime.service.status())
        if future is None:
            return
        self._poll_in_flight = True
        generation = self._cast_generation

        def finished(done) -> None:
            self._poll_in_flight = False
            if self._closed or generation != self._cast_generation:
                return
            try:
                self._statusReady.emit(done.result())
            except Exception as error:
                self._operationFailed.emit(
                    error_message(error, "AirPlay status could not be read")
                )

        future.add_done_callback(finished)

    def _on_status(self, status: CastStatus) -> None:
        self._cast_state = status.state
        if self._active_stream_session is not None:
            absolute_position = status.position_seconds
            if not self._stream_absolute_timeline:
                absolute_position += self._stream_start_seconds
            if self._stream_duration_seconds > 0:
                absolute_position = min(
                    absolute_position,
                    self._stream_duration_seconds,
                )
            self._cast_position = max(0, int(absolute_position))
            self._cast_duration = max(
                self._stream_duration_seconds,
                self._cast_position,
            )
        else:
            self._cast_position = status.position_seconds
            self._cast_duration = status.duration_seconds
        self._receiver_volume_available = status.can_set_volume
        if status.receiver_volume is not None:
            self._receiver_volume = status.receiver_volume
        self._checkpoint_playback_position(
            force=status.state in {"ended", "stopped", "error"}
        )
        self.castProgressChanged.emit()
        self.stateChanged.emit()
        if status.state == "error":
            self.log.warning("Active cast failed: %s", status.error)
            recoverable = "lost connection" in status.error.casefold()
            self._finish_cast()
            self._cleanup_stream_session()
            self._submit(self.runtime.service.stop_cast(), self._stopped)
            if recoverable:
                self.recoveryNeeded.emit(
                    status.error
                    or "The AirPlay connection was lost. Retry or continue here."
                )
            else:
                self.errorOccurred.emit(status.error or "AirPlay playback failed")
        elif status.state == "ended":
            clear_resume = getattr(
                self.playback,
                "clear_resume_position",
                None,
            )
            if callable(clear_resume):
                clear_resume()
            self._finish_cast()
            if self.queue.next_index() >= 0:
                future = self._start_future(self.runtime.service.stop_cast())
                if future is None:
                    self._cleanup_stream_session()
                    return

                def advance(done) -> None:
                    try:
                        done.result()
                        self._stopped.emit()
                        self._advanceQueue.emit()
                    except Exception as error:
                        self._operationFailed.emit(
                            error_message(error, "AirPlay queue cleanup failed")
                        )

                future.add_done_callback(advance)
            else:
                self._submit(self.runtime.service.stop_cast(), self._stopped)
        elif status.state == "stopped" and not self._stop_requested:
            self._finish_cast()
            self._cleanup_stream_session()
            self._submit(self.runtime.service.stop_cast(), self._stopped)

    def _on_stopped(self) -> None:
        self._checkpoint_playback_position(force=True)
        self._finish_cast()
        self._cleanup_stream_session()

    def _on_resume_local(self, position: int) -> None:
        self.playback.seek(position * 1000)
        self.playback.player.play()

    @Slot()
    def retryCasting(self) -> None:
        if self._preparing or self._connecting or self._casting:
            return
        row = next(
            (
                index
                for index, device in enumerate(self.devices.devices)
                if device.identifier == self._cast_device_id
            ),
            self._last_cast_row,
        )
        if self.devices.at(row) is None:
            self.errorOccurred.emit(
                "The AirPlay TV is no longer in the device list. Rescan and try again."
            )
            return
        self._requested_start_position_seconds = float(self._cast_position)
        self.castTo(row)

    @Slot()
    def continueAfterDisconnect(self) -> None:
        if self._casting:
            self.continueLocally()
            return
        self._on_resume_local(self._cast_position)

    def _on_stream_seek_ready(self, target: int) -> None:
        if self._closed:
            return
        old_session = self._active_stream_session
        new_session = self._pending_stream_session
        self._pending_stream_session = None
        if new_session is None:
            self._on_stream_seek_failed(
                "AirPlay seek completed without a replacement stream",
                False,
            )
            return
        self._active_stream_session = new_session
        self._stream_absolute_timeline = self._pending_stream_absolute_timeline
        self._pending_stream_absolute_timeline = False
        if old_session is not None and old_session is not new_session:
            self._stop_stream_session(old_session)
        self._stream_start_seconds = float(target)
        self._stream_duration_seconds = max(
            self._pending_stream_duration_seconds,
            target,
        )
        self._pending_stream_duration_seconds = 0
        self._stream_seek_target = None
        self._preparing = False
        self._preparation_status = "Playing on TV"
        self.playback.seek(target * 1000)
        self._cast_position = target
        self._cast_duration = self._stream_duration_seconds
        self._cast_state = "playing"
        self._cast_generation += 1
        self._stop_requested = False
        self.log.info(
            "Cast seek completed inside the active receiver session: position=%d",
            target,
        )
        self.stateChanged.emit()
        self.progressChanged.emit()
        self.castProgressChanged.emit()

    def _on_stream_seek_failed(
        self,
        message: str,
        cast_still_active: bool,
    ) -> None:
        pending_session = self._pending_stream_session
        self._pending_stream_session = None
        if pending_session is not None:
            self._stop_stream_session(pending_session)
        self._pending_stream_duration_seconds = 0
        self._pending_stream_absolute_timeline = False
        self._stream_seek_target = None
        self._preparing = False
        self._preparation_status = "Playing on TV" if cast_still_active else ""
        if not cast_still_active:
            resume_position = self._cast_position
            self._finish_cast()
            self._cleanup_stream_session()
            self._submit(self.runtime.service.stop_cast())
            if self._local_was_playing:
                self.playback.seek(resume_position * 1000)
                self.playback.player.play()
        self.stateChanged.emit()
        self.progressChanged.emit()
        self.errorOccurred.emit(message or "AirPlay seek failed")

    def _advance_cast_queue(self) -> None:
        self.playback.next()
        row = next(
            (
                index
                for index, device in enumerate(self.devices.devices)
                if device.identifier == self._cast_device_id
            ),
            self._last_cast_row,
        )
        QTimer.singleShot(300, lambda: None if self._closed else self.castTo(row))

    def _cleanup_stream_session(self) -> None:
        session = self._active_stream_session
        self._active_stream_session = None
        self._stream_absolute_timeline = False
        if session is not None:
            self._stop_stream_session(session)

    def _stop_stream_session(self, session) -> None:
        try:
            future = self.executor.submit(session.stop)

            def cleaned(done) -> None:
                try:
                    error = done.exception()
                except concurrent.futures.CancelledError:
                    return
                if error is not None:
                    self.log.warning("Streaming-session cleanup failed: %s", error)

            future.add_done_callback(cleaned)
        except RuntimeError:
            try:
                session.stop()
            except Exception:
                self.log.warning("Streaming-session cleanup failed", exc_info=True)

    def _finish_cast(self) -> None:
        self.poll_timer.stop()
        self._cast_generation += 1
        self._casting = False
        self._connecting = False
        self._cast_state = "idle"
        self.stateChanged.emit()

    def _checkpoint_playback_position(self, *, force: bool = False) -> None:
        checkpoint = getattr(
            self.playback,
            "checkpoint_remote_position",
            None,
        )
        if callable(checkpoint):
            checkpoint(
                int(self._cast_position * 1000),
                int(self._cast_duration * 1000),
                force=force,
            )

    def close(self) -> None:
        if self._closed:
            return
        if self._casting:
            self._checkpoint_playback_position(force=True)
        self._closed = True
        self.cancel_event.set()
        self.poll_timer.stop()
        if self._active_stream_session is not None:
            try:
                self._active_stream_session.stop()
            except Exception:
                self.log.warning("Streaming-session shutdown failed", exc_info=True)
            self._active_stream_session = None
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        finally:
            self.runtime.close()
