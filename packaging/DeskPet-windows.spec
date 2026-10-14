# -*- mode: python ; coding: utf-8 -*-
"""Windows 构建配置。与 macOS 版 DeskPet.spec 同源,差异:
无 BUNDLE/.app、无代码签名参数、图标用 .ico、不含 pyobjc。"""

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
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtPdf'],
    noarchive=False,
    optimize=0,
)

# 桌宠是窗口应用,用不到软件键盘和 PDF 解码,裁掉对应 Qt 插件减小体积。
def unused_qt_component(entry):
    name = entry[0].lower()
    return ('qtvirtualkeyboard' in name or 'qtpdf' in name
            or 'qpdf' in name)

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
    icon='DeskPet.ico',
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
