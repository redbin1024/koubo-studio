# 按参考片选字体

给工程和参考片拆解，自动从**本机字体库 + emfont 在线字体库**里选一款字幕字体，
可选写进 `config.captions.font`。

```bash
# 先拆参考片（会生成 work/reference/reference-profile.json）
koubo reference "https://v.douyin.com/xxxx/" -p my-video

# 选字体；默认只出建议
koubo font-pick my-video

# 确认后应用
koubo font-pick my-video --apply

# 不联网、不调 AI：只用本机字体 + 本地打分
koubo font-pick my-video --library local --no-llm
```

产物：

| 文件 | 内容 |
| --- | --- |
| `work/font-selection.json` | 简报、候选短名单、选中/备选、理由、授权、应用状态、未检查 |
| `work/font-selection.md` | 人看的一页结论 |
| `work/font-samples.jpg` | 候选字体的实际样张（用当前字幕文字渲染，人眼复核） |
| `config.json` | `--apply` 后写入 `captions.font` |
| `fonts/emfont-<id>.ttf` | emfont 字体按当前字幕生成的子集文件（仅 `--apply` 时） |

## 它怎么选

```text
参考片分析（visual_style / structure / rhythm / audience / hook）
+ 工程字幕与文案
        ↓  风格信号：科技 / 温暖 / 叙事 / 促销 / 国风 / 综艺 / 高端 / 科普 …
        ↓  候选：本机 CJK 字体（工程 fonts/ 优先）+ emfont 目录
        ↓  本地打分预筛（类别、字重、可读性、授权、是否已锁定）
        ↓  DeepSeek 从闭集里选 1 款（有 Key 且没加 --no-llm）
        ↓  校验：id 必须在候选内、confidence 0–1、alternates 合法
        ↓  失败回退本地打分
```

没有 Key 时不会假装 AI 选过：`mode` 会写成 `fallback`，理由写明「本地风格信号打分」。

## 字体库

### 本机

扫描顺序与渲染器一致：

```text
工程 fonts/ → 安装目录 fonts/ → KOUBO_FONT_DIRS → 系统字体目录
```

只收带汉字字形的字体；同一族只保留字重最粗的一档（字幕优先粗体）。
候选会带 `license`：

- Noto / 思源 / 得意黑 → `OFL-1.1`；
- 阿里妈妈 / 阿里巴巴普惠体 → 免费商用（仍需核对官方条款）；
- 系统字体 → `系统字体（仅本机渲染，不可再分发）`；
- 其他 → `unknown`，商用前自行核对。

### emfont

