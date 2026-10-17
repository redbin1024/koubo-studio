# 使用文档

本文是给人看的完整操作手册；Agent 的入口在 [SKILL.md](../SKILL.md)。安装与环境自检见 [安装文档](install.md)。

## 目录

1. [工程结构](#工程结构)
2. [建工程与量参考片](#建工程与量参考片)
3. [自动粗剪](#自动粗剪)
4. [字幕](#字幕)
5. [包装与插图](#包装与插图)
6. [声音](#声音)
7. [剪映草稿](#剪映草稿)
8. [质检与交付](#质检与交付)
9. [故事方案与云端视觉分析](#故事方案与云端视觉分析)
10. [环境变量](#环境变量)
11. [常见工作流](#常见工作流)

---

## 工程结构

`koubo new my-video` 会创建：

```text
my-video/
├── config.json          # 一切开关与数值
├── input/
│   ├── captions.srt     # 画面字幕
│   └── clean-cut.mp4    # 粗剪结果（自动生成）
├── work/                # 中间产物：镜头表、样式计划、混音、质检报告
├── output/              # final-*.mp4
├── assets/              # 脚本现画的插图 / 卡片素材
├── draft-store/         # 剪映草稿
└── fonts/               # 可选：工程自带字体
```

关键原则：

- **`config.json` 是唯一配置源。** 所有脚本都通过 `load_config` 补齐默认值。
- **`work/edit-plan.json` 是镜头表的唯一正本。** 改顺序、入点、时长后重跑粗剪，不要手改粗剪视频。
- **`work/` 可重跑，`output/` 是本轮交付。** 渲染凭据会绑定输入文件，旧成片不能冒充本轮结果。

---

## 建工程与量参考片

```bash
koubo new my-video --video ~/Movies/口播.mp4
koubo new my-video --video ~/Movies/口播.mp4 --reference ~/Movies/参考片.mp4
koubo new my-video --clips 1.mp4 2.mp4 --mode vlog
```

- `--video`：单条口播素材，相对路径从 `input/` 找，也可用绝对路径。
- `--clips`：多段素材，先拼接 / 粗剪。
- `--mode talking-head|vlog`：决定默认语音目标（口播 `source`，Vlog `narration`）。
- `--reference`：自动量参考片，并把卡片几何、画中画位置、强调色写进 `config.json`。
- `--aspect 9:16|16:9`：画布比例。

单独量参考片：

```bash
koubo analyze ~/Movies/参考片.mp4 \
  --out my-video/work/reference-teardown.json \
  --frames my-video/work/ref-frames
```

量出来的字段怎么用、哪些量不准，见 [reference-teardown.md](../references/reference-teardown.md)。

> 参考片只用来**取数**，任何一帧都不会进成片。

---

## 自动粗剪

```bash
# 口播：按静音区间选说话段
koubo auto-edit my-video --mode talking-head --clips talk.mov

# Vlog：按画面变化列候选场景，保持素材输入顺序
koubo auto-edit my-video --mode vlog --clips 1.mov 2.mov 3.mov

# 只生成镜头表，不渲染
koubo auto-edit my-video --mode vlog --clips 1.mov --plan-only

# 改完 work/edit-plan.json 后重出粗剪
koubo auto-edit my-video --apply-plan
```

镜头表 `work/edit-plan.json` 里每条 `shots` 支持：

| 字段 | 含义 |
| --- | --- |
| `source` | 源素材路径 |
| `in` | 源素材入点（秒） |
| `duration` | 本段时长（秒） |
| `audio_gain` | 0–2，默认 1；保留现场声或压低车载广播 |
| `transition` | 第二个及后续镜头可写 `"dip"`（120ms 淡黑进出），默认硬切 |
| `caption` | 画面提示文字 |
| `kind` | `speech` / `narration-slot` 等 |

**片长由内容产生，不是固定 29 秒。** 选段、动作完整性和重复内容由人判断；场景检测只生成候选，不能代替语义剪辑。

### 自动字幕（可选）

```bash
# 需要装了 faster-whisper 的环境
.venv/bin/koubo auto-edit my-video --mode talking-head --clips talk.mov --auto-captions
.venv/bin/koubo auto-edit my-video --apply-plan --auto-captions --replace-captions

# 已有逐词 JSON 时直接导入
.venv/bin/koubo auto-edit my-video --transcript /path/to/transcript.json
```

- 已有字幕默认不覆盖；确认替换才加 `--replace-captions`。
- ASR 结果必须人工核对人名、术语、低置信词和分句。
- 无语音或识别失败时，不会悄悄生成假字幕。

### 解说槽

口播也能加**解说**，但解说只落在现场人声的空隙里：

```bash
koubo auto-edit my-video --mode talking-head --clips talk.mp4 --narration-slots 3
# 写 work/narration-lines.json：{"lines": [{"slot": 1, "text": "…"}]}
.venv/bin/koubo tts my-video --probe   # 只试装，报每句装不装得下
.venv/bin/koubo tts my-video           # 出 voice.wav + 时窗 + 旁白字幕
koubo run my-video
```

- 装不下就报错（−5% → +30% 逐档升速试装），不会自动截断半句话。
- 解说文案只能使用素材里已有的信息，写完先给人过目再配音。

---

## 字幕

编辑 `my-video/input/captions.srt`。标准 SRT，额外支持轻量标记：

| 标记 | 作用 |
| --- | --- |
| `[[词]]` | 正向强调色（默认黄） |
| `((词))` | 反差强调色（默认粉） |
| `\|` | 强制换行 |
| `{@样式 layout=… anim=…}` | 写在第一条字幕开头，逐条样式 / 版式 / 入场动效 |
| `{@big}` | 内置大字卡样式 |

内置动效：`fade` / `hook` / `pop` / `rise` / `wipe` / `karaoke`。逐条样式会被算成 `work/style-plan.json`，**mp4 与剪映草稿读同一份**。

```srt
1
00:00:00,000 --> 00:00:02,500
{@hero layout=center anim=pop}
很多人问我

2
00:00:02,600 --> 00:00:06,000
为什么能[[打动]]这么多妈妈

3
00:00:06,100 --> 00:00:08,000
不是华丽的((广告))
```

常用配置：

```jsonc
"captions": {
  "font": "Noto Sans CJK SC Black",
  "size": 90,
  "layout": "bottom",
  "theme": "screen-clean",          // 可选：换字体 + 配色预设
  "styles": { "hero": { "size": 132, "layout": "center", "anim": "pop" } },
  "skip": [7, 8, 9],                // 卡段那几句不烧字幕
  "burn": "layer"                   // layer = Pillow 逐帧画；ass = libass
}
```

**为什么默认不用 libass**：macOS 的 Homebrew libass 只带 CoreText provider，不认 `fontsdir`，工程里放字体也会渲染成方框。默认 `burn = "layer"` 用 Pillow 画，字体跟工程走。

换字体：

```bash
koubo fonts my-video          # 列工程 fonts/ 与安装目录 fonts/
koubo fonts my-video --all    # 连系统字体一起列
```

把 `ttf/otf/ttc` 放进工程 `fonts/`，`captions.font` 写**族名**即可；写错会报错并列出可用族名，不会静默换字体。

---

## 包装与插图

`config.json` 里的包装块：

| 块 | 作用 |
| --- | --- |
| `card` | 信息卡：标题 + 编号条目 + 图标 + 入场动画 |
| `pip` | 画中画：裁切中心、框位、圆角、入场 |
| `gold` | 结尾发光大字 |
| `inserts` | 脚本现画的插图：`band` 横条 / `panel` 整屏 |
| `sfx` | 音效事件（真实采样） |
| `grade` | 调色 / 背景虚化 / 压暗 |
| `segments` | 收尾淡黑 |

插图版式：`icon-label` / `list` / `stat` / `quote`；图标：`check` / `clock` / `bowl` / `leaf` / `heart` / `home` / `star` / `shield`。全部由 Pillow 现画，不引外部图片、不联网找素材。

两条硬规矩：

1. **插图必须有据可依**：由字幕关键词触发，或挂在解说槽上；
2. **插图不得压字幕带**。

`verify.py` 会硬查（`insert-grounded` / `caption-band-clearance` / `insert-rendered`）。

---

## 声音

### 语音目标：交付契约

`config.json` 必须声明 `audio.speech_mode`：

| 值 | 含义 | 出片前检查 |
| --- | --- | --- |
| `source` | 原声口播 | 原声 ASR 检出可信语音 |
| `narration` | 旁白 | `work/voice.wav` 非静音且时长匹配 |
| `mixed` | 现场人声 + 解说 | 解说必须落在解说槽 |
| `none` | 纯音乐 / 无语音片的显式选择 | 不检查 |

**有音轨 ≠ 有语音。** 缺人声时 `run_all` 会在渲染前停止，不会拿 BGM 假充。

### 双轨收音：外录对轨

```bash
# 扫素材目录，判哪条外录配哪条毛片
koubo pick-audio <素材目录>

# 也可以显式写 config
"input": {
  "video": "talk.mp4",
  "audio": "talk_ext.wav",
  "audio_map": { "a.mov": "a.flac" },
  "align": { "enabled": true, "threshold": 0.35 }
}
```

三条纪律：

- **测出 0 比假设 0 更稳。** 已对齐的素材也测。
- **低置信不硬上。** 产一份剪映对齐草稿，人工拖齐后 `python scripts/align_audio.py --resume "<草稿>"`。
- **原始素材全部保留。** 换轨产物只是后续工程的素材。

### 离线 ASR

```bash
# 首次使用先装 faster-whisper
.venv/bin/pip install -r requirements-transcribe.txt

# 生成逐词证据
.venv/bin/koubo transcribe my-video/input/clean-cut.mp4 my-video/work/transcript.json
.venv/bin/koubo script prepare_source_speech.py my-video --transcript my-video/work/transcript.json

# 或让主流程在渲染前自动准备
.venv/bin/koubo run my-video
```

要求至少 3 个置信度 ≥ 0.60 的中文词，可信词时长覆盖至少 8%。不足会报 `no_speech` 或证据不足。

### 逐句听审

含 `audio.voice_cues` 的工程会在完整运行后导出：

```text
work/voice-review/v2-<本轮凭据>/
├── 听审清单.md
├── line-01.mp4
└── ...
```

每句都有最终混音 + 画面。实际看完后登记：

```bash
# 三项都通过
koubo review my-video --line 1 --reviewer "审核人" \
  --semantics pass --voice pass --subtitles pass

# 有 fail 时必须写 --note
koubo review my-video --line 2 --reviewer "审核人" \
  --semantics fail --voice pass --subtitles pass --note "这句和画面对不上"

# 查看汇总
koubo review my-video
```

状态：`awaiting_review` / `changes_requested` / `complete`。**自动检查不能代替人工判断。**

### BGM 与音效

```bash
# 先在 config.json 里打开 BGM
# "audio": { "bgm": { "enabled": true, "mood": "warm" } }

# 本地合成 BGM（零素材、零版权、逐字节可复现）
koubo bgm my-video

# 音效来自 assets/sfx/ 的真实采样
# 事件写在 config.sfx.events，或按故事方案生成
```

`koubo run` 的 `music` 步只在 `audio.bgm.enabled = true` 时插手；关着就跳过，`work/bgm.wav` 存在也不会上混音。想换曲子：把选好的音频放到 `work/bgm.wav` 的位置替换。剪映音乐库是云端内容，capcut-cli 没有音乐接口。

### 响度

`config.audio.loudness` 默认 `I=-14, TP=-2.6, LRA=11`。渲染时先限峰、再复测、按实测校准；质检使用同一测量器。不要把「有声音」当成响度合格。

---

## 剪映草稿

每一轮 `koubo run` 都会出草稿，**不是可选项**：

```text
video  主轨      work/graded.mp4 按镜头表切段
video  包装层    卡段 / 结尾发光字 / 收尾淡黑
audio  人声      粗剪原声（响度归一）
audio  音效      work/sfx-track.wav
audio  旁白      work/voice.wav（存在才上轨）
audio  BGM       work/bgm.wav（存在才上轨）
text   字幕      input/captions.srt（去掉标记，关键词上色）
```

```bash
# 只出草稿，不跑全流程
koubo draft my-video

# 只生成、不装进剪映草稿箱
koubo draft my-video --no-install
```

默认同名覆盖，但**剪映自己动过的同名草稿不覆盖**（加密 / 出现 `Timelines/` 目录）。要保留手改版本就换 `--name`；确认丢弃时加 `--force-install`。

### 剪映原生资源（只进草稿）

```jsonc
"jianying_fx": {
  "enabled": true,
  "namespace": "jianying",
  "effects":     [{ "name": "漏光噪点", "at": 0.0, "dur": 2.2, "intensity": 0.45 }],
  "filters":     [{ "name": "日系奶油", "intensity": 0.32 }],
  "transitions": [{ "at": 21.80, "name": "叠化", "dur": 0.36 }],
  "sfx":         [{ "name": "回音", "at": 8.0, "dur": 0.8, "volume": 0.5 }]
}
```

**这一块只进草稿。** 成片 mp4 是 ffmpeg 渲的，看不到剪映原生滤镜/特效/转场；选它就意味着「成片以剪映导出为准」。资源名可用 `capcut enums --filters --jianying` 等命令查；写错会在写草稿前报出来。

### 混合后端（可选）

需要剪映转场 / 大量滤镜时，可用 `jy_hybrid.py`：

```bash
git clone https://github.com/GuanYixuan/pyJianYingDraft /tmp/jy1
pip install pymediainfo && brew install mediainfo
export KOUBO_JY1=/tmp/jy1
python scripts/jy_hybrid.py my-video --name "片名_混合后端"
```

它是实测等价的后端，但依赖更多；默认后端仍是 `make_jianying_draft.py`。

---

## 质检与交付

```bash
koubo verify my-video
```

结果写到 `work/qc-report.json`，每项三态：

- `pass`：查过且通过；
- `fail`：查过且不通过；
- `unchecked`：**判不了**（缺输入、缺工具、元素未启用），必须写明原因。

**缺席 ≠ 通过。** 报告里消失的检查项会被读成通过，所以 `unchecked` 必须留在报告里。

关键检查项：

| 项 | 查什么 |
| --- | --- |
| `output-exists` | 成片是本轮渲染的，不是旧片 |
| `speech-presence` | 声明的语音目标真的成立 |
| `jianying-draft` / `jianying-installed` | 草稿生成了、也装进了剪映草稿箱 |
| `jianying-fx` | 声明的剪映资源写进草稿了 |
| `narration-slot-fit` / `narration-slot-real` | 解说落在真静音槽里 |
| `voice-caption-cross-overlap` | 画面字幕与旁白字幕不撞车 |
| `measured-constants` | 实测常量没漂移 |
| `insert-*` / `caption-band-clearance` | 插图有据、不压字幕 |

完整跑完 `run_all.py` 后，`pipeline.json` 的 `automation_complete` 表示生成步骤齐全；逐句旁白工程还要看 `status` 是否 `complete`。

---

## 故事方案与云端视觉分析

需要显式开启：

```bash
# 先在当前环境安全地注入 DEEPSEEK_API_KEY，不要写进工程文件
koubo auto-edit my-video --apply-plan --vision --story
```

- `--vision`：每个镜头抽一张 512px 代表帧，上传到 DeepSeek 多模态接口，生成 `work/visual-review.json`。
- `--story`：在视觉分析后只发送文字证据，生成 `work/storyboard.json`（待审核的镜头排序、证据关联旁白、音乐情绪）。
- **不会上传整条视频或素材路径**，但 API 会产生费用。
- 单次最多 24 镜头、每批 8 帧；一个代表帧不能证明完整动作或人物身份。
- API 结果不会直接改正式镜头表、原素材或字幕；故事方案也不会自动执行为旁白/BGM/转场。

审核 `storyboard.json` 后，若 `order` 与当前镜头表一致：

```bash
koubo script story_audio.py my-video --approve-story
koubo script story_effects.py my-video --approve-story
koubo run my-video
```

---

## 环境变量

新名 `KOUBO_*` 优先，旧名 `THSP_*` 仍然兼容。

| 变量 | 作用 |
| --- | --- |
| `KOUBO_FFMPEG` / `KOUBO_FFPROBE` | 指定 ffmpeg / ffprobe |
| `KOUBO_FONTS_DIR` | 给 libass 的 fontsdir |
| `KOUBO_FONT_DIRS` | 额外字体目录，冒号分隔 |
| `KOUBO_EMOJI_FONT` | 指定 emoji 字体 |
| `KOUBO_CAPCUT` | 指定 capcut 可执行文件 |
| `KOUBO_JY_STORE` | 指定剪映草稿箱 |
| `KOUBO_JY1` | pyJianYingDraft 路径（混合后端） |
| `KOUBO_VERBOSE=1` | 打印每条子进程命令 |
| `KOUBO_HOME` | 安装目录 |
| `KOUBO_REPO` / `KOUBO_REF` | 安装源 |
| `KOUBO_PYTHON` | 指定 Python 3.10+ |

---

## 常见工作流

### 只改字幕，重烧一遍

```bash
koubo captions my-video && koubo render my-video
```

### 改参考片风格，重新量

```bash
koubo analyze ~/Movies/新参考片.mp4 \
  --out my-video/work/reference-teardown.json \
  --frames my-video/work/ref-frames
# 按拆解结果更新 config.json
koubo run my-video
```

### 只重出草稿

```bash
koubo draft my-video
koubo verify my-video
```

### 从旧镜头表迁移

```bash
koubo script rebuild_sample.py /path/to/旧样片
# 旧样片需包含：镜头方案.json、旁白时码.json、字幕.srt、旁白字幕.srt、中文旁白.wav、原创节奏BGM.wav
```

### 跳过某些步骤

```bash
koubo run my-video --skip draft,review
koubo run my-video --only render,draft,verify
```

`draft` 被跳过后，`verify` 的 `jianying-draft` / `jianying-installed` 会报红——这是刻意的。

---

更多细节：

- [SKILL.md](../SKILL.md)：Agent 完整工作流与脚本表
- [reference-teardown.md](../references/reference-teardown.md)：参考片拆解字段
- [config-schema.md](../references/config-schema.md)：`config.json` 全字段
- [lessons.md](../references/lessons.md)：踩坑记录
- [registry.md](../references/registry.md)：跨文件规矩的唯一正本
