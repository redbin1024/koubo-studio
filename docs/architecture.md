# 架构说明

口播工坊不是一个大而全的编辑器，而是一组**可单独重跑的命令**，用共享的 `config.json` 和 `work/` 目录串成流水线。

## 目录分层

```text
scripts/
├── *.py                 # 命令入口：argparse、读 config、调用 workflow
├── auto_film.py         # 全自动编排：候选 → 导演 → 粗剪 → 字幕/声音 → 质检修复
├── workflow/            # 可复用实现：镜头表、字幕计划、自动导演、自动旁白、draft-spec、draft-audit、visual-contract、交付凭据
├── _common.py           # ffmpeg/字体定位、默认值、房规、时间码、SRT 解析
└── compat 模块          # edit_plan.py / visual_analysis.py / storyboard.py 只做再导出

references/              # 数值正本、字段说明、踩坑记录、跨文件规矩登记
examples/                # 脱敏示例
tests/                   # 回归测试（176 项）
assets/sfx/              # 可商用真实音效采样
```

**兼容层存在的原因**：早期脚本从 `scripts/edit_plan.py` 等路径导入。拆分实现后保留同名模块再导出，避免外部导入路径失效；新代码一律从 `workflow` 包导入。`tests/test_source_layout.py` 会检查这件事。

## 全自动层

`auto_film.py` 不绕过现有流水线，它在前面加一层“决策”，在后面加一层“修复”：

```text
auto_film.py
 ├── workflow/auto_director.py   本地候选 + 可选 DeepSeek 选段/排序/高亮/故事
 ├── transcribe_audio.py         全片 ASR → 候选文本；粗剪后再识别 → 字幕/原声证据
 ├── workflow/auto_voice.py      无声素材 edge-tts 旁白 + voice-cues + 旁白字幕
 └── run_all.py --auto           沿用字幕/包装/渲染/草稿/质检，只跳过人工听审
```

三条纪律：

- **模型只是建议。** id、时长、关键词、情绪、节拍全部校验；不合法回退本地结果。
- **语音契约不放松。** `source` 仍需原声证据；`narration` 仍需可听旁白与逐句字幕；`none` 是显式回退。
- **自动修复有边界。** 只修确定性红项；修不了的保留 `fail` 并以非零退出，不伪造通过。


## 一轮流水线

`run_all.py` 的步骤顺序是有意排的：

```text
align → merge → narrate → voice → captions → assets → sfx → music
      → frames → render → draft → verify → review
```

| 步骤 | 产物 | 说明 |
| --- | --- | --- |
| `align` | `work/align-report.json`、换轨视频 | 双轨收音先换外录；低置信不硬上 |
| `merge` | `input/clean-cut.mp4`、`work/edit-plan.json` | 按镜头表粗剪 |
| `narrate` / `voice` | `work/voice.wav`、旁白字幕 | 解说只落在解说槽 |
| `captions` | `input/*.ass`、`work/style-plan.json` | 逐条样式计划，mp4 与草稿共用 |
| `assets` | `assets/insert-*.png` | 插图全部脚本现画 |
| `sfx` / `music` | `work/sfx-track.wav`、`work/bgm.wav` | 真实采样 / 本地合成 |
| `frames` | `work/body-anim-silent.mp4`、`work/graded.mp4` | 逐帧合成包装层 |
| `render` | `output/final-*.mp4` | 烧字幕 + 混音 + 响度归一 |
| `draft` | `draft-store/<名字>/`、剪映草稿箱 | 每轮必出，不是可选项 |
| `verify` | `work/qc-report.json` | 三态质检 |
| `review` | `work/voice-review/v2-<凭据>/` | 逐句人工听审样张 |

`draft` 排在 `verify` 之前：草稿没出或没装进剪映，`verify` 的 `jianying-draft` / `jianying-installed` 会直接报红。**「每轮必出剪映草稿」是被质检卡住的，不靠人记得。**

## 数据流

```text
config.json ───────────────┐
input/*.mp4 / *.srt ───────┤
work/edit-plan.json ───────┼──► 各步骤 ──► work/ ──► output/*.mp4
work/style-plan.json ──────┤                   └──► draft-store/
work/voice.wav / bgm.wav ──┘
```

几个关键的单向依赖：

