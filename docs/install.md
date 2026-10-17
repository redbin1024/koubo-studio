# 安装

口播工坊以「一个安装目录 + 一个 `koubo` 命令 + 三个 Agent skill 软链接」的方式安装。安装器不需要 `sudo`，不会改系统 Python，也不会把字体塞进系统字体目录。

## 一键安装（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/redbin1024/koubo-studio/main/install.sh | bash
```

装完：

```bash
koubo doctor
```

### 安装器做了什么

| 步骤 | 默认行为 | 如何跳过 |
| --- | --- | --- |
| 拉代码 | `git clone --depth 1` 到 `~/.agents/skills/koubo-studio` | `--dir PATH` 换目录 |
| Python | 找 3.10+；没有且装了 Homebrew 时 `brew install python@3.12` | `--no-system` |
| venv | 在安装目录建 `.venv`，装 `numpy` / `Pillow` | `--no-venv` |
| 字体 | 下载 Noto Sans CJK SC Black 到安装目录 `fonts/`（约 17MB） | `--no-font` |
| ffmpeg | macOS 用 `brew install ffmpeg-full`（带 libass） | `--no-system` |
| capcut-cli | 有 Node ≥ 18 时装到 `vendor/npm/`，不污染全局 npm | `--no-capcut` |
| 旁白 | 安装 `edge-tts` | `--no-narration` |
| 离线转写 | **默认不装**；`--full` 或 `--with-whisper` 才装 `faster-whisper` | 默认 |
| 软链接 | `~/.local/bin/koubo`、`~/.agents/skills/…`、Codex / Claude Code 的 skills 目录 | `--no-skill-links` |
| 自检 | 跑 `koubo doctor` | — |

### 常用变体

```bash
# 全量：系统依赖 + faster-whisper + Node
curl -fsSL https://raw.githubusercontent.com/redbin1024/koubo-studio/main/install.sh | bash -s -- --full

# 最小：只装 Python 核心
curl -fsSL https://raw.githubusercontent.com/redbin1024/koubo-studio/main/install.sh | bash -s -- --minimal

# 指定目录
curl -fsSL https://raw.githubusercontent.com/redbin1024/koubo-studio/main/install.sh | bash -s -- --dir ~/tools/koubo-studio

# 先看计划，不动系统
bash install.sh --dry-run
```

从本地 checkout 安装：

```bash
git clone https://github.com/redbin1024/koubo-studio.git
cd koubo-studio
bash install.sh
```

本地安装默认就装回当前 checkout，不会复制到 `~/.agents/skills/`。

## 手动安装

不想跑安装器时：

```bash
git clone https://github.com/redbin1024/koubo-studio.git ~/.agents/skills/koubo-studio
cd ~/.agents/skills/koubo-studio
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-narration.txt     # 可选：解说旁白
.venv/bin/pip install -r requirements-transcribe.txt    # 可选：离线语音转写
mkdir -p ~/.local/bin
ln -s "$PWD/bin/koubo" ~/.local/bin/koubo
koubo doctor
```

手动装字体（二选一）：

```bash
# 项目本地（推荐，不动系统）
mkdir -p fonts
curl -fL https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Black.otf \
  -o fonts/NotoSansCJKsc-Black.otf

