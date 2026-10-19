---
name: koubo-studio
description: 口播 / Vlog 的可审核智能剪辑工作流：既支持 `koubo auto` 一条命令全自动成片（量参考片风格、ASR 字幕、自动旁白、BGM/音效、mp4 + 剪映草稿、质检自动修复），也支持逐步手工控制；本地规则打底，DeepSeek 可选。用户给出参考视频说「按这个风格剪一遍」「换一个风格再剪一遍」，或要求口播 / Vlog 自动成片、加字幕、信息卡、画中画、旁白、剪映草稿时使用。
metadata:
  short-description: 口播 / Vlog 的量片、粗剪、字幕、包装、剪映草稿与全自动成片
---

# 口播工坊 · Koubo Studio

把真人口播 / 多段 Vlog 做成「像某个参考片那样」、并且**能继续改**的成片。核心动作只有一句：
**先量，再抄。**

凭肉眼对着网格线猜几何会差 30%，所以永远先跑 `analyze_reference.py` 把参考片量成数值，
再把这些数值写进 `config.json`。参考片只用来**取数**，任何一帧都不进成片。

> 下面的命令默认在仓库根目录执行。装好后也可以用 `koubo <别名>`（`koubo --help` 看全部），
> 或在任意目录用 `~/.agents/skills/koubo-studio/bin/koubo`。环境自检：`koubo doctor`。
> 一键安装：`curl -fsSL https://raw.githubusercontent.com/redbin1024/koubo-studio/main/install.sh | bash`。

## 先判断：全自动还是分步

用户要的是「一条命令直接出片」时，**先用全自动入口**：

```bash
# 单条口播；自动判断口播/场景模式
python scripts/auto_film.py PROJECT --video talk.mp4
# 或
koubo auto PROJECT --video talk.mp4

# 多段 Vlog
koubo auto PROJECT --clips a.mov b.mov c.mov
```

全自动会：探测素材 → 候选镜头 →（有 `DEEPSEEK_API_KEY` 时）导演选段/排序/高亮/音乐 →
粗剪 → ASR 字幕 / 原声证据 → 无声素材自动旁白 → BGM/音效 → 渲染 → 剪映草稿 → 质检 →
按红项自动修复。没有 Key 时本地保序全选，Vlog 不自动写旁白；**模型输出全部过校验，
失败回退本地结果**。决策与回退见 `work/auto-decisions.json` / `work/auto-report.json`。
完整说明见 [docs/auto.md](docs/auto.md)。

**没有 `DEEPSEEK_API_KEY`、但你就在 DeepSeek / Agent 窗口里**：你自己当导演，不需要 Key：

```bash
koubo auto PROJECT --video talk.mp4 --prepare
# 读 work/host-director-request.json、work/host-director-prompt.md
# （Vlog 还看 work/host-frames/），把决策写到 work/host-director-decision.json
koubo auto PROJECT --video talk.mp4 --resume
```

`--prepare` 不做云端调用；`--resume` 用你自己的推理结果继续，decision 仍走同一套校验。

用户要求逐项控制、改镜头表、改包装或只要某一阶段时，用下面的分步流程。

## 开工硬闸：先看有没有外录（单轨/双轨）

**无论用户提没提外录音频，动手之前都要扫一遍素材目录。** 真实口播几乎都是**双轨收音**：
相机内录只是参考声，领夹麦/录音笔的外录才是成片要用的。漏了这一步 = 整条片子用错声。

```bash
python scripts/pick_audio.py <素材目录>          # 判哪条外录配哪条毛片
```

它给的是**证据不是结论**：每条候选都真跑一次互相关，报实测置信度。判定三档：

| 判定 | 含义 | 怎么办 |
|---|---|---|
| `use` | 唯一强候选且置信度达标 | 直接用，但**要说一句你用了哪条** |
| `ask` | 多个像的 / 置信度不够 | **问用户**，把候选和置信度一起给他 |
| `reject` | 时长离谱 / 是 BGM / 置信度低到底 | 别用 |

**不要只看文件名配对** —— 文件名只是排序依据，定案的是实测置信度。

然后写进 config，跑流水线时 `align` 步骤会自动换轨：

```jsonc
"input": {
  "video": "talk.mp4", "audio": "talk_ext.wav",          // 单条素材
  "clips": ["a.mov", "b.mov"],
  "audio_map": { "a.mov": "a.flac", "b.mov": "b.flac" }, // 多条素材逐条配
  "align": { "enabled": true, "threshold": 0.35 }
}
```

