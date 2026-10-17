# Changelog

## 1.1.0 — 2026-10-17

**全自动成片**：新增 `koubo auto`，一条命令从原始素材出 mp4 + 剪映草稿。

### 新增

- `scripts/auto_film.py`（`koubo auto`）：建工程 → 候选镜头 → 导演决策 → 粗剪 → 字幕 → 原声/旁白 → BGM/音效 → 渲染 → 草稿 → 质检 → 自动修复。
- `workflow/auto_director.py`：口播选段/排序/关键词高亮/音乐情绪；Vlog 复用视觉分析与故事方案。模型输出全部过校验，失败回退本地规则。
- `workflow/auto_voice.py`：无声素材自动旁白（edge-tts），逐句时窗、旁白字幕与 `voice-cues.json`；装不下跳过而不是截断。
- `run_all.py --auto`：跳过人工听审门禁，`pipeline.json` 记为 `automated`；需要复核仍可单独跑 `export_voice_review.py`。
- 自动质检修复循环：BGM 填静音、字幕标点/重叠、插图/卡片关闭、响度目标调整、草稿/渲染重试等。
- 空画面字幕支持：只有旁白字幕的 Vlog 也能生成合法空 ASS，草稿跳过空的字幕轨。
- 响度二次校准回退：`normalize_final_audio` 在带 offset 的线性校准不达标时，自动尝试无 offset 与确定性 volume+limiter。
- 安装器默认安装 `faster-whisper`（`--no-whisper` / `--minimal` 可跳过），为全自动口播路径准备 ASR。
- 新测试：导演校验与回退、自动旁白、自动修复、空字幕；测试总数 145。

### 变更

- `faster-whisper` 从“可选”变为推荐能力；模型仍首次运行时下载，默认 `small`，可用 `--asr-model large-v3`。
- README 增加全自动入口与能力边界；新增 [docs/auto.md](docs/auto.md)。

### 已知限制

- 口播自动选段依赖 ASR 质量；Vlog 的旁白与故事线依赖 DeepSeek API，缺 Key 时回退本地保序 + BGM。
- 自动模式默认不做信息卡/画中画/插图（这些需要内容支撑）；参考片只取字幕几何与配色。
- 质检仍是三态：自动修复只覆盖常见红项，`unchecked` 项仍会留在报告里。

## 1.0.0 — 2026-10-17

首个公开发布版本，项目由 `talking-head-style-pack` 更名为 **口播工坊 / Koubo Studio**。

### 新增

- 一键安装器 `install.sh`：安装目录、venv、字体、capcut-cli、Agent skill 软链接与环境自检。
- `koubo` CLI：`new` / `run` / `doctor` / `auto-edit` / `draft` / `verify` 等脚本别名。
- `scripts/doctor.py`：python、ffmpeg、字体、剪映草稿箱、可选模型逐项自检。
- `KOUBO_*` 环境变量；旧 `THSP_*` 继续兼容。
- 安装目录 `fonts/` 作为字体查找路径，一键安装的字体不必写进系统字体目录。
- 公开文档：安装、使用、架构、capcut-cli 笔记与贡献指南。

### 变更

- 项目名、Skill 名、Agent 元数据统一为 Koubo Studio。
- `.gitignore` 排除本地剪辑工程、素材、成片、剪映草稿与内部草稿。
- 示例与文档脱敏；移除对本地样片工程的依赖。
- `check_measured.py` 的基准配置改为仓库内 `examples/baseline/config.json`。

### 保留

- 参考片量化、自动粗剪、字幕/包装、旁白/BGM/音效、剪映草稿、三态质检等既有能力。
- 128 项回归测试。

### 已知限制

- 仍不是语义理解的全自动剪辑，镜头、文案、旁白与最终听审需要人。
- 剪映原生特效只进草稿，不进 mp4。
- 剪映草稿箱与 `say` 旁白以 macOS 为主；Linux 部分支持，Windows 需自行验证。