[emfont](https://font.emtech.cc) 是一个中文字体库。它的
[emfont-mcp](https://github.com/emfont/emfont-mcp) 用 MCP 暴露了 6 个工具；
这些工具背后就是同一套 HTTP 接口：

```text
GET  /list            字体目录
GET  /info/{fontId}   字体详情（授权、描述、字重）
POST /g/{fontId}      按文字生成子集字体
```

本项目直接用 Python 调这套接口，**不引入 Node / MCP 运行时**：

```bash
koubo font-pick my-video --library auto     # 本地 + emfont（默认）
koubo font-pick my-video --library emfont   # 只用 emfont；不可用就报错
```

- 目录缓存 7 天、详情缓存 30 天，放在 `~/.cache/koubo/`；断网时可用上次目录。
- 接口不可用时，`auto` 自动退回本机字体，并在 `unchecked` 写明原因。
- 自定义镜像：`EMFONT_API_BASE=https://your-mirror.example`，镜像需提供同样的
  `/list`、`/info`、`/g` 路径。
- 注意：`emfont-mcp` 的 `pnpm start` 只暴露 `/mcp`，不是 `/list`；本项目不把 MCP
  端口当 REST API 用，也不会替你启动 Node 服务。
- emfont 仓库是 Apache-2.0，但**每个字体有各自授权**；选中的字体授权以
  `work/font-selection.json` 里的 `license` 为准，不会因为工具开源就当成字体可商用。

## 应用与 style-lock

`--apply` 会写 `config.captions.font`。字体属于 style-lock 的风格投影，所以：

- 项目有 `work/style-lock.json` 且锁定字体与选中字体不同时，**默认不应用**，
  写 `apply_blocked` 并提示先发布新配方版本、重新绑定。比较的是 `captions.font`
  的完整字符串：同族不同字重也算变更，不会悄悄改锁；
- 加 `--force` 才会写，并标记 `style_lock_conflict=true` —— 此时
  `koubo style check` 会红。这不是 bug，是风格锁在起作用；
- 选中的就是锁定字体时，正常应用（等于不改）。

## emfont 子集字体

emfont 的 `/g/{id}` 是按文字生成子集，不是完整字体。应用时会把当前工程的：

- `input/captions.srt` 全部文字；
- `work/reference/transcript.json` 或 `work/transcript.json` 的口播；
- `config.card.rows` 的卡片文字；
- 工程名、常用标点/数字/字母

一起作为 `words` 传给 emfont，下载到 `fonts/emfont-<id>.ttf`，再用
`font_display_name()` 读出真实族名写进 config。

**改字幕之后要重跑 `--apply`**：子集字体只覆盖生成时的文字，新字会缺字。
模块会在应用前用 PIL 检查字幕字形，缺字会拒绝并尝试下一个候选。

## 授权与商用

```bash
# 商用场景：降低 NC/非商业字体的分数
koubo font-pick my-video --commercial

# 只保留明确 OFL/Apache/MIT/免费商用 的候选
koubo font-pick my-video --strict-license
```

`--strict-license` 会把系统字体（授权未知/系统限制）也过滤掉，候选可能只剩 Noto
或 emfont 里明确标注的字体；过滤数量会写进 `unchecked`。

## 参数

| 参数 | 作用 |
| --- | --- |
| `--reference PATH` | 参考片目录 / `reference-profile.json`；默认读 `<工程>/work/reference` |
| `--library auto\|local\|emfont` | 字体库来源；默认 auto |
| `--apply` | 写 `config.captions.font` |
| `--force` | 允许替换 style-lock 锁定的字体（会让 style check 红） |
| `--no-llm` | 只用本地打分，不调 DeepSeek |
| `--commercial` | 商用场景，降低 NC/非商业字体分数 |
| `--strict-license` | 只保留明确可商用的授权 |
| `--max-candidates N` | 最多送多少候选给 AI（默认 36） |
| `--json` | 只打印 `font-selection.json` 路径 |

拆参考片时也可以顺手选：

```bash
koubo reference "https://v.douyin.com/xxxx/" -p my-video --pick-font
# → my-video/work/reference/font-selection.json
# 只出建议，不写 config；确认后再 koubo font-pick my-video --apply
```

## 边界

- **不证明字体在剪映里一定好看**：选择依据是参考片文本分析 + 字体元数据，
  最终要在 `work/font-samples.jpg` 和成片字幕上人眼复核（写进 `unchecked`）。
- **不做字形特征识别**：没有把字体渲成图再比风格；类别/标签来自字体名与字体库元数据。
- **不保证授权**：授权文本按字体库原样记录，商用发布前仍需核对官方条款。
- **不自动改字号/描边/位置**：只换字体；字号、描边、行距仍由字幕/风格配置决定。
- **emfont 不可用不是失败**：`auto` 会用本机字体继续，并把「emfont 字体库」写进未检查。


## 剪映草稿里为什么字体不生效

`font-pick --apply` 只写 `config.captions.font`，那是 mp4/Pillow 的字幕字体；
剪映草稿不读 config，它读 `materials.texts[].font_resource_id` 和
`content.styles[].font`。只改 config，剪映仍然用默认字体。

现在在 config 里写：

```json
"captions": {
  "font": "Songti SC Black",
  "jianying_font": {
    "name": "SourceHanSerifCN-Medium",
    "resource_id": "7265597365539574329",
    "path": ""
  }
}
```

`make_jianying_draft` 会把 resource_id 写进文本材质和每个 range 的 `font`；
`verify` 的 `draft-font` 逐条核对。resource_id 必须在
`capcut enums --fonts --jianying` 的列表里，否则剪映会回退默认字体。
