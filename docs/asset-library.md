# 素材库：可检索、可调用、授权清楚

口播剪辑的素材层不是「把文件堆进文件夹」。真到自动化产线，缺的是三件事：

1. **程序能检索**：按类型/标签/情绪/时长/许可召回，而不是靠人翻目录；
2. **程序能稳定调用**：配置里写 ID，不写会随改名失效的路径；
3. **授权边界清楚**：每个素材知道能不能商用、要不要署名、来源在哪、什么时候核对的。

这个模块把三件事落成一个 **JSONL 注册表 + 文件 sidecar + 许可目录 + 三态核验**，
并接进 `preflight` / `run_all` / `verify` / 交付清单。

> 它不是素材下载站。远程源只走公开 API 单条检索/下载；不批量抓取、不绕登录、
> 不把平台素材当自己的素材库再分发。

## 1. 目录

```text
assets/library/
├── registry.jsonl          正本：每条素材一行 JSON
├── licenses.csv            人可读授权台账（由注册表生成）
├── CREDITS.md              署名清单（由注册表生成）
├── audio/bgm/              BGM
├── audio/sfx/              音效（whoosh / click / pop / impact / riser …）
├── video/broll/            B-roll 空镜
├── video/overlays/         转场、光效、纹理
├── graphics/stickers/      贴纸
├── graphics/fonts/         字体二进制（许可记录见 fonts/licenses/）
├── graphics/illustrations/ 插图
├── graphics/stills/        静帧
├── templates/jianying/     剪映草稿模板
└── templates/captions/     花字/字幕条模板
```

素材库根默认是 `assets/library`，可用 `KOUBO_ASSET_LIBRARY=/path` 或工程
`config.assets.library` 覆盖。媒体文件默认被 `.gitignore` 忽略（大文件不进 git），
`registry.jsonl` 可以单独提交；换机器时把媒体放回相同相对路径即可。

随包素材（`assets/sfx`、`assets/illustrations`、`assets/motion`）用
`base: "repo"` 登记，不移动原文件；新入库文件用 `base: "library"`。

## 2. 一条素材记录

```json
{
  "id": "sfx/whoosh-short",
  "kind": "sfx",
  "title": "Short whoosh",
  "base": "repo",
  "path": "assets/sfx/whoosh-short.mp3",
  "sha256": "…",
  "duration": 0.575,
  "tags": ["whoosh", "transition", "swipe", "quick"],
  "mood": ["neutral", "energetic"],
  "scene": ["transition", "ui"],
  "use_for": ["快速滑动", "元素入场", "短转场"],
  "avoid_for": ["长镜头慢移"],
  "sync": {"at": 0.12, "meets": "move-peak"},
  "provider": "pixabay",
  "source_url": null,
  "license": "Pixabay-Content-License",
  "license_checked_at": "2026-10-21",
  "license_snapshot": {"commercial": true, "attribution": "none", "checked_at": "2026-10-21"},
  "bundled": true,
  "notes": "随包真实采样；原始来源 URL 未逐条留存"
}
```

| 字段 | 作用 |
| --- | --- |
| `id` | 调用契约；配置写 `asset:<id>` |
| `kind` | `bgm/sfx/broll/overlay/sticker/font/illustration/still/template/caption` |
| `base` + `path` | `repo`/`library`/`project` + 相对路径，便于换机器 |
| `sha256` | 文件被替换/登记过期时 `verify` 判红 |
| `tags/mood/scene/use_for/avoid_for` | 检索与召回的正本；不是装饰字段 |
| `duration/bpm/energy/sync` | 时长、BPM、能量、对齐点；音效的 `sync.at` 可直接用于落点 |
| `provider/provider_id/source_url/creator` | 来源与可追溯性 |
| `license` | 指向 `workflow/asset_licenses.py` 的许可 key |
| `license_checked_at` | 上次人工核对授权的日期；超过 365 天提示重核 |
| `license_snapshot` | 入库时的许可快照；条款变了能被发现 |

命令 `koubo assets show ID` 会打印解析后的绝对路径与存在性。

## 3. ID、sidecar 与稳定调用

### ID

- 随包素材：`sfx/pop`、`illustration/crib`、`overlay/steam`；
- 内置库：`broll/city-night`、`bgm/mixkit-443`；
- 远程：`broll/pexels-video-123`；
- sfx-kit：`sfx/sfx-kit-whoosh-fast-hard`。

