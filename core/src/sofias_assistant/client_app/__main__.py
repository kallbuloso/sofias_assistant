"""Desktop Client executable entry point."""

from __future__ import annotations

import argparse
import os
import sys
from uuid import UUID

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit

from sofias_assistant.client_app.executable_locator import CoreExecutableLocator
from sofias_assistant.client_app.instance_identity import resolve_expected_instance_key
from sofias_assistant.client_app.launcher import QtProcessLauncher
from sofias_assistant.client_app.qt_app import create_application
from sofias_assistant.client_app.supervisor import (
    DesktopCoreSupervisor,
    SupervisorState,
)
from sofias_assistant.client_attach.windows_store import WindowsClientAttachStore


def _attach_via_supervisor() -> tuple[str, str, UUID] | None:
    """Discover/start/attach the expected Core with no human token handling.

    Returns `(base_url, credential, runtime_session_id)` on success, or
    `None` when the bounded attach/launch algorithm could not reach
    `CORE_READY` (Desktop/Core Interaction Contract v1 SS12).
    """

    instance_key = resolve_expected_instance_key()
    attach_store = WindowsClientAttachStore()
    supervisor = DesktopCoreSupervisor(
        instance_key=instance_key,
        attach_store=attach_store,
        executable_locator=CoreExecutableLocator(),
        process_launcher=QtProcessLauncher(),
    )
    state = supervisor.attach()
    if state is not SupervisorState.CORE_READY:
        return None
    record = attach_store.read(instance_key)
    if record is None:
        return None
    base_url = f"http://{record.host}:{record.port}"
    return base_url, record.credential.reveal(), record.runtime_session_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sofia's Assistant Desktop Client")
    parser.add_argument("--core-url", default=os.environ.get("SOFIA_CORE_URL"))
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Start and exit after the UI smoke interval",
    )
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv)

    credential = os.environ.get("SOFIA_CLIENT_CREDENTIAL", "")
    runtime_session_id: UUID | None = None
    if args.smoke:
        core_url = args.core_url or "http://127.0.0.1:8989"
        credential = credential or "smoke-placeholder"
    elif args.core_url or credential:
        # Explicit dev/test override: bypass supervision entirely.
        core_url = args.core_url or "http://127.0.0.1:8989"
        if not credential:
            credential, accepted = QInputDialog.getText(
                None,
                "Connect to Sofia Core",
                "Local Client credential:",
                QLineEdit.EchoMode.Password,
            )
            if not accepted or not credential:
                return 1
    else:
        # Seamless human path: discover/start/attach Core automatically
        # (Amendment 0004; Desktop/Core Interaction Contract v1).
        attached = _attach_via_supervisor()
        if attached is None:
            return 1
        core_url, credential, runtime_session_id = attached

    app, window = create_application(
        core_url,
        credential,
        auto_connect=not args.smoke,
        runtime_session_id=runtime_session_id,
    )
    if args.smoke:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1500, window._quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