三条纪律：

- **测出 0 比假设 0 更稳。** 已对齐的素材也照样测 —— 万一其实没对齐，「假设 0」会**静默错轨**。
- **低置信不硬上。** 置信度不足时不自动换轨，改产一份**剪映对齐草稿**（画面 + 外录两条轨），
  你在时间线上拖着对齐（有波形有预览，比任何抽听都直观），保存后：
  `python scripts/align_audio.py --resume "<草稿>"`。**没换 ≠ 换好了**，报告里会如实登记。
- **原始素材全部保留**，是内录保底轨；外录爆音/断录随时回退。换轨产物是后续工程的素材，**别删**。

**没配外录就是单轨** —— `align` 步骤零动作，整条链路和以前逐字一致。

**闭环在剪辑软件里**：对轨效果（唇音同步）最终以你眼睛看到的为准，不以脚本的置信度为准。

## 两条房规（默认值，不要改）

**正本是 `scripts/_common.py` 的 `HOUSE_RULES`**，所有脚本共用；`SKILL.md` 和
`config-schema.md` 里写的是**说明**，不是第二份定义：

- **字幕与画面文案去掉标点**。竖屏快读时 `，。！？` 是噪音，不是信息。只在用户明确要求保留时才改 `captions.strip_punctuation`。
- **不做开头封面、不做片尾卡、不做常驻标题**。第一帧就是正片，最后一句说完就收（结尾只留 0.4s 快速淡黑）。参考片里那种「无片尾卡，但末尾快速淡黑」的观感就是照这个来的。

`verify.py` 会把这两条当硬性检查项跑，破了会出现在 `work/qc-report.json` 里。

> 跨文件的规矩都登记在 [references/registry.md](references/registry.md)：
> **一条规矩只有一个正本**，别处只写「见正本 X」。这份表还记着已经漂移过的事故
> （标点表曾经两份、20 vs 43 字符）。新立一条跨文件规矩时去那儿加一行。

## 实测常量有保质期

「先量再抄」量出来的数字**不是永久的**。`references/measured.json` 是它们的登记表，
每条记「值 / 量于何时 / 拿什么量的 / 怎么量的 / 什么时候该重量」：

```bash
python scripts/check_measured.py                    # 值还和登记表一致吗（verify 里也跑）
python scripts/recalibrate.py ~/Downloads/demo_02.mp4   # 拿参考片重量一遍
```

**改任何一个实测值（字号、描边、margin_v、强调色、响应系数），都要同步登记表** ——
不然下一次没人知道该重量什么。`verify.py` 的 `measured-constants` 一项会在漂移时报红。

`measured.json` 里 `provenance: null` 的条目是**出处待补**（当前 3 条 `CARD_*`）——
不是「没问题」，是「没人记得当初对着什么量的」。

**覆盖率的实话**：17 条里只有 3 条能自动重量（字幕墨迹底 + 两个强调色）。
其余的要在本项目自己的产物上量（`local:*`），或只能人工（字号/描边/阴影）。
`recalibrate.py` 会把量不了的**逐条列出来**，不假装通过。

⚠️ **别用 `analyze_reference.py` 的 `caption_band.y_bottom_norm` 反推 `margin_v`** ——
它走亮带检测，会被画面底部亮区带跑（实测 0.9873，反推只有 24）。要用字幕**墨迹下沿**。

## 质检是三态，不是两态

`verify.py` 每一项落成 `pass` / `fail` / **`unchecked`** 三种之一。**缺席 ≠ 通过**：

- 判不了的项（缺输入、缺工具、元素没启用）必须以 `unchecked` 出现在报告里，并写清为什么，
  **不许从报告里消失** —— 消失的检查项会被读成「通过」，那是把「不可判」说成「安全」。
- `verify.py` 末尾会打一行「有 N 项没查，**不等于通过**」，看到就去看那几项为什么没查。
- 同理「不可判」也不能说成「有问题」：那会让人去修一个可能不存在的毛病。

## 流程

**片长由内容产生。** 29 秒仅是早期样片镜头方案的结果，不是工作流目标或上限。
先审素材中的有效事件、完整语句/动作和重复内容，再定镜头入出点与顺序；最终片长
从镜头表与实际粗剪得出。Vlog 场景检测只生成完整候选段，不能代替语义选段。
不能把所有镜头机械截成同样长度，也不能通过旧 `config.duration` 截断新素材。
用户明确要求平台长度时，重新调整选段与叙事，再更新配音、字幕和包装。

