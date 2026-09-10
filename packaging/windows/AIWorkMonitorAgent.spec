from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).parents[1]
hidden_imports = collect_submodules("websockets") + ["win32pdh", "pywintypes", "pythoncom"]

analysis = Analysis(
    [str(project_root / "src" / "aiworkmonitor" / "windows_agent.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "pytest", "httpx"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="AIWorkMonitorAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / "packaging" / "windows" / "version_info.txt"),
    icon=str(project_root / "packaging" / "windows" / "app_icon.ico"),
    uac_admin=False,
)
