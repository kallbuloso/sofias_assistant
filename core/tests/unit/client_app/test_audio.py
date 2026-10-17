"""Deterministic tests for the Gate I18 audio device abstraction."""

from __future__ import annotations

import pytest

from sofias_assistant.client_app.audio import (
    AudioDeviceError,
    AudioInputDevice,
    AudioOutputDevice,
    FailingAudioInputDevice,
    FailingAudioOutputDevice,
    FakeAudioInputDevice,
    FakeAudioOutputDevice,
    _convert_pcm16_mono,
)


def test_fake_input_device_replays_chunks_in_order() -> None:
    chunks = [b"\x00\x01", b"\x02\x03", b"\x04\x05"]
    device = FakeAudioInputDevice(chunks)
    received: list[bytes] = []

    device.start(received.append)

    assert received == chunks
    assert device.started is True
    device.stop()
    assert device.stopped is True


def test_fake_input_device_satisfies_the_protocol() -> None:
    assert isinstance(FakeAudioInputDevice(), AudioInputDevice)


def test_failing_input_device_raises_audio_device_error() -> None:
    device = FailingAudioInputDevice()

    with pytest.raises(AudioDeviceError):
        device.start(lambda _chunk: None)


def test_fake_output_device_records_writes_in_order() -> None:
    device = FakeAudioOutputDevice()
    device.start()

    device.write(b"\x00\x01")
    device.write(b"\x02\x03")

    assert device.written == [b"\x00\x01", b"\x02\x03"]
    device.stop()
    assert device.stopped is True


def test_fake_output_device_satisfies_the_protocol() -> None:
    assert isinstance(FakeAudioOutputDevice(), AudioOutputDevice)


def test_fake_output_device_rejects_write_before_start() -> None:
    device = FakeAudioOutputDevice()

    with pytest.raises(AudioDeviceError):
        device.write(b"\x00\x01")


def test_failing_output_device_raises_audio_device_error() -> None:
    device = FailingAudioOutputDevice()

    with pytest.raises(AudioDeviceError):
        device.start()
    with pytest.raises(AudioDeviceError):
        device.write(b"\x00")



def test_pcm16_mono_24k_to_48k_preserves_duration() -> None:
    # 4 source frames at 24 kHz should become 8 frames at 48 kHz.
    source = (
        (0).to_bytes(2, "little", signed=True)
        + (1000).to_bytes(2, "little", signed=True)
        + (2000).to_bytes(2, "little", signed=True)
        + (3000).to_bytes(2, "little", signed=True)
    )

    converted = _convert_pcm16_mono(
        source,
        source_sample_rate=24_000,
        target_sample_rate=48_000,
        target_channels=1,
    )

    assert len(converted) == 16


def test_pcm16_mono_to_stereo_duplicates_each_sample() -> None:
    source = (
        (100).to_bytes(2, "little", signed=True)
        + (-100).to_bytes(2, "little", signed=True)
    )

    converted = _convert_pcm16_mono(
        source,
        source_sample_rate=24_000,
        target_sample_rate=24_000,
        target_channels=2,
    )

    assert converted == (
        (100).to_bytes(2, "little", signed=True)
        + (100).to_bytes(2, "little", signed=True)
        + (-100).to_bytes(2, "little", signed=True)
        + (-100).to_bytes(2, "little", signed=True)
    )



def test_partial_sink_writes_preserve_unwritten_audio() -> None:
    class _Sink:
        def __init__(self) -> None:
            self.free = 4

        def bytesFree(self) -> int:
            return self.free

    class _Io:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def write(self, data: bytes) -> int:
            self.calls.append(data)
            return 2

    from sofias_assistant.client_app.audio import QtAudioOutputDevice

    device = QtAudioOutputDevice()
    device._sink = _Sink()
    device._io_device = _Io()
    device._pending.extend(b"abcdef")

    device._drain()

    assert device._io_device.calls == [b"abcd"]
    assert bytes(device._pending) == b"cdef"
