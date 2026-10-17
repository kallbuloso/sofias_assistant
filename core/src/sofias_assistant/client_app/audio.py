"""Bounded audio input/output device abstraction (Gate I18, SA-B041).

Desktop/Core Interaction Contract v1 SS45-SS47: the Desktop owns microphone
capture and speaker playback only; Core continues to own the realtime
Conversation/session domain and the existing `realtime.v1` wire protocol.
This module never creates a second Realtime runtime -- it only produces/
consumes the exact PCM16/24000Hz/mono chunks that
`RealtimeVoiceConnection.send_audio()`/`pump_events()` already expect
(`client_boundary/realtime_ws.py` `_audio_format()`).

Deterministic fakes are the CI-authoritative implementation (Contract v1
SS47); the QtMultimedia-backed classes are a best-effort Windows-first
hardware baseline exercised only by an opt-in live test, since this
sandboxed environment has no functional audio backend even where
`QMediaDevices` enumerates a device (see test file for the exact failure
mode observed).
"""

from __future__ import annotations

from array import array
from collections.abc import Callable
import sys
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QAudioSource

SAMPLE_RATE_HZ = 24000
CHANNELS = 1


class AudioDeviceError(RuntimeError):
    """Raised when a device fails to start/write.

    Voice becomes unavailable/degraded; text remains usable (Contract v1
    SS47/SS59). Never authorizes widening locality or switching provider.
    """


@runtime_checkable
class AudioInputDevice(Protocol):
    """Bounded microphone capture producing PCM16/24000Hz/mono chunks only."""

    def start(self, on_chunk: Callable[[bytes], None]) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class AudioOutputDevice(Protocol):
    """Bounded speaker playback consuming PCM16/24000Hz/mono chunks only."""

    def start(self) -> None: ...

    def write(self, chunk: bytes) -> None: ...

    def stop(self) -> None: ...


class FakeAudioInputDevice:
    """Deterministic microphone fake: replays one bounded scripted sequence."""

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self._chunks = list(chunks or [])
        self.started = False
        self.stopped = False

    def start(self, on_chunk: Callable[[bytes], None]) -> None:
        self.started = True
        for chunk in self._chunks:
            on_chunk(chunk)

    def stop(self) -> None:
        self.stopped = True


class FailingAudioInputDevice:
    """Deterministic microphone fake that always fails to start."""

    def start(self, on_chunk: Callable[[bytes], None]) -> None:
        raise AudioDeviceError("Microphone is not available")

    def stop(self) -> None:
        return None


