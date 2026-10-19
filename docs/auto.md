# 全自动成片

`koubo auto` 是一条命令的口播 / Vlog 自动成片入口：

```bash
koubo auto my-video --video ~/Movies/口播.mp4
```

产物：

```text
my-video/output/final-1080x1920.mp4     成片 mp4
my-video/draft-store/<名字>/            剪映草稿（同时登记进剪映草稿箱）
my-video/work/qc-report.json            三态质检
my-video/work/auto-decisions.json       导演决策（选段/高亮/情绪/回退原因）
my-video/work/auto-report.json          本轮自动报告（耗时/修复/质检摘要）
```

它**不是把质检关掉**：质检照跑，人工听审不再阻塞；需要复核时仍可跑
`koubo export-review my-video`，再逐句登记。

## 它做了什么

```text
素材
 ├─ 探测尺寸/帧率/音轨、静音切点 / 场景切点
 ├─ 离线 ASR（faster-whisper）得到逐词转录
 ├─ 导演决策
 │   ├─ 口播：本地全选兜底；有 Key 时 DeepSeek 选段/排序/高亮/音乐情绪
 │   └─ Vlog：视觉分析 + 故事方案（排序/旁白/音乐/节拍；不自动删场景）
 ├─ 生成 work/edit-plan.json → 粗剪 input/clean-cut.mp4
 ├─ 重新识别粗剪 → 原声证据 / 画面字幕
 ├─ 无声 Vlog → 自动旁白（edge-tts）+ 旁白字幕 + voice-cues
 ├─ 自动 BGM / 音效 / 轻微调色
 ├─ run_all --auto：字幕层、包装层、渲染、剪映草稿、质检
 └─ 按 qc-report.json 红项做有限次自动修复
```

## 先决条件

| 依赖 | 说明 |
| --- | --- |
| `faster-whisper` | 默认由 `install.sh` 安装；口播路径必需。首次运行下载模型，默认 `small` |
| `edge-tts` | 默认安装；无声素材自动旁白用 |
| `capcut-cli` + 剪映 | 出草稿必需；`koubo auto` 会提前检查 |
| `DEEPSEEK_API_KEY` | 可选。没有 Key 时可用宿主模式（见下），或让口播本地全选成片 |

```bash
export DEEPSEEK_API_KEY="..."     # 只放当前环境，不写进工程文件
```

首次运行模型下载：

```bash
# 更快的默认
koubo auto my-video --video talk.mp4 --asr-model small

# 更准（本机已缓存 large-v3 时推荐）
koubo auto my-video --video talk.mp4 --asr-model large-v3
```

## 常用命令

```bash
# 单条口播（自动判断口播/场景模式）
koubo auto my-video --video ~/Movies/talk.mp4

# 多段 Vlog
koubo auto my-video --clips ~/Movies/a.mov ~/Movies/b.mov ~/Movies/c.mov

# 给参考片：只取字幕几何、配色与版式数值
koubo auto my-video --video talk.mp4 --reference ~/Movies/ref.mp4

# 不调用云端模型
koubo auto my-video --video talk.mp4 --no-llm

# 无声素材也不生成旁白
koubo auto my-video --video broll.mp4 --mode vlog --no-narration

# 重建配置与中间产物（保留 ASR/TTS 缓存）
koubo auto my-video --video talk.mp4 --force
```

### 参数

| 参数 | 作用 |
| --- | --- |
| `--video PATH` | 单条素材 |
| `--clips a b c` | 多段素材（Vlog） |
| `--reference PATH` | 参考片；只抄字幕几何/配色，不抄画面 |
| `--mode auto\|talking-head\|vlog` | 默认 auto：单条有说话段→口播，多段/无音轨→Vlog |
| `--asr-model` | `small`（默认）/ `medium` / `large-v3` |
| `--llm-model` | 默认 `deepseek-flash` |
| `--no-llm` | 不调用云端模型，只用本地规则 |
| `--no-narration` | 无声素材不生成 TTS 旁白 |
| `--max-repairs` | 质检红项最多修复轮数，默认 2 |
| `--prepare` | 只生成候选与宿主导演请求；不做云端调用 |
| `--resume` | 读取宿主 decision 继续；不需要 API Key |
| `--decision PATH` | 宿主 decision 路径（默认 `work/host-director-decision.json`） |
| `--force` | 重建 config，清理可再生的 work/captions/assets |

## 在 DeepSeek 窗口里用，不填 Key

如果你就在 DeepSeek / Agent 窗口里，可以让**当前窗口的模型自己当导演**。
脚本不会借用聊天窗口的登录，也不需要 `DEEPSEEK_API_KEY`；推理由宿主会话完成：

