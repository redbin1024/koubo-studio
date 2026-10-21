# 工作流与模块地图

## 先纠正一件事：当前成片不是 SVG 插画

4105 和接送当前用的是：

| 位置 | 4105 | 接送 |
| --- | --- | --- |
| 卡片三行 | 无插图，细线图标 | 无 |
| CTA / 信息条 | 真实静帧 `stills/clean-19.0.jpg` | 真实静帧 `stills/clean-9.2.jpg` / `clean-20.8.jpg` |

SVG 模块仍然存在，但**当前成片没有用它**：

- `assets/illustrations/*.svg`
- `render_svg.py`（SVG → 透明 PNG）
- `render_illustrations.py`（读 config 引用，批量渲染）
- `assets/illustrations/manifest.json`（tier/focus/license）

它现在的定位是 **vector 概念图**，只在 config 的 `illustration` 指向 `illustrations/*.png` 时启用。
真实静帧由 `extract_still.py` 从 `input/clean-cut.mp4` 抽，优先用于护理/环境/证据。

> 原因：80px 小图窗里 SVG 细节活不下来；真实静帧更可信，也不需要伪造。

## 一轮流水线

```text
new_project / auto_film
  → align → merge → narrate/voice → captions
  → assets → sfx → music → beats → preflight → frames → render
  → draft → asset-audit → visual-review → verify → review-outputs → review
```

| 步骤 | 入口 | 实现 | 什么时候用 |
| --- | --- | --- | --- |
| 建工程 | `new_project.py` | `_common` | 新素材、新比例、新参考 |
| 全自动编排 | `auto_film.py` | `auto_director` / `auto_voice` | 没有人工粗剪，想一键出候选 |
| 对轨 | `align_audio.py` | — | 双轨收音，先换外录 |
| 粗剪 | `merge_cut.py` | `edit_plan` / `pacing` | 按镜头表切 `clean-cut.mp4` |
| 解说槽 | `tts.py` / `auto_voice.py` | `narration` / `speech_policy` | 口播+解说，或无声素材自动旁白 |
| 字幕 | `make_captions.py` | `caption_plan` / `caption_layer` | 所有项目；mp4 与草稿共用样式计划 |
| 包装素材 | `make_assets.py` | `caption_plan` | 玻璃卡、图窗、CTA、贴纸 |
| 素材库 | `asset_library.py` / `workflow/asset_library.py` | `asset_licenses` | 登记、检索、稳定引用、授权台账 |
| 素材 audit | `run_all` 的 `asset-audit` | `workflow/asset_library.py` | 工程用量 → `work/asset-manifest.json` + `output/asset-licenses.csv` |
| 真实静帧 | `extract_still.py` | `PIL` | 有 clean-cut，要真实护理/环境图 |
| SVG 插画 | `render_illustrations.py`、`render_svg.py` | Playwright | 没有实拍、只需要概念/章节图 |
| 动效 overlay | `render_motion.py` | Playwright + ffmpeg | HTML/Canvas → ProRes 4444 alpha |
| 音效 | `make_sfx.py` | `assets/sfx` | 需要落点音效 |
| BGM | `make_bgm.py` / `music_library.py` / `mixkit.py` | 合成 / 剪映曲库 / Mixkit | 零版权床垫、剪映选曲或 Mixkit 免费音乐 |
| 逐帧合成 | `build_frames.py` | `caption_layer` / `advanced_fx` / `broll` | 卡片、字幕、调色、模糊底 |
| 成片 | `render.py` | `loudness` | 混音、响度归一、烧字幕 |
| 剪映草稿 | `make_jianying_draft.py` | `draft_spec` / `jy_hybrid` | 每轮必出；可继续手改 |
| 原生草稿 | `draft_native.py` | `workflow/draft_native` + jianying-tool 桥 | 剪映保存过（加密）的草稿：读 / 同步副本 / 诊断 / 导出 |
| 视觉审查 | `make_visual_review.py` | `visual_contract` | 包装 beat 多、需要人眼复核 |
| 质检 | `verify.py` | `draft_audit` / `delivery` | 每轮；三态 pass/fail/unchecked |
| 听审 | `review_voice.py` / `export_voice_review.py` | `voice_review` | 有旁白时逐句听 |

## 模块分层

### 1. 编排 / CLI

| 模块 | 作用 |
| --- | --- |
| `run_all.py` | 固定步骤顺序执行，失败不跳过 verify |
| `auto_film.py` | 候选、导演、ASR、自动旁白、自动修复 |
| `koubo.py` | 子命令别名入口 |
| `doctor.py` | 环境/ffmpeg/字体/依赖自检 |

### 2. 镜头与结构

