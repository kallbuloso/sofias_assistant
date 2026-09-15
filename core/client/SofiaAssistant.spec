import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPEC).resolve().parents[1]
source_root = project_root / "src"

hiddenimports = collect_submodules("sofias_assistant.client_app")

# The interpreter's own OpenSSL DLLs must win over any same-named DLL that
# happens to sit earlier on the build machine's PATH (e.g. MySQL Shell, PHP,
# or Git for Windows all ship their own libssl-3-x64.dll/libcrypto-3-x64.dll
# and PyInstaller's dependency walker can pick one of those up instead of
# the one that actually matches this interpreter's _ssl.pyd, producing a
# frozen build that fails with "DLL load failed while importing _ssl" at
# runtime even though the unfrozen app works fine).
_python_dll_dir = Path(sys.base_exec_prefix) / "DLLs"
_pinned_openssl_binaries = [
    (str(_python_dll_dir / name), ".")
    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll")
    if (_python_dll_dir / name).is_file()
]

a = Analysis(
    [str(source_root / "sofias_assistant" / "client_app" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=_pinned_openssl_binaries,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SofiaAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
