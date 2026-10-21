# 第三方素材与许可

代码本身以 [MIT](LICENSE) 发布。以下是随仓库分发的第三方素材。

## 音效

`assets/sfx/*.mp3`

- 来源：<https://pixabay.com/sound-effects/>
- 许可：[Pixabay Content License](https://pixabay.com/service/license-summary/)
- 允许商用与非商用、修改，无需署名；**不可原样转售/再分发素材本身**。此处登记仅为透明起见。
- 逐条说明见 `assets/sfx/manifest.json`。

## 字体

安装器会下载 **Noto Sans CJK SC Black** 到安装目录 `fonts/`（不随仓库提交）。

- 来源：<https://github.com/notofonts/noto-cjk>
- 许可：SIL Open Font License 1.1
- 逐字体许可记录见 `fonts/licenses/`（字体二进制不进仓库）。

## 可选：sfx-kit

`koubo assets import-sfx-kit` 可导入用户本地克隆的
[sfx-kit](https://github.com/wyzowl/sfx-kit)（CC0）。**不随本仓库分发**，
只读取其 `sounds.json` 元数据并按分类复制/链接用户已下载的文件。

## 运行依赖

`capcut-cli`、`ffmpeg`、`Pillow`、`numpy`、`faster-whisper`、`edge-tts` 等依赖遵循各自许可，本项目不重新分发它们。

## 可选：jianying-tool

`scripts/draft_native.py setup` 会把 [jianying-tool](https://pypi.org/project/jianying-tool/)
（Apache-2.0）装进 `vendor/jytool-venv`，用于解码剪映原生加密草稿与驱动剪映导出。

- 它是**运行期可选依赖**，不随本仓库分发，也没有复制其源码。
- 它通过调用本机安装的剪映所带的 `videoeditor.dll` / `libvideoeditor.dylib` 读写草稿，
  不包含剪映的任何二进制文件；本项目与剪映官方无关。
- 升级/移除：删掉 `vendor/jytool-venv` 即可回到纯明文草稿路径。