| 模块 | 什么时候用 |
| --- | --- |
| `auto_edit.py` / `edit_plan.py` | 从素材生成镜头表 |
| `workflow/pacing.py` | 自适应切点、节奏分析 |
| `workflow/auto_director.py` | 多段候选排序/高亮/故事 |
| `workflow/storyboard.py` / `storyboard.py` | 分镜草案 |
| `workflow/reference_source.py` / `reference_shots.py` / `reference_vision.py` | 参考片入库、切镜、视觉拆解 |
| `style_match.py` | 按字幕/镜头表命中固定风格，只出改编建议 |

### 3. 字幕 / 文字

| 模块 | 什么时候用 |
| --- | --- |
| `make_captions.py` | 生成 SRT/ASS |
| `auto_captions.py` | ASR 后写 SRT |
| `workflow/caption_plan.py` | 正本：逐条样式、卡段、skip、强调词 |
| `caption_layer.py` | Pillow 逐帧画字幕（mp4 默认） |
| `workflow/caption_roles.py` | 检查包装文字是否复述底部字幕 |
| `tts.py` / `workflow/auto_voice.py` | edge-tts 旁白、逐句装槽 |
| `font_pick.py` / `workflow/font_picker.py` | 按参考片/工程选字幕字体 |
| `workflow/emfont.py` | emfont 在线字体子集 |
| `workflow/style_lock.py` | 固定风格锁定/漂移检查 |

### 4. 视觉包装

| 模块 | 什么时候用 |
| --- | --- |
| `make_assets.py` | 卡片、行、图标、CTA、插图窗口 |
| `build_frames.py` | 卡片入场、逐行揭示、叠卡、字幕层 |
| `workflow/broll.py` | B-roll 画面/素材替换 |
| `workflow/advanced_fx.py` | 镜头关键帧/蒙版/混合 |
| `workflow/overlay_fx.py` | overlay 关键帧 |
| `workflow/visual_contract.py` | 包装 beat 合同 |
| `workflow/visual_analysis.py` | 静帧/构图分析 |
| `make_visual_review.py` | 接触表、视觉审查包 |

### 5. 素材库

| 模块 | 什么时候用 |
| --- | --- |
| `asset_library.py` | `koubo assets`：init/scan/add/search/verify/audit/suggest/remote |
| `workflow/asset_library.py` | 注册表、sidecar、检索、核验、用量台账、召回建议 |
| `workflow/asset_licenses.py` | 许可目录、三态判据、字体许可记录 |
| `workflow/asset_remote.py` | Pexels/Pixabay 单条检索/下载 + sfx-kit 导入 |
| `mixkit.py` | 搜索/下载 Mixkit 视频/音乐/音效，可写 B-roll/BGM；下载写 sidecar |

### 6. 音频

| 模块 | 什么时候用 |
| --- | --- |
| `align_audio.py` | 外录对轨 |
| `prepare_source_speech.py` | 原声证据/语音就绪 |
| `pick_audio.py` | 从素材里挑可用原声 |
| `make_sfx.py` | 音效轨 |
| `make_bgm.py` | 本地合成 BGM |
| `music_library.py` | 扫描剪映 music_id、选曲、下载 BGM |
| `audio_beats.py` | 口播/promo 真重音 → `work/beats.json` |
| `workflow/preflight.py` | frames 前校验卡片/插图/B-roll/转场/BGM |
| `preflight.py` | frames 前预检，可单独运行 |
| `cleanup_workspace.py` | 工作区清理清单；`--apply-cache` 只删可再生缓存 |
| `failure_bundle.py` | 失败时保存配置/QC/日志/接触表 |
| `workflow/loudness.py` | 响度/真峰归一 |
| `review_voice.py` / `export_voice_review.py` | 逐句听审 |

### 7. 交付 / 质检

| 模块 | 什么时候用 |
| --- | --- |
| `make_jianying_draft.py` | 生成可编辑剪映草稿；每轮必出 |
| `workflow/draft_spec.py` | 先写规格，再执行 |
| `workflow/draft_audit.py` | 草稿对账 |
| `workflow/delivery.py` | 渲染凭据/草稿/听审一致性 |
| `verify.py` | 三态质检；不能把 unchecked 说成 pass |
| `package_video.py` | 交付打包 |

## 当前 4105 实际选择

```text
字幕：Pillow caption_layer（Songti）
卡片：make_assets 玻璃卡 + 细线图标
插图：无 SVG；CTA 用真实静帧
卡段：12.63–24.30，skip [5,6,7]，无底部字幕
音频：voice_volume 2.2 / bgm_volume 0.12 / -13 LUFS
草稿：文字轨 9 条；字体受 JianYing 11.6 加密限制，保持默认
```

## 当前接送实际选择

```text
字幕：Pillow caption_layer（Noto Black）
插图：真实静帧（上车照护/床边照护）
卡片：无玻璃卡
音频：voice_volume 2.2 / bgm_volume 0.10 / -13 LUFS
```
