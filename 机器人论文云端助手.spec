# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[('scripts\\send_daily_robotics_paper.py', 'scripts'), ('FEATURES.md', '.'), ('RELEASING.md', '.'), ('ROADMAP.md', '.'), ('CHANGELOG.md', '.'), ('RELEASE_NOTES.md', '.')],
    hiddenimports=['_cffi_backend'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='机器人论文云端助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    # Keep one-file extraction beside the app instead of Windows TEMP. Some
    # endpoint-security policies block loading Python DLLs from %TEMP%\_MEI*.
    runtime_tmpdir='.',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
