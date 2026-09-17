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