- `new_project.py` 量参考片 → 写 `config.json`；之后 `config.json` 是唯一配置源。
- `auto_edit.py` 写 `edit-plan.json` → 粗剪、包装、字幕、草稿都读它。
- `caption_plan.py` 生成 `style-plan.json` → **mp4 与剪映草稿读同一份**，不各推一遍。
- `delivery.py` 记录渲染凭据 → `verify.py` 用同一凭据判断「成片是不是本轮的」。
- `speech_policy.py` 判断语音是否就绪 → `run_all`、`render`、`verify` 共用同一判据。

## 质检为什么是三态

`verify.py` 的每一项只能是：

- `pass`：查过且通过；
- `fail`：查过且不通过；
- `unchecked`：**判不了**，必须写清原因。

「没查」不能从报告里消失。报告里少一项，读报告的人会默认它通过；把不可判说成安全，比报错更危险。所以 `verify.py` 末尾会打印「有 N 项没查，不等于通过」。

同理，「不可判」也不能说成「有问题」——那会让人去修一个可能并不存在的毛病。

## 交付凭据

`work/render-receipt.json` 绑定本轮输入集合与成片摘要。任一输入变化（配置、字幕、镜头表、音轨、样式计划、插图素材、成片本身），旧凭据都失效，旧成片不能冒充本轮交付。

`verify.py` 的 `handoff` 检查会对比：本轮渲染凭据、草稿摘要、人工听审记录。三者必须指向同一轮，否则报红。

## 跨文件规矩：一个正本

`references/registry.md` 登记了每条跨文件规矩的**唯一正本**与所有副本。典型例子：

- 房规正本在 `scripts/_common.py` 的 `HOUSE_RULES`；
- 标点表正本在 `PUNCT_CHARS`，`verify.py` 直接 import；
- 字幕样式计划正本在 `workflow/caption_plan.py`，mp4 与草稿都只读它。

规矩是：**引用不复制**。副本只写「见正本 X」，不抄数值。曾经因为抄了一份 20 字符的标点表（正本 43 字符），质检「通过」但实际漏查了一半标点——这类事故都记在登记表里。

## 为什么字幕默认不用 libass

macOS 上 Homebrew 的 libass 只带 CoreText provider，而 CoreText provider 不支持 `fontsdir`，只认系统已安装字体。于是「字体丢进工程 `fonts/` 就能换」这条最该有的能力在 macOS 上直接失效。

默认走 `caption_layer.py`：Pillow 逐帧绘制，复刻字号自适应、双强调色、硬描边、投影、首句 hook。代价是要自己维护一套 ASS 语义，换来的是字体跟工程走、和卡片/大字同一套视觉。

`captions.burn = "ass"` 可以走回 libass；Linux 上的 libass 通常带 fontconfig provider，`fontsdir` 是好用的。

## 为什么剪映草稿是必出项

mp4 是压平的交付件：改一个字要重跑整条流水线。
草稿是能继续编辑的工程：切点、顺序、音量、字幕、包装层都能在剪映里改。

两条产物解决的是不同问题，所以不是「有 mp4 就够了」。草稿这一块的取舍：

- **卡段与发光大字烘在「包装层」里**：它们是构图，不是字幕；要改字得回 `config.json` 重出包装层。
- **剪映原生特效 / 滤镜 / 转场只进草稿**：mp4 是 ffmpeg 渲的，剪映不参与渲染；选了这类资源，成片以剪映导出为准。
- **剪映自己动过的草稿不覆盖**：加密或出现 `Timelines/` 时只提示，避免静默覆盖用户手改。

## 扩展点

| 想加什么 | 放哪 |
| --- | --- |
| 新字幕样式 / 动效 | `workflow/caption_plan.py` + `caption_layer.py` + 草稿侧读同一份 |
| 新插图版式 / 图标 | `make_assets.py`（Pillow 现画） |
| 新质检项 | `verify.py`，并在「没成片时也要报告」的名单里登记 |
| 新音效 cue | `make_sfx.py` 的 `CUES`，同步 `references/style-recipes.md` |
| 新 LLM 供应商 | `workflow/visual_analysis.py` 的 transport 层 |
| 新粗剪策略 | `auto_edit.py` + `workflow/edit_plan.py` |

## 测试

```bash
python -m unittest discover -s tests
```

测试覆盖：镜头表、字幕计划与动效、插图触发、旁白槽、语音策略、响度、交付凭据、质检三态、草稿切点、参考片拆解、ASR 规范化、目录兼容层等。测试用 ffmpeg 生成短素材，不依赖任何私有样片。