配置里写：

```json
{"broll": {"items": [
  {"cue": 7, "keyword": "放心", "source": "asset:broll/city-night", "dur": 1.8}
]}}
```

`broll.resolve` / `make_sfx.cache_wav` 会解析 `asset:`；文件改名、换目录不影响配置。
普通路径仍然可用（相对 `input/` 或绝对路径），`asset:` 是新代码推荐写法。

### sidecar

每个文件旁边可以有一份 `<file>.asset.json`。工程内素材（`input/broll/`、
`assets/mixkit/`、`work/cloud-music/`）靠 sidecar 随工程走，不依赖共享注册表。

`koubo assets scan` 会优先读 sidecar；没有 sidecar 的新文件登记为
`license=unknown`，等人工补。

## 4. 许可模型

许可目录在 `scripts/workflow/asset_licenses.py`。每条许可记录：

| 字段 | 含义 |
| --- | --- |
| `commercial` | `true` / `false` / `null`（不明） |
| `attribution` | `none` / `optional` / `required`（成片署名） |
| `redistribute` | 能否再分发素材文件本身 |
| `notice_required` | 再分发时是否必须附许可文本/NOTICE |
| `review_required` | 商用前是否必须人工核验官方条款 |
| `notes` | 边界摘要，不是法律意见 |

内置许可包括 CC0 / CC BY / CC BY-SA / CC BY-ND / CC BY-NC / OFL-1.1 /
Apache-2.0 / MIT / BSD-3-Clause / Pixabay / Mixkit / Pexels / 剪映云端 /
项目自有 / 用户提供 / 系统字体 / 未知。

### 三态

和 `verify.py` 一样，只有三种：

- `pass`：当前用途下没有已知障碍；
- `unchecked`：判不了或需人工确认（授权不明、需核对条款、要署名但没导出、
  核验过期、外部素材缺来源 URL、用户提供素材）；
- `fail`：明确不可用（NC 用于商业项目、文件缺失、哈希不符、严格模式下授权未知）。

**`unchecked` 不是通过。** 它必须出现在报告里，不能被静默吞掉。

### 字体

字体记录放 `fonts/licenses/*.json`，每个字体一条：

- Noto Sans CJK / 思源黑体 → OFL-1.1；
- 抖音美好体 DouyinSans → OFL-1.1；
- 得意黑 Smiley Sans → OFL-1.1（保留字体名）；
- 典迹题幕 Monu Titl → OFL 1.1（以发布页为准，`review_required`）；
- 阿里巴巴普惠体 / 阿里妈妈字体 / 站酷字体 → 官方免费商用条款
  （`review_required: true`，脚本不会直接报 pass）。

OFL 的关键区分：**成片使用不需要署名**；**再分发字体文件**必须附 OFL 文本与
版权声明，保留字体名不得用于修改版。`attribution` 与 `notice_required` 分开记录
就是为了这个。

`koubo font-pick` 的候选会带 `license_id/license_url/license_review_required`；
选中的字体如果 `review_required`，`work/font-selection.json` 里会记 `unchecked`。

## 5. 命令

```bash
koubo assets init                    # 建目录 + 登记随包素材
koubo assets scan [--refresh]        # 扫目录；新文件 = 待核
koubo assets add FILE --kind broll --license CC0-1.0 \
  --source-url URL --tags city,night [--project P]
koubo assets search 城市夜景 --kind broll --mood calm
koubo assets show broll/city-night
koubo assets path broll/city-night   # 脚本拿绝对路径
koubo assets set-license ID --license CC-BY-4.0 --checked-at 2026-10-21
koubo assets verify [--strict]       # 文件/哈希/许可
koubo assets export [--out DIR]      # 素材库台账
koubo assets audit PROJECT           # 工程实际用量 → output/asset-licenses.csv
koubo assets suggest PROJECT --cue 7 # 按字幕召回，只出建议
koubo assets stats
```

退出码：`0` = 没有 `fail`（可能仍有 `unchecked`）；`1` = 有 `fail`。

### 入库示例