1. **建工程**。`python scripts/new_project.py DIR --video in.mp4 [--reference ref.mp4]`。
   给了 `--reference` 就会自动量片并把卡片几何、画中画位置、强调色写进 `config.json`。
   多段素材要拼接时用 `--clips a.mp4 b.mp4`。
2. **量参考片**（如果第 1 步没给，或想重新量）：
   `python scripts/analyze_reference.py REF.mp4 --out work/reference-teardown.json --frames work/ref-frames`。
   读 [references/reference-teardown.md](references/reference-teardown.md) 理解每个字段怎么用、哪些量不准。
3. **写 `config.json`**。字段全表见 [references/config-schema.md](references/config-schema.md)，
   成品样例见 [examples/config.example.json](examples/config.example.json)。
4. **写字幕** `input/captions.srt`。用轻量标记表达设计意图，不要在 config 里再维护一份行号映射表：
   - `[[词]]` → 正向强调色（参考片里的黄）
   - `((词))` → 反差强调色（参考片里的粉）
   - `|` → 强制换行
   - `{@样式 layout=… anim=…}` 写在**该条第一行开头** → 逐条样式与入场动效
     （`@` 后是 `captions.styles` 里的名字，内置 `default` / `big`；写错直接报错）
   卡段的几句写进 `captions.skip`，那一屏的卡片本身就是放大的字幕，再烧一遍会打架。
   逐条样式会被算成 `work/style-plan.json`：**mp4 与剪映草稿读同一份**，不各推一遍。
5. **跑**：`python scripts/run_all.py DIR`（或分步跑，见下）。
6. **看片**。抽几帧人眼复核，别只看质检报告：
   `python scripts/analyze_reference.py` 的 `--frames` 同样能用来抽成片帧做比对。
   有 `audio.voice_cues` 的工程还要打开 `work/voice-review/latest/听审清单.md`，
   逐句播放最终混音与画面，核对文案、镜头语义和字幕遮挡；清单初始状态为待人工确认。
   实际听审后用 `python3 scripts/review_voice.py DIR --line 1 --reviewer "实际审核人"
   --semantics pass --voice pass --subtitles pass` 逐句登记；未通过项填写 `fail` 和 `--note`。
   未完成判读时不得代填通过。记录绑定本轮渲染与样张，复审追加历史；用
   `python3 scripts/review_voice.py DIR` 查看汇总。完整流水线在待审时记录
   `awaiting_review`，有问题时记录 `changes_requested`，全部句子通过才记 `complete`。
7. **出剪映草稿**。`run_all.py` 里质检**之前**那一步，**每轮必出，不是可选项**：
   `python scripts/make_jianying_draft.py DIR`。
   mp4 是交付件，草稿是能继续改的工程 —— 两条都出了这一轮才算跑完。
   草稿默认同名覆盖（要留手改版本就换 `--name`），并自动装进剪映草稿箱。
   **这条不靠自觉**：`verify.py` 有 `jianying-draft` / `jianying-installed` 两项检查，
   `--skip draft` 或没装进草稿箱都会在 `work/qc-report.json` 里报红。

## 脚本

