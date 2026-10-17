# Changelog

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
