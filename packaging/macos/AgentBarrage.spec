# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]


a = Analysis(
    [str(ROOT / 'bin' / 'agent-barrage')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='AgentBarrage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AgentBarrage',
)
app = BUNDLE(
    coll,
    name='AgentBarrage.app',
    icon=str(ROOT / 'packaging' / 'macos' / 'AgentBarrage.icns'),
    bundle_identifier='io.github.agentbarrage.AgentBarrage',
    info_plist={'LSUIElement': True, 'NSHighResolutionCapable': True,
                'CFBundleDisplayName': 'AgentBarrage'},
)