| 脚本 | 作用 |
| --- | --- |
| `auto_film.py` | **全自动**：素材 → 候选镜头 → 导演决策 → 粗剪 / 字幕 / 旁白 / 包装 → mp4 + 草稿 → 质检修复 |
| `analyze_reference.py` | 量参考片：切点 / 强调色 / 卡片几何 / 画中画 / 字幕带 |
| `check_measured.py` | 校验实测常量还和登记表一致（防漂移，已接进 verify 第 19 项） |
| `recalibrate.py` | 拿参考片把实测常量重量一遍，报与登记表的差异 |
| `list_fonts.py` | 列出可用字体族名（中英文）与 `captions.font` 该写什么 |
| `pick_audio.py` | 扫素材目录，判哪条外录配哪条毛片（实测置信度，不靠文件名猜） |
| `align_audio.py` | 外录对轨：测偏移 + 置信度；高置信换轨、低置信产剪映对齐草稿 |
| `speech_rate.py` | 量旁白语速（净说话 / 段挂钟 / 全片铺开）与反查字数预算 |
| `merge_cut.py` | 可选粗剪：按静音切点把多段素材拼成一条锁定时间轴的口播片 |
| `tts.py` | 解说旁白：`work/narration-lines.json` 文案装槽 → TTS → `voice.wav` + 逐句时窗 + 旁白字幕（口播加解说走这条，见下） |
| `make_captions.py` | SRT → ASS：去标点、关键词换色、首句 hook、字号自适应 |
| `caption_layer.py` | 字幕层：用 Pillow 逐帧画字幕（默认烧法，见下「字幕为什么不走 libass」） |
| `make_assets.py` | 生成信息卡素材（卡底 / 标题 / 条目 / 图标 / 结尾发光大字） |
| `make_sfx.py` | 音效轨：真实采样、按峰值对齐、低频高通 |
| `build_frames.py` | 逐帧合成包装层（卡段 + 画中画 + 发光字 + 收尾淡黑） |
| `render.py` | 烧字幕 + 混音 + 响度归一 → `output/final-*.mp4` |
| `verify.py` | 质检：规格 + 房规 + 风格是否真的落地 → `work/qc-report.json` |
| `jy_hybrid.py` | **可选**混合后端：jy1 写内容 + 本模块补关键词变色 + capcut-cli 补交付层 |
| `make_jianying_draft.py` | 装配剪映草稿：主轨 / 包装层 / 人声 / 音效 /（旁白 / BGM）/ 字幕，装进剪映草稿箱 |
| `run_all.py` | 串起全流程（align 最先跑），`--only` / `--skip` 控制步骤 |
| `rebuild_sample.py` | 把旧镜头表 / 已审核音轨的样片导入标准工程，再调用完整流水线 |
| `export_voice_review.py` | 从本轮成片导出逐句带声画的旁白听审短片和镜头来源清单 |
| `review_voice.py` | 登记逐句人工判读、审核人和问题说明；保留复审历史并刷新本轮验收状态 |

分步重跑很常见（改完字幕只想重烧一遍）：

```bash
python scripts/make_captions.py DIR && python scripts/render.py DIR
```

## 剪映草稿（每轮必出）

成片是压平的 mp4，改一个字要重跑整条流水线；草稿是能继续编辑的工程。所以**两条都出**：

| 轨道 | 内容 | 可改 |
| --- | --- | --- |
| video `video` | `work/graded.mp4` 按 `edit-plan.json` 或粗剪记录切开的 n 段（无有效镜头表就一整段） | 切点、顺序、速度、调色 |
| video `包装层` | `work/body-anim-silent.mp4` 里包装真正出现的时间窗（卡段 / 结尾发光字 / 收尾淡黑） | 位置、时长 |
| audio `人声` | 粗剪片的原声（已做响度归一），音量取 `audio.voice_volume` | 音量、裁剪 |
| audio `音效` | `work/sfx-track.wav`，音量取 `audio.sfx_volume` | 单个音效的落点、音量 |
| audio `旁白` | `work/voice.wav`（**可选**，文件在才上轨），音量取 `audio.narration_volume` | 逐句裁剪、换音色 |
| audio `BGM` | `work/bgm.wav`（**可选**，文件在才上轨），音量取 `audio.bgm_volume`，带淡入淡出 | 音量、裁剪、整轨换曲 |
| text `字幕` | `input/captions.srt`（去掉标记与 `{@…}` 指令、`|` 变真换行），关键词按 `[[ ]]`/`(( ))` 上色 | 文案、位置、动画 |
| video `包装层` 里的插图 | `assets/insert-*.png`（脚本现画，烘进包装层） | 位置、时长（要改字得回头改 `inserts.items` 重出素材） |

**卡段与发光大字是烘在「包装层」里的**，要改那两块的字得回头改 `config.json` 重出包装层，
不能在剪映里直接改字 —— 这是刻意的：那两块是构图，不是字幕。

### 旁白与 BGM（可选的两条干轨）

素材本身没人声时（跟拍、空镜、Vlog），片子的声音只有现场声会很空。补两条干轨：

| 缺什么 | 谁来做 | 产物 |
| --- | --- | --- |
| 解说 / 口播 | `tools/make_voiceover.py`（edge-tts 神经音色，逐句控速装槽） | `work/voice.wav` |
| 背景音乐 | `tools/make_bgm.py`（本机合成，零素材零版权） | `work/bgm.wav` |

