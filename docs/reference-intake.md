# 抖音参考片入库与拆解

给一条抖音链接（或本机视频），把它变成一份**可复核**的参考片档案：
切点、镜长、字幕带、强调色、卡片/画中画、逐镜三联图、口播转写、全片结构。

```bash
koubo reference "https://v.douyin.com/xxxx/" -p my-video
koubo reference ~/Movies/参考片.mp4 -o work/ref-analysis --no-llm

# 拆完顺手按分析选一款字幕字体（只出建议，不写 config）
koubo reference "https://v.douyin.com/xxxx/" -p my-video --pick-font
```

- 给 `-p/--project`：写到 `<工程>/work/reference/`，并复制一份
  `<工程>/work/reference-profile.json`。
- 不给：写到 `work/reference-intake/`。
- `--json` 只打印 profile 路径，方便 Agent 串下一步。
- `--force` 清掉旧分析重算；不加时按步骤复用已下载的原片和已有结果。

## 它做什么

```text
链接 / 文件
 ├─ 取原片：抖音分享页 SSR 数据 → 失败回退 yt-dlp → 再失败要本地文件
 ├─ 节奏：自适应切点、镜长分布、VFR、LUFS
 ├─ 视觉几何：字幕带、强调色、卡片、画中画、最平的安全带
 ├─ 切镜：切点 + 固定阈值补刀 → 每镜首/中/尾三联图 → 接触表 → ≤15s 分段
 ├─ 口播：本地 faster-whisper 逐词转写 + SRT
 ├─ 拆解：可选 DeepSeek 视觉；每条结论必须引用三联图证据
 └─ 汇总：reference-profile.json + REPORT.md
```

它**不是**「一键复刻」：不生成新视频、不换人、不自动改工程。它只回答
「这条参考片量到了什么、看到什么、哪些没查」。

## 三个来源

| 来源 | 行为 |
| --- | --- |
| 本机文件 | 不复制、不改名，直接分析；推荐先用这个，最稳 |
| 抖音分享链接 | 解析 `v.douyin.com` 短链 → 分享页 SSR；不登录、不批量 |
| `koubo reference` 产出目录 | `auto` / `new` 直接复用其中的 `teardown.json`，不重量 |

抖音分享页第一次请求通常只下发 `ttwid`，第二次才带 `videoInfoRes`，命令内部会自动
重试一次。仍然拿不到时：

1. 加 `--cookie`：可以是浏览器导出的 `cookies.txt`，也可以是 `sessionid=...; ttwid=...`；
2. 装 `yt-dlp` 后重试（`--engine auto` 会自动回退）；
3. 仍然失败就把视频下载到本地，传文件路径。**不猜、不假装成功**。

> 图文作品没有视频轨，会直接报错，不会拿第一张图当视频分析。

## 产物

| 文件 | 内容 |
| --- | --- |
| `source.json` | 平台、引擎、作品 id/作者/标题/音乐/互动数、实际下载地址、告警 |
| `douyin/douyin.mp4` | 链接来源的原片；本地文件不复制 |
| `pacing.json` | 自适应切点、镜长分布、VFR 诊断、响度 |
| `teardown.json` | 字幕带 / 强调色 / 卡片 / 画中画 / flat bands 的原始测量 |
| `shots.json` | 镜头表、三联图时间点、≤15s 分段、接触表路径 |
| `frames/strip-NN.jpg` | 每镜一张「左=切入后 / 中=中点 / 右=切出前」三联图 |
| `frames/shot-NN.jpg` | 中点关键帧 |
| `contact-sheet.jpg` | 所有镜头总览，报告里的主图 |
| `transcript.json` / `.srt` | 逐词证据与生成字幕（装了 `faster-whisper` 时） |
| `breakdown.json` | 全片结构 + 逐镜语义（有 `DEEPSEEK_API_KEY` 时） |
| `reference-profile.json` | 下游稳定契约：来源 / 节奏 / 风格 / 口播 / 镜头 / 建议 / 未检查 |
| `font-selection.json` | 加 `--pick-font` 时的字体建议（不写 config；应用用 `koubo font-pick --apply`） |
| `REPORT.md` | 人看的报告，含镜头表、证据、未检查项 |

## 报告怎么读

- **技术参数**：文件时长 vs 分析时长分开写。抖音下载文件可能比作品元信息长
  （App 追加的黑帧/尾屏），切镜只分析到元信息时长，并写进「未检查」。
- **节奏**：同时给「实际切镜」和「pacing 自适应原始值」。两边不一致时以实际切镜表
  为准，因为固定阈值切点补了自适应漏掉的刀。
- **视觉风格**：强调色、字幕带、卡片、画中画都是像素测量；字体/字号/描边不在其中。
  满屏色块会被当成假的「卡片」，面积超过 55% 会被剔除并写明。
