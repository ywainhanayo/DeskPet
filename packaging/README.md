# 从源码构建 macOS 应用

本页供希望自行构建 DeskPet 的开发者使用。需要 Apple 芯片 Mac 和 Python 3.11。

在仓库根目录执行：

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements-build.txt
./.venv/bin/pyinstaller --noconfirm \
  --workpath .build/pyinstaller --distpath .build/dist packaging/DeskPet.spec
```

构建结果位于 `.build/dist/DeskPet.app`。若要向其他 Mac 用户分发，请为最终应用另行完成签名、公证和安装测试。
