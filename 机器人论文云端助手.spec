# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[('scripts\\send_daily_robotics_paper.py', 'scripts'), ('FEATURES.md', '.'), ('RELEASING.md', '.'), ('ROADMAP.md', '.'), ('CHANGELOG.md', '.')],
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
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