两条都**只是 work/ 下的文件**：`render.py` 和 `make_jianying_draft.py` 都是「文件在就上轨，
不在就跟以前一模一样」，所以老工程不用改一个字。旁白一走，现场声和 BGM 都会做**侧链闪避**
（`audio.duck`），人声才站得住。两个脚本是 `scripts/tts.py` 与 `scripts/make_bgm.py`，
用法见 [examples/](examples/) 和 [使用文档](docs/usage.md)。

**音量别靠耳朵定，按空隙/说话段分别量 RMS。** 定档方法和踩过的坑见
[references/lessons.md](references/lessons.md) #24。

草稿默认同名覆盖（工程内的 `draft-store/<name>/` 加剪映草稿箱里的那份）。唯一的例外：
**剪映自己动过的同名草稿不覆盖**（6.0+ 的 `draft_meta_info.json` 被加密，或目录里出现
`Timelines/`）—— 那里面可能是用户在剪映里手改的版本，脚本只提示、换名或确认丢弃时加
`--force-install`（config 里写 `jianying.force_install: true` 则每轮都覆盖）。

**来源标记**：装配时会调用 `stamp_jianying_platform()` 把草稿的 `platform` 改成
`{"app_source": "lv", "os": "mac"}`。种子模板来自 CapCut 国际版，留着 `cc` 会让剪映按
CapCut 的命名空间解析特效/动画，字幕动画会**全部「加载失败」**。改回 `lv` 才认得出来。

两个踩过的坑（脚本里已经绕开，手改草稿时注意）：

- **`add-video` 不要传 duration**。传了会把素材时长写成「这一段的时长」，随后 `trim` 出的
  in-point 就越界，剪映会把入点夹回 0——每个片段都从文件开头开始播。
- **剪映不会按画布宽度折行**。字幕要在写入前折好：脚本用一次小 DP 折行，
  行宽上限 9 字，且尽量不切开带色关键词（`JY_MAX_CHARS`）。

## 解说旁白：口播也能叠解说（`mixed`）

口播的现场人声不换，另配一条解说轨 —— 但**解说只落在现场人声的空隙里**。
空隙不是补出来的静音，是粗剪时从原素材真实静音里留出来的「解说槽」：

```bash
python3 scripts/auto_edit.py my-video --mode talking-head --clips talk.mp4 --narration-slots 3
# 写 work/narration-lines.json：{"lines": [{"slot": 1, "text": "…"}]}
../.venv/bin/python scripts/tts.py my-video --probe   # 真的合成一遍，报每句装不装得下
../.venv/bin/python scripts/tts.py my-video           # 出 voice.wav + 时窗 + 旁白字幕
python3 scripts/run_all.py my-video                   # narrate → voice → 全链
```

- **文案只能用素材里已有的信息**，不新增原片没有的事实；写完先给用户过目再配音。
- **装不下就报错**（`−5% → +30%` 逐档升速试装，再不行就停），脚本不替你截断半句话。
- 四条质检：`narration-slot-fit`（落在槽里没有）、`narration-slot-real`（槽是不是真静音）、
  `voice-caption-cross-overlap`（画面字幕与旁白字幕合起来会不会撞车）、
  `long-silence`（已声明的槽不算空场，排除几段会写在 detail 里）。
- 解说槽也是图形段落点：`inserts.items[].trigger` 写 `{"slot": N}` 就能让插图与旁白同起同落。

## 插图画面：全部由脚本现画

`inserts` 把「额外画面」做成**脚本绘制**的图形，不引外部图片、不联网找素材：

| 版式 | 落点 | 用来做什么 |
|---|---|---|
| `band` | 字幕带上方的横条（默认 `box`） | 关键词卡：图标 + 标题 + 一行说明 |
| `panel` | 整屏（底画压暗） | 图形段：与解说槽同起同落，画面交给图形 |

四种 `kind`：`icon-label` / `list` / `stat` / `quote`；图标是几何图形现画
（`check/clock/bowl/leaf/heart/home/star/shield`），字体走 `captions.font` 同一个 family。

**两条硬规矩**：插图必须有据可依 —— 要么由字幕关键词触发（触发词得真在那条字幕里），
要么挂在解说槽上（那一槽得有解说）；框位下沿不许越过字幕带上沿。两条都由
`verify.py` 复查（`insert-grounded` / `caption-band-clearance` / `insert-rendered`）。

## 特效与字幕：先选型，再动手

剪映的素材库和你自己的合成能力是两回事，落点也不同。一笔效果加在哪，先想清楚：

