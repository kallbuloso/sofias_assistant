"""Real Windows integration coverage for named mutex instance ownership."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sofias_assistant.runtime.instance_ownership import CoreInstanceOwnership


@pytest.mark.integration
@pytest.mark.skipif(os.name != "nt", reason="requires Win32 named mutexes")
def test_windows_mutex_excludes_same_store_until_released(tmp_path: Path) -> None:
    data_dir = tmp_path / "mutex-store"
    first = CoreInstanceOwnership(data_dir)
    first.acquire()
    try:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys\n"
                    "from pathlib import Path\n"
                    "from sofias_assistant.runtime.instance_ownership import (\n"
                    "    CoreAlreadyRunningError, CoreInstanceOwnership,\n"
                    ")\n"
                    "ownership = CoreInstanceOwnership(Path(sys.argv[1]))\n"
                    "try:\n"
                    "    ownership.acquire()\n"
                    "except CoreAlreadyRunningError:\n"
                    "    raise SystemExit(0)\n"
                    "raise SystemExit(1)\n"
                ),
                str(data_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode == 0, probe.stderr
    finally:
        first.release()

    third = CoreInstanceOwnership(data_dir)
    third.acquire()
    third.release()
