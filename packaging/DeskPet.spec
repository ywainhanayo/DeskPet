# -*- mode: python ; coding: utf-8 -*-

import os

signing_identity = os.environ.get('DESKPET_CODESIGN_IDENTITY') or None
entitlements_file = os.environ.get('DESKPET_ENTITLEMENTS_FILE') or None


a = Analysis(
    ['../main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../sprites', 'sprites'),
        ('../LICENSE', 'licenses/DeskPet'),
        ('../ARTWORK_LICENSE.md', 'licenses/DeskPet'),
        ('../THIRD_PARTY_NOTICES.md', 'licenses'),
        ('licenses', 'licenses/third-party'),
    ],
    hiddenimports=['objc', 'AppKit'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtPdf'],
    noarchive=False,
    optimize=0,
)

# The widget application does not use a software keyboard or PDF image decoding.
# Remove their plugins and frameworks pulled in by Qt's generic collection hook.
def unused_qt_component(entry):
    name = entry[0].lower()
    return ('qtvirtualkeyboard' in name or 'qtpdf' in name
            or name.endswith('/libqpdf.dylib'))

a.binaries = [entry for entry in a.binaries if not unused_qt_component(entry)]
a.datas = [entry for entry in a.datas if not unused_qt_component(entry)]
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
        'CFBundleShortVersionString': '0.2.1',
        'CFBundleVersion': '4',
    },
)
