# Changelog

## 1.2.4 — 2026-10-19

### 修复

- `pip.enabled = false` 时卡片里仍会绘制画中画：`compose_card` 之前没有判断开关，
  只要 `pip.at` 落在卡段内就会把 PiP 叠上去，甚至压住卡片标题。现在开关为 false
  或 `dur <= 0` 时完全不画。
- 全功能版实剪：卡片 / 发光字 / 3 条插图 / 日系奶油滤镜 / 两处叠化转场 / BGM / 音效 /
  逐镜头主轨，质检 30 过 / 0 红 / 4 没查。

## 1.2.3 — 2026-10-19

### 变更

- **工作流侧重点改为剪映草稿**：剪映草稿是主交付，mp4 降为预览 / 快速发布副本。
- 草稿主轨从「通常一整段」改为**逐镜头帧对齐分段**：粗剪 plan 42.761s 渲出来 42.900s
  时不再退回单段，而是按 30fps 对齐到 8 段，逐镜头可 trim / 排序 / 加转场 / 滤镜 / 关键帧。
- 新增 [docs/draft-first.md](docs/draft-first.md)：草稿里能改什么、哪些仍烘焙在 `graded.mp4`、
  为什么暂不直接挂原始素材。
- 新增主轨帧对齐测试；测试总数 150。

## 1.2.2 — 2026-10-19

### 修复

- 剪映草稿人声轨：从 AAC 源抽出的 WAV 常比视频短 20–40ms，`capcut add-audio` 会拒绝
  「请求时长 > 源时长」；旧代码用 `check=False` 把这个错误静默吞掉，结果是草稿里
  只有 BGM / 音效、没有人声，但日志仍打印“人声 + 音效 + BGM”。
- 现在人声 / 音效 / 旁白 / BGM 一律按源文件实际时长夹取，并强制检查 `add-audio`；
  失败会直接报错，不再产出“看起来有、实际没有”的草稿。
- 新增人声上轨时长回归测试；测试总数 149。

## 1.2.1 — 2026-10-19

### 修复

- 全自动口播切点增加 `lead` / `tail`，避免静音检测把第一个字的前 0.2–0.7s 判成静音，
  导致成片从「人问我」开始而不是「很多人问我」。
- 自动口播把短停顿并成完整句，减少「华/丽」「送/到」「打/咬」这类跨镜头断词。
- 新增切点回归测试；测试总数 148。

## 1.2.0 — 2026-10-19

**在 DeepSeek / Agent 窗口里直接用，不填 API Key**：新增宿主导演模式。

### 新增

- `koubo auto --prepare`：生成候选镜头、ASR 转录、Vlog 代表帧与 `work/host-director-request.json` / `host-director-prompt.md`。
- `koubo auto --resume`：读取 `work/host-director-decision.json` 继续出片；决策仍走与云端模型相同的校验。
- 当前窗口的 DeepSeek / Agent 可以直接读请求、写 decision，用会话自身的推理完成选段/排序/旁白，不需要 `DEEPSEEK_API_KEY`。
- `--decision PATH` 可指定宿主 decision 文件位置。
- 响度二次校准增加动态 loudnorm / 压缩 / volume+limiter 回退，旁白 + BGM 的短素材不再因真峰限制卡死。
- 新增宿主导演校验测试；测试总数 147。

### 边界

- 宿主模式需要 Agent 能读本地文件；Vlog 需要能看图（`work/host-frames/`）。
- 宿主写出的 decision 仍受覆盖率、关键词、旁白长度、镜头锚点等校验；不合格会拒绝继续。
- 这不是“脚本借用聊天窗口登录”：脚本本身不会调用 DeepSeek；推理由当前窗口的模型完成。

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
