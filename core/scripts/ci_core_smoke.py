"""CI smoke for the packaged `SofiaCore.exe` (Gate I16 packaging acceptance).

Launches the built `dist/SofiaCore.exe` as a genuinely separate OS process,
waits for it to publish its `ClientAttachRecord` to the real Windows
Credential Manager, verifies the authenticated `GET /api/v1/runtime/identity`
contract, requests a graceful shutdown through `POST /api/v1/runtime/shutdown`,
and confirms the process exits cleanly and the attach record is removed.

Exits non-zero (with a clear message) on any failure so CI fails loudly.
Never prints the attach credential.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from sofias_assistant.client_app.api import CoreApiClient
from sofias_assistant.client_app.instance_identity import resolve_expected_instance_key
from sofias_assistant.client_attach.models import ClientAttachRecord
from sofias_assistant.client_attach.windows_store import WindowsClientAttachStore

_ATTACH_TIMEOUT_SECONDS = 30.0
_ATTACH_POLL_INTERVAL_SECONDS = 0.5
_SHUTDOWN_TIMEOUT_SECONDS = 15.0


def _wait_for_record(
    store: WindowsClientAttachStore, instance_key: str, timeout: float
) -> ClientAttachRecord | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = store.read(instance_key)
        if record is not None:
            return record
        time.sleep(_ATTACH_POLL_INTERVAL_SECONDS)
    return None


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    executable = repo_root / "dist" / "SofiaCore.exe"
    if not executable.is_file():
        print(f"ci_core_smoke: packaged executable not found: {executable}")
        return 1

    with tempfile.TemporaryDirectory(prefix="sofia-ci-core-smoke-") as tmp:
        data_dir = str(Path(tmp) / "core-data")
        environment = {"SOFIA_DATA_DIR": data_dir}
        instance_key = resolve_expected_instance_key(environment=environment)
        store = WindowsClientAttachStore()

        process = subprocess.Popen(
            [str(executable)],
            env={
                **_inherited_environment(),
                "SOFIA_DATA_DIR": data_dir,
                "LLM_MODEL": "ci-smoke-model",
            },
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            record = _wait_for_record(store, instance_key, _ATTACH_TIMEOUT_SECONDS)
            if record is None:
                print("ci_core_smoke: attach record was not published in time")
                return 1

            client = CoreApiClient(
                f"http://{record.host}:{record.port}", record.credential.reveal()
            )
            try:
                client.connect()
                identity = client.get_runtime_identity()
                if identity.get("instance_key") != instance_key:
                    print("ci_core_smoke: runtime identity instance_key mismatch")
                    return 1
                if identity.get("runtime_session_id") != str(record.runtime_session_id):
                    print("ci_core_smoke: runtime identity runtime_session_id mismatch")
                    return 1
                print("ci_core_smoke: attach + authenticated identity verified")

                accepted = client.request_runtime_shutdown(
                    record.runtime_session_id, reason="ci_smoke"
                )
                if not accepted:
                    print("ci_core_smoke: graceful shutdown request was rejected")
                    return 1
            finally:
                client.close()

            exit_code = process.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
            if exit_code != 0:
                print(f"ci_core_smoke: SofiaCore.exe exited with code {exit_code}")
                return 1

            if store.read(instance_key) is not None:
                print("ci_core_smoke: attach record was not cleaned up after shutdown")
                return 1

            print("ci_core_smoke: graceful shutdown and attach cleanup verified")
            return 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def _inherited_environment() -> dict[str, str]:
    return dict(os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
