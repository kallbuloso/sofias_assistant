"""Explicitly opt-in real QtMultimedia audio device smoke coverage.

This sandboxed environment enumerates a default input/output device via
`QMediaDevices` but has no functional audio backend: `QAudioSource.start()`/
`QAudioSink.start()` return `None` instead of a usable `QIODevice`. Both
`QtAudioInputDevice`/`QtAudioOutputDevice` already treat that as
`AudioDeviceError` (Contract v1 SS47: microphone/speaker unavailable
degrades voice; text remains usable) rather than crashing, so this test
accepts either a real successful round trip (on a machine with a working
audio backend) or a clean `AudioDeviceError` -- it never silently claims a
live hardware round trip that did not happen.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.getenv("SOFIAS_ASSISTANT_RUN_AUDIO_HARDWARE_TESTS") != "1",
    reason="requires explicit audio hardware smoke opt-in on Windows",
)


@pytest.mark.integration
@pytest.mark.smoke
def test_qt_audio_input_device_starts_or_fails_safely() -> None:
    from PySide6.QtWidgets import QApplication

    from sofias_assistant.client_app.audio import AudioDeviceError, QtAudioInputDevice

    app = QApplication.instance() or QApplication([])
    device = QtAudioInputDevice()
    try:
        device.start(lambda _chunk: None)
    except AudioDeviceError:
        pytest.skip("no functional microphone backend in this environment")
    else:
        device.stop()
    finally:
        del app


@pytest.mark.integration
@pytest.mark.smoke
def test_qt_audio_output_device_starts_or_fails_safely() -> None:
    from PySide6.QtWidgets import QApplication

    from sofias_assistant.client_app.audio import AudioDeviceError, QtAudioOutputDevice

    app = QApplication.instance() or QApplication([])
    device = QtAudioOutputDevice()
    try:
        device.start()
    except AudioDeviceError:
        pytest.skip("no functional speaker backend in this environment")
    else:
        device.write(b"\x00\x00" * 2400)
        device.stop()
    finally:
        del app