class FakeAudioOutputDevice:
    """Deterministic speaker fake: records every chunk written, in order."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.written: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def write(self, chunk: bytes) -> None:
        if not self.started:
            raise AudioDeviceError("Speaker output is not active")
        self.written.append(chunk)

    def stop(self) -> None:
        self.stopped = True


class FailingAudioOutputDevice:
    """Deterministic speaker fake that always fails to start."""

    def start(self) -> None:
        raise AudioDeviceError("Speaker output is not available")

    def write(self, chunk: bytes) -> None:
        raise AudioDeviceError("Speaker output is not active")

    def stop(self) -> None:
        return None


def _build_audio_format() -> QAudioFormat:
    from PySide6.QtMultimedia import QAudioFormat

    audio_format = QAudioFormat()
    audio_format.setSampleRate(SAMPLE_RATE_HZ)
    audio_format.setChannelCount(CHANNELS)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return audio_format


class QtAudioInputDevice:
    """Real PySide6 QtMultimedia microphone capture (Windows-first baseline).

    Must run on a thread with an active Qt event loop (the existing
    `ClientWorker` QThread), since `readyRead` is a queued Qt signal.
    """

    def __init__(self) -> None:
        self._source: QAudioSource | None = None
        self._io_device: Any = None
        self._on_chunk: Callable[[bytes], None] | None = None

    def start(self, on_chunk: Callable[[bytes], None]) -> None:
        from PySide6.QtMultimedia import QAudioSource, QMediaDevices

        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise AudioDeviceError("No microphone is available")
        audio_format = _build_audio_format()
        if not device.isFormatSupported(audio_format):
            raise AudioDeviceError(
                "Microphone does not support the required PCM16/24000Hz/mono format"
            )
        self._on_chunk = on_chunk
        source = QAudioSource(device, audio_format)
        io_device = source.start()
        if io_device is None:
            raise AudioDeviceError("Microphone could not be started")
        io_device.readyRead.connect(self._read_available)
        self._source = source
        self._io_device = io_device

    def _read_available(self) -> None:
        io_device = self._io_device
        on_chunk = self._on_chunk
        if io_device is None or on_chunk is None:
            return
        data = bytes(io_device.readAll().data())
        if data:
            on_chunk(data)

    def stop(self) -> None:
        if self._source is not None:
            self._source.stop()
        self._source = None
        self._io_device = None
        self._on_chunk = None


class QtAudioOutputDevice:
    """Real PySide6 QtMultimedia speaker playback (Windows-first baseline).

    OpenAI Realtime emits PCM16/24 kHz/mono. Some Windows audio backends report
    that format as supported but still render through a 48 kHz device path,
    which makes raw 24 kHz samples play roughly twice as fast. We therefore
    negotiate a device-rate Int16 format and convert the provider PCM explicitly
    before writing it to Qt.
    """

    def __init__(self) -> None:
        self._sink: QAudioSink | None = None
        self._io_device: Any = None
        self._target_sample_rate = SAMPLE_RATE_HZ
        self._target_channels = CHANNELS

    def start(self) -> None:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise AudioDeviceError("No speaker output is available")

        preferred = device.preferredFormat()
        target = QAudioFormat()
        target.setSampleRate(preferred.sampleRate())
        target.setChannelCount(CHANNELS)
        target.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        if not device.isFormatSupported(target):
            target = preferred
            if target.sampleFormat() is not QAudioFormat.SampleFormat.Int16:
                raise AudioDeviceError(
                    "Speaker preferred format is not PCM16 and cannot be converted safely"
                )
            if target.channelCount() not in (1, 2):
                raise AudioDeviceError(
                    "Speaker preferred channel layout is not supported"
                )

        sink = QAudioSink(device, target)
        io_device = sink.start()
        if io_device is None:
            raise AudioDeviceError("Speaker could not be started")

        self._target_sample_rate = target.sampleRate()
        self._target_channels = target.channelCount()
        self._sink = sink
        self._io_device = io_device

    def write(self, chunk: bytes) -> None:
        if self._io_device is None:
            raise AudioDeviceError("Speaker output is not active")
        converted = _convert_pcm16_mono(
            chunk,
            source_sample_rate=SAMPLE_RATE_HZ,
            target_sample_rate=self._target_sample_rate,
            target_channels=self._target_channels,
        )
        self._io_device.write(converted)

    def stop(self) -> None:
        if self._sink is not None:
            self._sink.stop()
        self._sink = None
        self._io_device = None
        self._target_sample_rate = SAMPLE_RATE_HZ
        self._target_channels = CHANNELS


def _convert_pcm16_mono(
    chunk: bytes,
    *,
    source_sample_rate: int,
    target_sample_rate: int,
    target_channels: int,
) -> bytes:
    """Convert little-endian PCM16 mono to a device-rate mono/stereo stream."""

    if len(chunk) % 2:
        raise AudioDeviceError("PCM16 audio chunk has an invalid byte length")
    if source_sample_rate <= 0 or target_sample_rate <= 0:
        raise AudioDeviceError("Audio sample rates must be positive")
    if target_channels not in (1, 2):
        raise AudioDeviceError("Only mono and stereo speaker output are supported")
    if not chunk:
        return b""

    samples = array("h")
    samples.frombytes(chunk)
    if sys.byteorder != "little":
        samples.byteswap()

    if target_sample_rate == source_sample_rate:
        resampled = samples
    else:
        output_count = max(
            1,
            round(len(samples) * target_sample_rate / source_sample_rate),
        )
        resampled = array("h")
        if len(samples) == 1:
            resampled.extend([samples[0]] * output_count)
        else:
            scale = source_sample_rate / target_sample_rate
            last = len(samples) - 1
            for index in range(output_count):
                position = min(index * scale, last)
                left = int(position)
                right = min(left + 1, last)
                fraction = position - left
                value = round(
                    samples[left] * (1.0 - fraction)
                    + samples[right] * fraction
                )
                resampled.append(max(-32768, min(32767, value)))

    if target_channels == 2:
        interleaved = array("h")
        for sample in resampled:
            interleaved.append(sample)
            interleaved.append(sample)
        resampled = interleaved

    if sys.byteorder != "little":
        resampled.byteswap()
    return resampled.tobytes()