# 或 macOS 系统字体
brew install --cask font-noto-sans-cjk-sc
```

## 依赖矩阵

| 依赖 | 版本 | 必需 | 用途 | 缺失时 |
| --- | --- | --- | --- | --- |
| Python | 3.10+ | ✅ | 全部脚本 | 安装器会尝试装 |
| numpy / Pillow | 见 `requirements.txt` | ✅ | 逐帧合成、字幕层、BGM | 渲染失败 |
| ffmpeg / ffprobe | 任意近期版本；libass 可选 | ✅ | 转码、混音、响度、抽帧 | 安装器会尝试装 |
| 中文字体 | Noto Sans CJK SC / 思源黑体等 | ✅ | 字幕、卡片、大字 | 渲染报错（不会静默换字体） |
| capcut-cli + Node | Node ≥ 18；capcut-cli 0.25+ | 出草稿必需 | 装配 / 登记剪映草稿 | mp4 仍可出，`draft` 步骤失败 |
| 剪映桌面版 | macOS | 用草稿必需 | 打开 / 继续编辑 / 导出 | 只能拿 mp4 |
| edge-tts | 见 `requirements-narration.txt` | 可选 | 解说旁白 | 旁白不可用 |
| faster-whisper | 见 `requirements-transcribe.txt` | 可选 | 离线 ASR / 自动字幕 | 手工写字幕 |
| mediainfo + pymediainfo | 可选 | `jy_hybrid.py` 混合后端 | 元数据 | 默认后端不受影响 |

## 平台

| 平台 | 状态 | 说明 |
| --- | --- | --- |
| macOS 12+ Apple Silicon / Intel | ✅ 主要支持 | 剪映草稿箱、`say` 旁白、Homebrew 路径都按 macOS 验证 |
| Linux | ⚠️ 部分支持 | 渲染、字幕、质检、多数脚本可跑；剪映草稿箱不存在，`story_audio` 的 `say` 不可用 |
| Windows | ⚠️ WSL / 自行验证 | 没有原生安装路径；剪映草稿箱与字体路径需自行适配 |

## 装到哪里

| 路径 | 内容 |
| --- | --- |
| `~/.agents/skills/koubo-studio/` | 默认安装目录（代码 + `.venv` + `fonts/` + `vendor/`） |
| `~/.codex/skills/koubo-studio` | Codex 的 skill 软链接（检测到 `~/.codex` 时创建） |
| `~/.claude/skills/koubo-studio` | Claude Code 的 skill 软链接（检测到 `~/.claude` 时创建） |
| `~/.local/bin/koubo` | CLI 软链接 |
| `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/` | 剪映草稿箱（由剪映创建） |

如果 `~/.local/bin` 不在 `PATH`：

```bash
export PATH="$HOME/.local/bin:$PATH"
# 写进 ~/.zshrc 或 ~/.bashrc 可长期生效
```

## 升级

```bash
koubo update            # git pull --ff-only + 更新核心依赖
koubo update --no-deps  # 只拉代码
```

或重跑安装器。安装器对已有 checkout 使用 `git pull --ff-only`，不会覆盖本地修改。

## 卸载

```bash
bash install.sh --uninstall           # 删除软链接，保留安装目录
bash install.sh --uninstall --force   # 连安装目录一起删除
```

手动删除时注意别删到自己的素材工程。

## 排错

### `command not found: koubo`

```bash
export PATH="$HOME/.local/bin:$PATH"
# 或直接跑
~/.agents/skills/koubo-studio/bin/koubo doctor
```

### `koubo doctor` 报字体失败

确认安装目录 `fonts/` 里有 `NotoSansCJKsc-Black.otf`，或把任意中文字体放进去，并在 `config.json` 里把 `captions.font` 写成字体族名：

```bash
koubo fonts my-video --all
```

### ffmpeg 没带 libass

默认字幕走 Pillow 字幕层（`captions.burn = "layer"`），不需要 libass。只有显式改成 `burn = "ass"` 时才需要：

```bash
brew install ffmpeg-full
```

### 剪映草稿箱不存在 / 不可写

1. 安装并至少打开一次剪映；
2. 确认目录存在：`~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft`；
3. 给终端「完全磁盘访问权限」（系统设置 → 隐私与安全性 → 完全磁盘访问权限）；
4. 或设置 `KOUBO_JY_STORE` 指向可写目录。

### capcut-cli 安装失败

安装器使用本地 npm 前缀，避免全局权限问题。仍失败时：

```bash
npm install -g capcut-cli
# 或指定路径
export KOUBO_CAPCUT=/path/to/capcut
```

### 装完 Agent 找不到 skill

确认软链接存在：

```bash
ls -l ~/.agents/skills/koubo-studio ~/.codex/skills/koubo-studio ~/.claude/skills/koubo-studio
```

重启 Agent 客户端，或在对话里明确说「用口播工坊」。

---

更多环境变量见 [使用文档](usage.md#环境变量)。
