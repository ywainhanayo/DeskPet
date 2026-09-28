# -*- mode: python ; coding: utf-8 -*-

import os

signing_identity = os.environ.get('DESKPET_CODESIGN_IDENTITY') or None
entitlements_file = os.environ.get('DESKPET_ENTITLEMENTS_FILE') or None


a = Analysis(
    ['../main.py'],
    pathex=[],
    binaries=[],
    datas=[('../sprites', 'sprites')],
    hiddenimports=['objc', 'AppKit'],
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
    name='DeskPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=signing_identity,
    entitlements_file=entitlements_file,
    icon=['DeskPet-icon.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DeskPet',
)
app = BUNDLE(
    coll,
    name='DeskPet.app',
    icon='DeskPet-icon.png',
    bundle_identifier='com.wanglei.deskpet',
    info_plist={
        'CFBundleDisplayName': 'DeskPet',
        'CFBundleShortVersionString': '0.2.0',
        'CFBundleVersion': '3',
    },
)