- **字幕带**：只给几何。**不要用 `y_bottom_norm` 反推 `margin_v`**，要用字幕墨迹下沿重算。
- **镜头表**：每镜带三联图链接和证据。`unchecked` 表示没拆解，不是「没问题」。
- **未检查**：没装 ASR、没有 Key、某批拆解失败、字体量不了、音乐没识别、漏检切点没定位，
  都会逐条列出。

## 三态，不是两态

| 状态 | 含义 |
| --- | --- |
| `ok` | 该项有实测证据 |
| `partial` | 整体可用，但部分镜头/批次没拆出来 |
| `unchecked` | 没查，原因写在 `unchecked[]` |

缺席不等于通过。报告里不会因为没配 Key 就少一段，反而会多一条「未检查」。

## 接到全自动 / 建工程

```bash
# 先拆参考片
koubo reference "https://v.douyin.com/xxxx/" -p my-video

# 建工程时直接复用拆解结果（不重量）
koubo new my-video --video ~/Movies/口播.mp4 --reference my-video/work/reference

# 或者让 auto 自己去下载（只取几何，不跑完整拆解）
koubo auto my-video --video ~/Movies/口播.mp4 --reference "https://v.douyin.com/xxxx/"
```

`new` / `auto` 的 `--reference` 现在接受三种值：本地文件、抖音链接、
`koubo reference` 的产出目录。传目录时直接读 `teardown.json`，不再重复抽帧。

## 视觉拆解（可选）

```bash
export DEEPSEEK_API_KEY="..."   # 只放当前环境，不写进工程
koubo reference ~/Movies/参考片.mp4 -o work/ref-analysis
```

- 全片结构 1 次调用 + 每 3 镜一批；默认最多送 30 镜（`--max-shots`）。
- 每条镜头结论必须给出 `evidence`（引用左/中/右格差异），枚举值、镜头 id、
  置信度由代码校验；不合格重试一次，再不合格只把那批标 `unchecked`。
- 模型判断「三联图像不连续机位」时记 `hidden_cut=true`；本项目**没有**做逐帧 SSIM
  定位，切点时间不保证，报告会写明。
- 没有 Key 时用 `--no-llm` 也不丢人：节奏、几何、三联图、接触表仍然可用。

## 程序接口

Agent / 其他脚本可以不用 CLI，直接调用：

```python
import sys
sys.path.insert(0, "scripts")
from reference_intake import run

profile = run("https://v.douyin.com/xxxx/", "work/reference",
              no_asr=True, no_llm=True, log=print)
print(profile["coverage"], profile["unchecked"])
```

只取原片、不做拆解时：

```python
from workflow.reference_source import fetch_reference, prepare_reference

result = fetch_reference("https://v.douyin.com/xxxx/", "work/src")
prepared = prepare_reference("work/reference", "work")  # 复用档案里的 teardown
```

`run()` 返回的就是 `reference-profile.json` 的内容；不会因为有未检查项而抛异常，
只有在**取不到原片**或**参考片读不了**时才抛 `ReferenceSourceError`。
CLI 会把同样的错误打印成非零退出。

## 边界与许可证

- 抖音抓取只做公开单条作品的分享页解析，**不登录、不批量、不抓评论**，
  也没有引入 MediaCrawler（其许可证是 NON-COMMERCIAL LEARNING LICENSE，且需要扫码登录）。
- 只分析你**有权使用**的参考片；参考片任何一帧都不进成片。
- 去水印地址失败时会回退带水印源，`source.json` 里会写明；带水印原片只用于拆解。
- `yt-dlp` 是可选依赖，不装也能用本地文件和分享页。
- 不做：音乐/音效识别、字体识别、OCR 逐字识别、镜头语义的逐帧证明、
  付费 API 的自动重试计费保护（拆解只在显式命令下发生）。

## 常见问题

**Q：抖音分享页返回验证页 / 空数据。**
A：先用浏览器打开链接确认作品还在；再试 `--cookie`（从浏览器导出），或直接下载到本地。
数据中心 IP 比家庭宽带更容易被风控。

**Q：下载下来带水印。**
A：去水印地址可能被限流；看 `source.json.warnings`。拆解不受影响，但不要把它当素材用。

**Q：没有 faster-whisper。**
A：转写会标 `unchecked` 并给安装提示；`pip install faster-whisper` 后加 `--force` 重跑。
首次会下载模型，可用 `--asr-model small` 换更快的。

**Q：镜头数太多，拆解很贵。**
A：`--max-shots 12` 最多送 12 镜（均匀覆盖全片）；或先 `--no-llm` 看接触表，再决定要不要拆语义。

**Q：我只想量几何，不要切镜/转写。**
A：直接 `koubo analyze 参考片.mp4`，那是更轻的旧入口；本模块是「整条参考片档案」。
