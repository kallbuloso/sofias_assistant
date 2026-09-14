"""Desktop Client executable entry point."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit

from sofias_assistant.client_app.qt_app import create_application


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sofia's Assistant Desktop Client")
    parser.add_argument(
        "--core-url", default=os.environ.get("SOFIA_CORE_URL", "http://127.0.0.1:8989")
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Start and exit after the UI smoke interval",
    )
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv)
    credential = os.environ.get("SOFIA_CLIENT_CREDENTIAL", "")
    if not credential and not args.smoke:
        credential, accepted = QInputDialog.getText(
            None,
            "Connect to Sofia Core",
            "Local Client credential:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted or not credential:
            return 1
    app, window = create_application(
        args.core_url,
        credential or "smoke-placeholder",
        auto_connect=not args.smoke,
    )
    if args.smoke:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1500, window._quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
