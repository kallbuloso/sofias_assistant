import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPEC).resolve().parents[1]
source_root = project_root / "src"

hiddenimports = collect_submodules("sofias_assistant") + collect_submodules(
    "aiosqlite"
)

# See SofiaAssistant.spec for why the interpreter's own OpenSSL DLLs must win
# over any same-named DLL earlier on the build machine's PATH.
_python_dll_dir = Path(sys.base_exec_prefix) / "DLLs"
_pinned_openssl_binaries = [
    (str(_python_dll_dir / name), ".")
    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll")
    if (_python_dll_dir / name).is_file()
]

a = Analysis(
    [str(source_root / "sofias_assistant" / "host" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=_pinned_openssl_binaries,
    datas=[
        (
            str(source_root / "sofias_assistant" / "persistence" / "migrations"),
            "sofias_assistant/persistence/migrations",
        ),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SofiaCore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No terminal window: packaged human startup must not require or show a
    # console (Desktop/Core Interaction Contract v1 SS53). Diagnostics are
    # served through the authenticated health/runtime-identity API instead
    # of stdout, matching the Desktop's own `console=False` packaging.
    console=False,
)
