# Third party notices

DeskPet source code uses the MIT license. Bundled libraries retain their own licenses. The application includes the license texts from `packaging/licenses/` under `DeskPet.app/Contents/Resources/licenses/third-party/`; DeskPet's code and artwork terms are also included there.

| Component | Version used for this build | License and source |
|---|---|---|
| CPython | 3.11.5 | Python license; [source](https://www.python.org/downloads/release/python-3115/) |
| Qt, PySide6, Shiboken6 | 6.11.1 | LGPL v3 option for the included Qt modules and Python bindings; [Qt source](https://download.qt.io/archive/qt/6.11/6.11.1/submodules/), [bindings source](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.11.1) |
| NumPy | 2.4.6 | BSD and included third party notices; [source](https://github.com/numpy/numpy/tree/v2.4.6) |
| Pillow | 12.3.0 | HPND and included library notices; [source](https://github.com/python-pillow/Pillow/tree/12.3.0) |
| PyObjC Core | 12.2.2 | MIT; [source](https://github.com/ronaldoussoren/pyobjc) |
| PyObjC Cocoa and Quartz bindings | 12.2.1 | MIT; [source](https://github.com/ronaldoussoren/pyobjc) |
| PyInstaller bootloader and runtime hooks | 6.22.3 | GPL with the bootloader exception; runtime hooks use Apache 2.0; [license and source](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3) |
| OpenSSL | 3.0.10 | Apache 2.0; [source](https://github.com/openssl/openssl/tree/openssl-3.0.10) |
| libffi | 3.4.4 | MIT; [source](https://github.com/libffi/libffi/tree/v3.4.4) |
| ncurses | 6.4 | MIT-style license; [source](https://invisible-island.net/ncurses/) |
| zlib | 1.2.13 | zlib license; [source](https://github.com/madler/zlib/tree/v1.2.13) |
| bzip2 | 1.0.8 | bzip2 license; [source](https://sourceware.org/bzip2/) |

Qt contains additional third party code. Its module-specific notices and source references are listed in [Qt licenses and attributions](https://doc.qt.io/qt-6.11/licenses-used-in-qt.html). Qt for Python's additional notices are listed in [its license documentation](https://doc.qt.io/qtforpython-6/licenses.html). The FreeType project is used by bundled dependencies; its license and notices are included with Pillow.

Qt frameworks and the Python bindings are dynamically loaded from the application's `Contents/Frameworks/` and `Contents/Resources/` directories. DeskPet's MIT license does not restrict modifying the application to use modified versions of its LGPL libraries, or reverse engineering it to debug such modifications. A modified macOS bundle may need to be re-signed locally before it can run. The repository provides the application source and PyInstaller specification for rebuilding it with alternative compatible libraries; the upstream links provide the corresponding library source releases.

This build excludes the unused Qt Virtual Keyboard components and PDF image plugin. It does not distribute a commercial Qt license.
