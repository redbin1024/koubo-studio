# 剪映操作能力矩阵（Koubo Studio）

这份文件只回答一件事：**某个剪映能力，在当前工作流里到底是自动、只进草稿、还是要人工。**

它不定义风格。风格规则见 `references/styles/`，参数证据见 `references/evidence-registry.md`。

## 状态含义

| 状态 | 含义 |
| --- | --- |
| ✅ 自动 | `make_jianying_draft` 会写进草稿，`draft_audit` 能对账 |
| 📝 只进草稿 | 只存在于剪映工程，mp4 预览不包含；最终以剪映导出为准 |
| 👤 人工 | 当前 CLI 不表达，必须写进交付清单，不能声称已做 |
| ⛔ 不可读 | 剪映加密/版本边界，不要试图绕过 |

## 能力矩阵

| 意图 | 剪映叫法 | 我们的实现 | 状态 | 证据 |
| --- | --- | --- | --- | --- |
| 逐镜头主轨 | 主轨分段 | `graded.mp4` 按镜头表帧对齐切段 | ✅ 自动 | `draft_audit`: `main-segments` / `main-durations` / `main-gaps` |
| 包装层 | 卡段 / 发光字 / 淡黑 | `body-anim-silent.mp4` 时间窗 | ✅ 自动 | `packaging-*` + 包装层轨道 |
| 原声 | 人声轨 | `clean-cut.mp4` 抽 WAV，按源时长上轨 | ✅ 自动 | `audio-voice` |
| 音效 / BGM | 音效轨 / 音乐轨 | `sfx-track.wav` / `bgm.wav` | ✅ 自动 | `audio-sfx` / `audio-bgm` |
| 旁白 | 旁白轨 | `work/voice.wav` + `voice-cues` | ✅ 自动 | `audio-narration`（有旁白时） |
| 字幕 | 文本轨 | SRT → 文本对象；行距 `jianying.line_spacing` | ✅ 自动 | `text-*` + `text-line-spacing` |
| 贴纸 | 贴纸轨 | 本地全画布透明 PNG，独立“贴纸”轨 | 📝 只进草稿 | `stickers`；不是剪映在线贴纸库 |
| 特效 | 特效轨 | `jianying_fx.effects` + 资源名 | 📝 只进草稿 | `native-effect` + 资源报告 |
| 滤镜 | 滤镜轨 | `jianying_fx.filters` + 强度 | 📝 只进草稿 | `native-filter` |
| 转场 | 片段转场 | `jianying_fx.transitions` 挂在主轨切点 | 📝 只进草稿 | `native-transitions` |
| 关键帧 | 参数关键帧 | 未写入草稿 | 👤 人工 | — |
| 蒙版 | 蒙版 | 未写入草稿 | 👤 人工 | — |
| 混合模式 | 混合模式 | 未写入草稿 | 👤 人工 | — |
| 常规变速 / 曲线变速 | 变速 | 未写入草稿 | 👤 人工 | — |
| 在线贴纸库 | 贴纸 | 需要剪映 resource-id，未接 | 👤 人工 | 资源 id 不在公开 API |
| 抠像 / 跟踪 | 智能抠像 / 运动跟踪 | 未接 | 👤 人工 | — |
| 降噪 / 人声分离 / 响度统一 | 音频处理 | 未接 | 👤 人工 | — |
| 导出 | 导出 | 剪映 7+ 无自动导出 | 👤 人工 | 硬约束 |
| 读已有草稿 | — | 剪映加密，不读；走新名字 + 成片分析 | ⛔ 不可读 | 见 `docs/draft-first.md` |

## 交付清单：必须写进 `auto-report.json` / 交付说明

- 剪映里**重新导出**才会包含原生特效/滤镜/转场/贴纸。
- 需要人工确认：滤镜/特效资源是否能加载、贴纸位置、字幕行距、转场是否自然。
- 需要人工做：关键帧、蒙版、混合模式、变速、抠像、跟踪、降噪、人声分离、最终导出。
- **不要**在报告里写“已完成调色/特效/转场”，如果它只是 API 接受但没目视确认；写“已写入草稿，待剪映确认”。

## 与 Edit-Skill 的对应

- EDL/操作/手法/风格四分法：见 `references/edl.md`、`references/techniques/README.md`、`references/styles/`。
- 证据等级：见 `references/evidence-registry.md`。
- 反静默失败：见 `docs/lessons.md` 与 `tests/test_draft_audit.py`。