```bash
# 本地 B-roll，进共享库
koubo assets add ~/Downloads/city-night.mp4 --kind broll \
  --license CC0-1.0 --source-url https://example.com/city-night \
  --tags city,night,street --mood calm --scene city

# 进工程（B-roll 自动放 input/broll/，写 sidecar）
koubo assets add ~/Downloads/tea.mp4 --kind broll \
  --license project-owned --project my-video

# 外部贴纸：贴纸层读 source（图片或 asset:<id>）
# {"stickers": {"items": [{"source": "asset:sticker/heart", "x": .82, "y": .22, "size": .085}]}}
```

`--license` 必填。真的不知道授权时用 `--allow-unknown` 先登记，`verify`
会把它记成 `unchecked`——这是「待核」，不是「可用」。

### 稳定引用

```jsonc
{
  "sfx": {"events": [
    {"t": 10.9, "clip": "asset:sfx/whoosh-short", "peak_db": -22}
  ]},
  "broll": {"items": [
    {"cue": 7, "keyword": "放心", "source": "asset:broll/city-night", "dur": 1.8}
  ]}
}
```

## 6. 素材来源

| 来源 | 类型 | 接入方式 | 许可边界 |
| --- | --- | --- | --- |
| 随包 `assets/sfx` | 音效 | `init` 自动登记 | Pixabay Content License；可商用免署名；不可再分发素材本身 |
| [Mixkit](https://mixkit.co/) | 视频/音乐/音效 | `koubo mixkit`；下载自动写 sidecar | Mixkit Free License；可商用免署名；不可单独转售/再分发 |
| [Pexels](https://www.pexels.com/) | 视频/图片 | `koubo assets remote`，需 `PEXELS_API_KEY` | Pexels License；可商用，署名可选；不可原样转售/再分发；人物/品牌需注意 |
| [Pixabay](https://pixabay.com/) | 视频/图片 | `koubo assets remote`，需 `PIXABAY_API_KEY` | Pixabay Content License；可商用免署名；不可原样转售/再分发 |
| [sfx-kit](https://github.com/wyzowl/sfx-kit) | 320 条音效 | `koubo assets import-sfx-kit ~/sfx-kit --categories whooshes,interface` | CC0；可商用免署名；带 `use_for/tags/sync` 元数据 |
| 剪映云端音乐 | BGM | `koubo music pick` | 平台授权；`review_required`；不随项目分发 |
| 工程 `fonts/licenses/` | 字体 | JSON 记录 | OFL / 官方免费商用；逐条核对 |
| 用户原始素材 | 视频/音频/静帧 | 自动识别 | `project-input`；商用权利由用户确认 |
| 项目自绘/生成 | 插图/动效/包装 | 自动识别 | `project-owned` / `project-generated` |
| FMA / 淘声 / 耳聆 / 爱给 | 音乐/音效 | 手动 `assets add`，逐条填许可 | 协议混杂（CC BY/BY-NC/站内条款）；**不做批量抓取**，逐首核对 |
| GIPHY / 黑罐头 | 贴纸/梗图 | 手动下载后 `assets add --kind sticker` | 平台条款与人物/品牌风险；贴纸层通过 `stickers.items[].source` 使用 |

### 远程源

```bash
export PEXELS_API_KEY=...
export PIXABAY_API_KEY=...

koubo assets remote search pexels --media video --query "city night" --orientation portrait
koubo assets remote add pexels --media video --id 12345 --query "city night" --project my-video
```

- 没有 Key 明确报错，不伪造结果；
- 结果缓存 12 小时；单条下载，不批量；
- `add` 只下载选中的一条，写来源 URL、作者、平台许可；
- 人物/品牌/可识别的私人地点，商用前仍需人工确认肖像/商标/平台规则。

### sfx-kit

```bash
git clone https://github.com/wyzowl/sfx-kit ~/sfx-kit
koubo assets import-sfx-kit ~/sfx-kit --categories whooshes,interface,pops --limit 40
```

它带 `sounds.json`：`use_for/avoid_for/tags/sync.at/fits_seconds/under_voiceover_db`
等字段，正是「程序检索 + 稳定落点」需要的。默认按分类导入，不把 67MB 全量塞进仓库。

## 7. 接进流水线

```text
… → draft → asset-audit → visual-review → verify → review-outputs …
```

- `asset-audit`（`run_all`）扫描 `config` + `work` 实际用到的素材，写
  `work/asset-manifest.json`，并生成：
  - `output/asset-licenses.csv`
  - `output/CREDITS.md`
- `preflight` 会解析 `asset:` 引用、检查 B-roll/插图是否存在；坏引用在 frames 前就报。
- `verify` 新增 `asset-license`：
  - 有 `fail` → 红项；
  - 有 `unchecked` → `unchecked`，不是通过；
  - 没有 manifest → `unchecked`（先跑 audit）。
- `review-outputs` 的视频门包含 `asset-license`。

`audit` 覆盖的用量：

| 位置 | 记录 |
| --- | --- |
| `input.video/clips/audio/audio_map` | 原始素材（`project-input`） |
| `broll.items[].source` | B-roll（支持 `asset:`） |
| `inserts.items[].illustration` | 插图/静帧 |
| `stickers.items[].source` | 外部贴纸（`make_assets` 合成进贴纸层） |
| `sfx.events[].clip`（含 cue 解析） | 音效 |
| `audio.bgm`（本地/合成/Mixkit/剪映云端） | BGM |
| `captions.font` | 字幕字体 |
| `work/mixkit.json` | 旧 Mixkit 下载的兜底来源 |
| sidecar | 工程内素材的许可/来源 |

## 8. 按字幕召回（suggest）

```bash
koubo assets suggest my-video --cue 7
koubo assets suggest my-video --cue 7 --remote pexels,pixabay
```

它把字幕里的中文词扩成场景标签（城市→city/street，护理→care/hands，
营养餐→food/meal…），按 `tags/use_for/标题/描述` 打分，结合时长过滤和许可状态，
输出**可解释**的候选与 `reasons`。

这是**元数据召回**，不是语义向量 + VLM 精排。它不会自动改 `config`：
- 好处是可复核、可离线、不会把「模型觉得很像」当成证据；
- 边界是遇到片库里没有的近义表达，召回会弱；需要更强语义匹配时，
  可以在这层之上接 Embedding/VLM，但最终仍要落回同一份 ID 与许可记录。

## 9. 授权会变：台账的意义

免费素材站的许可不是永久不变的。`license_checked_at` + `license_snapshot` 让
「入库时是什么条款」和「现在是什么条款」可比较：

- 快照与当前目录不一致 → `unchecked`，提示重新核对；
- 超过 365 天未核 → `unchecked`；
- 导出成片时附 `asset-licenses.csv` 与 `CREDITS.md`，批量交付也能回答
  「这条片子里每一段素材从哪来、能不能商用」。

## 10. 限制

- 不是法律意见。`pass` 只代表已知许可边界内没有程序能发现的障碍；
  肖像权、商标权、平台规则、可识别地点仍需人工签收。
- 远程源依赖平台 API；没有 Key、限流、页面/接口变化都会明确报错。
- 不批量抓取、不登录、不绕付费墙；不把平台素材再分发。
- 随包音效的原始 Pixabay 单条 URL 未逐条留存，登记为 `bundled` 并注明；
  需要逐条来源时，用 `koubo assets set-license` 补 URL/备注，或重新从平台下载。
- `suggest` 是元数据召回，不是语义搜索；中文同义词表可扩展（`SCENE_SYNONYMS`）。
- **贴纸已接入**：`stickers.items[].source` 可以是图片路径或 `asset:<id>`，由
  `make_assets` 合成进贴纸层。**花字/字幕条模板尚未接入**：`templates/captions/`
  目录与登记已预留，但当前花字仍由 `workflow/caption_plan.py` 的代码样式生成；
  从剪映模板提取花字/气泡元信息是下一步，不在这一版里假装支持。
- **剪映模板（`templates/jianying/`）只登记，不自动套用**：模板模式与剪映版本/
  加密状态强相关，当前仍以本项目生成草稿为主。

## 11. 相关文件

- `scripts/workflow/asset_library.py`：注册表、sidecar、检索、核验、audit、suggest
- `scripts/workflow/asset_licenses.py`：许可目录、三态判据、字体许可
- `scripts/workflow/asset_remote.py`：Pexels/Pixabay/sfx-kit
- `scripts/asset_library.py`：`koubo assets` 命令
- `assets/library/README.md`：目录与命令速查
- `fonts/licenses/README.md`：字体许可记录规范