| | 自己绘制 | 剪映原生 |
| --- | --- | --- |
| 特效 | `make_assets.py` / `build_frames.py` 逐帧合成 | `add-effect` / `add-filter` / `transition` / `mask` |
| 字幕 | `make_captions.py` 出 ASS，`render.py` 烧进画面 | 草稿里的真字幕对象 / `bubble-text` / `text-style` |
| 落在 | 成片 mp4 | 剪映草稿 |
| 换来 | 和参考片逐帧对齐、完全可控 | 用户能在剪映里接着改，蹭得到整个素材库 |

**成片是 ffmpeg + Pillow 压平的，剪映不参与渲染。** 所以剪映原生特效和字幕**只存在于草稿里**，
不会出现在交付的 mp4 上 —— 这是刻意的分工，不是缺陷：mp4 交付成品，草稿交付「可继续改」。

**该走剪映原生的**：一眼看得出是素材库的东西（光效、故障、噪点、漏光、颜色滤镜、转场），
拿 Pillow 复刻既费劲又不像；以及希望用户接着调的东西（字幕入场动画、气泡、背景框、关键词高亮）。

**仍要自己绘制的**：参考片的招牌构图（信息卡、画中画、发光大字）—— 那些是构图不是特效，
要和量出来的几何逐帧对齐，剪映特效给不了；任何需要进 mp4 的东西；卡段那几句
（`captions.skip`，那屏的字幕就是卡片本身，别再挂一层剪映字幕）。

### 资源从哪来

`capcut enums` 才是资源清单，别照着 `--help` 里那几个举例用（`add-effect` 只列了 7 个，实际远不止）：

| 命名空间 | 场景特效 | 人物特效 | 滤镜 | 转场 | 文字入场 | 音效 |
| --- | --- | --- | --- | --- | --- | --- |
| CapCut（默认） | 345 | 95 | 10 | 116 | 76 | 15 |
| 剪映 `--jianying` | 912 | 227 | 468 | 362 | 144 | 43 |

数量差一倍多，**但别拿 slug 数量判断能不能用**（本仓在这里栽过一次）：`findEnum` 除了 slug
还匹配 **member**，而每条都有 member —— 中文名就是 member。

- `add-effect` / `add-filter`：名字或 `--resource-id` 都行，另有 `--intensity 0-1`
  （草稿里记在材质的 `value` 字段，不是 `intensity`）。
- `transition` / `add-sfx`：**按 member 名 + `--jianying` 就能用** —— 实测
  `capcut transition <草稿> <片段id> 上移 --jianying`、`capcut add-sfx <草稿> 回音 … --jianying` 都成功。
  剪映转场 362 条里没有 slug，但 `上移`/`叠化` 这类 member 名直接可写。
- 唯一的坑：`add-sfx` 的资源是**音效效果**（回音/低保真/8bit 这类处理器），不是「音效素材」；
  剪映的**音乐库没有任何接口**，`add-audio` 只收本地文件 —— 要换曲子只能把文件放进来。

两个前提：剪映本地得缓存过那个资源（没下载过，草稿里就是个空壳，打开时在线拉取）；
`lint` 对这类 id 会报 `unknown-effect-slug`，那是 info 级，不影响退出码。
`--full` 别用：实测它按「草稿时长」算，写出了 2× 片长的滤镜段（81.47s / 40.93s），
时间轴当场对不上；显式给起止。

### 把剪映资源写进草稿（`jianying_fx`）

配置里声明，草稿那一步落盘，`verify.py` 的 `jianying-fx` 对账：

```jsonc
"jianying_fx": {
  "enabled": true, "namespace": "jianying",      // 剪映资源库；CapCut 用 "capcut"
  "effects":     [{"name": "漏光噪点", "at": 0.0, "dur": 2.2, "intensity": 0.45}],
  "filters":     [{"name": "日系奶油", "intensity": 0.32}],   // dur 不写 = 覆盖全片
  "transitions": [{"at": 21.80, "name": "叠化", "dur": 0.36}], // at = 主轨切点
  "sfx":         []                                          // 音效效果，不是音效素材
}
```

- 资源名直接抄 `capcut enums --filters --jianying` / `--scene-effects` / `--transitions` /
  `--audio-effects`；写错会在写草稿**之前**报出来（`resolve_fx` 先全解一遍）。
