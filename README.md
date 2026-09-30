# DeskPet

DeskPet 是一款 macOS 桌面宠物，默认角色是原创角色明里。她会在桌面上走动、眨眼，支持拖动、点击互动、聊天和切换皮肤。

已在 Apple 芯片 Mac 上验证。

## 安装

Apple Silicon DMG 安装包在 [Releases 页面](https://github.com/ywainhanayo/DeskPet/releases) 提供下载。打开 DMG 后，将 `DeskPet.app` 拖入“应用程序”文件夹即可。

DMG 已包含 Python 运行环境和所需依赖，安装用户不需要另装 Python。开发者也可以按下面的步骤从源码运行。

## 从源码运行（开发者）

需要 Python 3.11。在仓库目录中执行：

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python main.py
```

打开后可以：

- 拖动桌宠；单击播放动作，双击打开或关闭聊天。
- 右键切换皮肤、导入皮肤包、打开设置或退出。
- 在设置中填写自己的 DeepSeek API key 后使用聊天功能。

## 皮肤

通过右键菜单的“导入皮肤包…”选择 `.petpack` v2 文件。导入后会自动切换，以后也可在“皮肤”菜单中选择。旧版 v1 包不能直接导入。

也可以把图片皮肤放到 `~/Library/Application Support/DeskPet/skins/` 下的独立文件夹，重启后从“皮肤”菜单选择。

## 聊天与本地数据

聊天由 DeepSeek API 提供，需要用户自己的 API key。发送消息时，对话内容会发往 DeepSeek；填写 API key 并设置角色名后，程序会联网获取资料并生成角色设定。

API key 和其他设置保存在本机 `~/Library/Application Support/DeskPet/config.json`。**API key 当前未加密存储**，请在信任的设备上使用。

## 授权与构建

代码和文档采用 [MIT 许可](LICENSE)。明里图片及应用图标另按 [素材使用规则](ARTWORK_LICENSE.md) 授权，不能直接按 MIT 处理。

应用内第三方组件的许可见 [第三方声明](THIRD_PARTY_NOTICES.md)。

开发者可参阅 [构建说明](packaging/README.md)。本仓库不包含其他角色皮肤包；DMG 下载以 Releases 页面实际发布的文件为准。