```bash
# 1. 准备：候选镜头 + ASR 转录 + Vlog 代表帧 + 请求文件
koubo auto my-video --video ~/Movies/口播.mp4 --prepare

# 2. 让当前窗口的模型读：
#    my-video/work/host-director-request.json
#    my-video/work/host-director-prompt.md
#    （Vlog 还看 my-video/work/host-frames/*.jpg）
#    把决策写到：
#    my-video/work/host-director-decision.json

# 3. 继续出片
koubo auto my-video --video ~/Movies/口播.mp4 --resume
```

decision 的两种格式：

```jsonc
// 口播
{
  "shots": ["shot_2", "shot_1"],
  "highlights": ["方法", "清单"],
  "music_mood": "calm",
  "beats": [{"shot_id": "shot_2", "cue": "cut"}],
  "notes": "删掉重复开头，把结论前置"
}

// Vlog（order 必须覆盖全部候选，不删场景）
{
  "order": ["shot_1", "shot_2", "shot_3"],
  "narration": [
    {"shot_id": "shot_2", "text": "清晨的光落在窗台上", "evidence": ["shot_2"]}
  ],
  "music_mood": "warm",
  "beats": []
}
```

宿主决策和云端模型走**同一套校验**：未知/重复 id、覆盖率不足、关键词不在转录、
旁白超过 30 字、缺镜头锚点都会拒绝继续，而不是把坏数据写进镜头表。
`--prepare` 会抽 Vlog 代表帧到 `work/host-frames/`，方便当前窗口的多模态模型看图。

## 导演决策怎么回退

全自动的底线是：**模型不可用也要能出片**。

- 没有 `DEEPSEEK_API_KEY` 且不跑宿主模式：口播本地保序全选；Vlog 本地保序 + BGM，不写旁白。
- 宿主写了 decision 但校验不过：直接报错并指出哪一项不合格；不会悄悄降级成另一条片子。
- 模型返回未知镜头 / 重复镜头 / 删掉超过 65% 内容 / 关键词不在转录里 / 非法情绪或节拍：
  校验失败，回退本地结果；回退原因写进 `auto-report.json` 的 `notes`。
- 视觉分析或故事方案失败：Vlog 回退本地保序，不猜旁白。
- ASR 不可用：口播直接报错并给出安装命令；Vlog 可以继续（无原声字幕/旁白）。
- edge-tts 429/网络失败：逐句跳过；全部失败则回退无旁白 + BGM，不伪造静音。

## 声音策略

| 情况 | 结果 |
| --- | --- |
| 粗剪原声有可信中文语音 | `speech_mode=source`，保留原声，画面字幕来自 ASR |
| 无可信人声 + Vlog + 有故事旁白 | `speech_mode=narration`，edge-tts 旁白 + 旁白字幕 |
| 无可信人声 + 口播 | `speech_mode=none`，BGM 填充；没有硬造旁白 |
| 加 `--no-narration` | `speech_mode=none` |

旁白每句的窗口会从该镜头起点延到下一句之前，给 TTS 留时间；**装不下就跳过该句**，
不会截断半句话。具体写在 `work/voice-cues.json` 的 `skipped` 里。

## 自动修复覆盖哪些红项

`verify.py` 仍按 `pass / fail / unchecked` 三态报告。自动修复只动能被确定性修好的：

- `long-silence` / `bgm-present`：打开 BGM；
- `no-punctuation`：清掉画面字幕标点；
- `caption-overlap`：收紧同帧重叠；
- `voice-caption-cross-overlap`：清空画面字幕，只保留旁白字幕；
- `voice-caption-overlap` / `narration-slot-*`：回退无旁白；
- `speech-presence`：回退无语音；
- `jianying-fx` / `insert-*` / 卡片类：关闭对应包装；
- `loudness` / `true-peak`：目标各降 1dB 重渲；
- `duration` / `resolution` / `framerate` / 房规：按当前粗剪与配置回正；
- 草稿/成片缺失：重跑一轮渲染和草稿。

修不了的（例如 capcut 没装、剪映写保护、素材本身无音轨）会在报告里保留红项并退出非零。

## 适合与不适合

**适合**：口播知识/观点/带货，单条或多段跟拍 Vlog，已经有明确素材、想先拿到一版可剪成片。

**Vlog 的边界**：自动模式按场景切点保留全部候选镜头，故事方案只排序、不删镜头；
要删掉重复/废镜头，请在 `work/edit-plan.json` 里改后重跑 `koubo auto` 或手动流程。

**不适合**：需要严格事实核对的新闻、需要逐句人工润色的品牌片、没有 ASR 模型且要求字幕的口播。
自动旁白/故事线是**建议**，发布前仍应看一遍 `work/auto-decisions.json` 和成片。

## 隐私

- 只有显式提供 `DEEPSEEK_API_KEY` 时才调用云端：口播发送候选片段文字；Vlog 发送每个候选镜头的一张 512px 代表帧 + 文字证据。
- 不上传整条视频、原始素材路径或成片。
- 不上传 `work/` 下的报告；它们只在本机。