- **这一块只进草稿**。交付的 mp4 是 ffmpeg 渲的，看不到剪映原生滤镜/特效/转场。
  所以选它就意味着**成片以剪映导出为准**（草稿是交付件，mp4 是预览）。
- `verify` 只能证明「声明的东西写进草稿了」；资源能不能在剪映里解析，得打开草稿看一眼
  （离线或没缓存时会显示缺失）。报告里这句话是明写的。

### 草稿里的字幕轨

现在走 `import-srt`。关键词上色（`text-ranges`）和出入场动画（`text-anim`）已经有了，
但 capcut-cli 把 `import-srt` 标为 "mimicry" —— 它拆出来是一堆**独立文本段**，
剪映不认它是一条字幕轨。要往这条轨上加原生能力（气泡 `bubble-text`、背景框描边 `text-style`、
样式复用 `--preset` 配 `make-preset`），得先换成 `caption`：那条产出**真正的剪映字幕轨对象**，
而 `--script input/captions.srt` 正好接上这个 skill 的现成优势 —— whisper 只负责词级时间，
文案用你写好的 SRT（人名、术语不会被听错），`--highlight-words` 还能把手工算的 `[[ ]]`
区间换成声明式关键词表。**这条路还没接进脚本**，要换得改 `make_jianying_draft.py`。

## 剪映草稿：两个后端

默认后端是 `make_jianying_draft.py`（全程 capcut-cli）。另有一条**实测等价**的混合后端
`jy_hybrid.py`：**pyJianYingDraft 写内容 + 本模块补关键词变色 + capcut-cli 补交付层**。

**为什么会有两条**：capcut-cli 的剪映命名空间里**转场 362 条一条都用不了**（`transition` 只收
slug，而它们全没 slug），滤镜 468、字体 335；pyJianYingDraft 带 **4548 条带 resource_id 的枚举**
（转场 453 / 滤镜 1052 / 字体 798），拿来即用。所以**要转场和滤镜时走混合后端，不要时用默认的**。

混合后端在一个 58 秒双轨 Vlog 工程上验证过**与默认后端等价**：7 条轨、24 条字幕、33 个样式段、
**关键词区间与颜色逐字节一致**，`capcut lint` 零问题。实测依据见
[references/lessons.md](references/lessons.md) #30。

```bash
export KOUBO_JY1=~/path/to/pyJianYingDraft    # 或放在 /tmp/jy1
pip install pymediainfo && brew install mediainfo
python scripts/jy_hybrid.py PROJECT_DIR --name "片名_混合后端"
```

⚠️ **装之前先 ⌘Q 退出剪映** —— 它运行时会用内存里的草稿列表回写 `root_meta_info.json`，
可能把新登记的条目冲掉。没登记上就加 `--no-install` 只生成，或事后重跑。

## 写旁白：先算字数，再写字

素材没人声时要补一条旁白。**动笔前先用语速把「多少字」算出来**，别写完才发现塞不下 ——
塞不下的后果是脚本自动升速，语气全变。

```bash
python scripts/speech_rate.py --plan 60 --coverage 0.5    # 60s 片子、旁白占一半 → 多少字
python scripts/speech_rate.py PROJECT_DIR --archive       # 跑完量实际语速，存进数值正本
```

三个口径别混（**混用是这类估算出错的唯一原因**）：

| 口径 | 回答什么 |
|---|---|
| 净说话语速 | 嘴动起来有多快（本机 edge-tts 实测 319 字/分钟） |
| 旁白段挂钟语速 | 一段连续旁白占多少秒（154 字/分钟） |
| **全片铺开语速** | **一条 N 秒的片子该写多少字** —— 写稿用这个 |

关键在「留白」：本仓实测一条 Vlog 的旁白只占片长 **47%**，剩下给了 BGM 和现场声。
**这是设计不是偷懒** —— 句句铺满会喘不过气。所以 60s 的片子：
占 47% ≈ 150 字、占 75% ≈ 240 字、占 95% ≈ 300 字。

配音跑完 `scripts/tts.py` 会**零成本回校**一次实际语速：偏差 > 15% 会在交付里点名。
但**不会自动改稿、不会自动重跑 TTS** —— 改稿要重跑全链时码、重花一次合成，返工与否你定。

方法与五项档案格式见 [references/speech-rate.md](references/speech-rate.md)，
数值正本是 `references/speech-rate.json`（逐片追加）。

## 音效

`assets/sfx/` 里是 9 个真实采样（Pixabay Content License，可商用免署名），
按情绪场景从 [references/style-recipes.md](references/style-recipes.md) 的 cue 表里挑。

