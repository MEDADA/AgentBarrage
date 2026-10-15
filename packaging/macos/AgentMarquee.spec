# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]


a = Analysis(
    [str(ROOT / 'bin' / 'agent-marquee')],
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
    name='AgentMarquee',
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
    name='AgentMarquee',
)
app = BUNDLE(
    coll,
    name='AgentMarquee.app',
    icon=str(ROOT / 'packaging' / 'macos' / 'AgentMarquee.icns'),
    bundle_identifier='io.github.agentmarquee.AgentMarquee',
    info_plist={'LSUIElement': True, 'NSHighResolutionCapable': True,
                'CFBundleDisplayName': 'AgentMarquee'},
)