**结构重音默认用 `impact-bass-2` + `whoosh-cinematic` 叠层，不要用 `impact-bass-1`。**
`impact-bass-1` 是干砸，整条片子连砸几次观感很廉价；`impact-bass-2` 带一小段预示性
swell，落点更靠前，更像成片。重音只留给真正的结构切点（开场 hook、切卡、切回真人），
其余落点交给 `pop` / `click-soft` / `chime` / `ping`。

## 环境

- `ffmpeg`（macOS 建议 `brew install ffmpeg-full`。默认字幕走 Pillow 字幕层，不依赖 libass；
  只有 `captions.burn = "ass"` 才需要带 libass 的构建）
- `python3` + `numpy` + `Pillow`（一键安装会建 `.venv`）
- 一个中文字体（Noto Sans CJK / 思源黑体）；macOS 上装到 `~/Library/Fonts`。
  **换字体不用装系统**：把 `ttf/otf` 丢进工程的 `fonts/` 目录，`captions.font`
  写**族名**即可（也认 `KOUBO_FONT_DIRS` 环境变量）。找字体的顺序是
  工程 `fonts/` → 安装目录 `fonts/` → `KOUBO_FONT_DIRS` → 系统字体目录，
  **第一个命中的目录就定案**（工程字体永远压过系统里的同族）。
  字幕、卡片、金色大字**共用同一个 family**：`match_font(family, "Bold"/"Medium")`
  只在本族里找字重，族里只有单一字重就全用它，别让卡面混进别的家族的字。
  换字体后字号由 `caption_layer` 实测自动收缩，不用手算。

  **族名中英文都认**（`阿里妈妈数黑体` 和 `Alimama ShuHeiTi` 是同一个字体）：
  中文名是从字体文件的 name 表里读出来的，不靠文件名猜 —— 文件叫
  `阿里妈妈数黑体.ttf` 也照样能用英文名找到。**写错名字直接报错**并列出可用族名，
  不会静默换一个字体、渲出来「看着一样」。不知道能写什么：

  ```bash
  python3 scripts/list_fonts.py PROJECT_DIR          # 工程 fonts/ 里的
  python3 scripts/list_fonts.py PROJECT_DIR --all    # 连系统字体一起列
  ```

  它把「族名 / 字重 / 中文名 / `captions.font` 该写什么」列成一张表，抄最后一列即可。
  指到一款没有汉字的字体会在解析时打 ⚠（中文字幕会变豆腐块）。
- **`capcut`（capcut-cli，`npm install -g capcut-cli`）+ Node ≥ 18**：出剪映草稿用。
  草稿默认写到工程内 `draft-store/`，再复制+登记进剪映草稿箱
  （`~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft`，可用 `KOUBO_JY_STORE` 覆盖）。
  只建草稿不装进剪映：`make_jianying_draft.py DIR --no-install`。
- 可用环境变量覆盖：`KOUBO_FFMPEG` / `KOUBO_FFPROBE` / `KOUBO_FONTS_DIR` / `KOUBO_FONT_DIRS` / `KOUBO_EMOJI_FONT` / `KOUBO_CAPCUT` / `KOUBO_JY_STORE` / `KOUBO_JY1` / `KOUBO_VERBOSE=1`。
  旧名 `THSP_*` 仍然兼容，但新配置请写 `KOUBO_*`。

## 字幕为什么不走 libass

字幕默认由 `caption_layer.py` 用 Pillow 画进画面（`captions.burn = "layer"`），不走
ffmpeg 的 `subtitles` 滤镜。原因是 macOS 上 Homebrew 的 libass **只带 CoreText provider，
而 CoreText provider 不支持 `fontsdir`** —— 它只认系统已安装字体。于是「字体丢进工程
`fonts/` 就能换」这条最该有的能力在 macOS 上直接失效：字体没装进系统，字幕整屏方框
（`analyze_reference.py` 量出来的几何再对也没用）。

自己画的代价是要复刻一遍 ASS 的语义（字号自适应 / 双强调色 / 硬描边 / 明显投影 /
首句 hook 缩放），换来的是：字体跟工程走、和卡片/金色大字同一套字体同一套视觉、
不受系统装没装字体影响。`captions.burn = "ass"` 可以走回老路（Linux 上的 libass
带 fontconfig provider，`fontsdir` 是好用的）。
