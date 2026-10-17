# capcut-cli 笔记

面向剪映 macOS 的 `capcut-cli` 使用笔记，记录本项目实际依赖的命令、资源库与版本边界。命令数以 `capcut-cli 0.25.0` 实测为准；升级后请重新核对。

> 剪映版本迭代很快，草稿格式、加密文件与资源缓存都可能变。这里写的是「我们验证过什么」，不是永久承诺。

## 常用命令

| 类别 | 命令 |
| --- | --- |
| 读 | `info` / `version` / `tracks` / `segments` / `texts` / `materials` / `segment` / `timeline` / `diff` / `diagnose` / `config` |
| 片段 | `set-text` / `shift` / `shift-all` / `speed` / `volume` / `trim` / `opacity` / `crop` / `duplicate` / `remove` / `replace-media` / `cut` / `concat` |
| 素材 | `add-video` / `add-audio` / `add-text` / `tts` / `add-sfx` / `add-sticker` / `add-filter` / `add-effect` / `add-cover` |
| 调整 | `keyframe` / `transition` / `mask` / `bg-blur` / `mix-mode` / `audio-fade` / `chroma` / `matting` / `text-style` / `text-ranges` / `text-anim` / `image-anim` / `bubble-text` |
| 字幕 | `import-srt` / `import-ass` / `caption` / `export-srt` / `export-ass` / `export-timeline` / `import-timeline` / `translate` |
| 建稿 | `init` / `quickstart` / `compile` / `templates` / `save-template` / `apply-template` / `make-preset` |
| 批处理 | `batch` / `serve` / `export --batch` |
| 维护 | `lint` / `prune` / `register` / `rename` / `relink` / `restore` / `sync-timelines` / `migrate` / `decrypt` / `fixture` |
| 资源 | `enums` / `catalogue` / `harvest-enums` |
| 分析 | `detect-scenes` / `detect-silence` / `detect-retakes` |

## 草稿读写

- 标准文件：`draft_content.json`、`draft_info.json`、`draft_meta_info.json`、`template-2.tmp`。
- 时间线可能在根对象，也可能在浅层 JSON 信封里。
- 写盘是「同目录临时文件 + fsync + rename」的原子替换，每个文件保留一份 `.bak`。
- `--dry-run` 不落盘；编辑器运行时默认拒绝写，`--force-write` 覆盖但仍打 warning。

**本项目只依赖其中稳定的一部分**：`init` / `add-video` / `add-audio` / `add-text` / `import-srt` / `text-ranges` / `text-anim` / `relink` / `register` / `lint` / `enums`。其余命令在 `docs` 里记录，但不进流水线。

## 版本边界

`capcut-cli` 自带写保护：版本未知、过新或 schema 顶层整数异常时可能拒绝写入。实测注意：

- **`version` 可能返回 `app_version: null`。** 没有版本标记时，写保护会被判成 `ok`，但这不代表剪映真的兼容。
- **剪映 ≥ 6.0 的 `draft_meta_info.json` 可能被加密。** `capcut-cli` 只读写 4 个标准文件；加密镜像里的漂移它看不见。
- **`template-2.tmp` 可能是二进制/加密。** `sync-timelines` 在无法重建时会失败，这是预期行为。
- 升级剪映后，先跑一次 `capcut diagnose` 和 `capcut lint`，再决定是否批量重出草稿。

**本项目对剪映自己动过的草稿不覆盖**：目录里出现 `Timelines/`，或 `draft_meta_info.json` 被加密，脚本只提示、换名或确认丢弃时加 `--force-install`。

## 资源库

`capcut enums` 才是资源清单。`--help` 里只列了几个例子，实际远不止。

| 命名空间 | 场景特效 | 人物特效 | 滤镜 | 转场 | 文字入场 | 音效 |
| --- | --- | --- | --- | --- | --- | --- |
| CapCut（默认） | 345 | 95 | 10 | 116 | 76 | 15 |
| 剪映 `--jianying` | 912 | 227 | 468 | 362 | 144 | 43 |

关键结论：

- **别拿 slug 数量判断能不能用。** `findEnum` 除了 slug 还匹配 **member**，中文名就是 member。
- `add-effect` / `add-filter`：名字或 `--resource-id` 都行，`--intensity 0-1` 控制强度。
- `transition` / `add-sfx`：按中文 member 名 + `--jianying` 可用。
- `add-sfx` 加的是**音效效果**（回音/低保真/8bit 这类处理器），不是「音效素材」。
- **剪映音乐库没有命令行接口**，`add-audio` 只收本地文件。所以 BGM 走本地合成或用户自备文件。
- `--full` 别用：实测它会按草稿时长算，写出约 2× 片长的滤镜段。滤镜一律显式给起止。

## 字幕与文字

- `import-srt`：一条 cue 一个文字片段。关键词上色用 `text-ranges`，出入场动画用 `text-anim`。
- `text-ranges` 的 `start/end` 是 **JS 字符串 code unit 索引**（BMP 字符与 Python 下标一一对应）。
- `import-srt` 被 capcut-cli 标为 "mimicry"：它拆出来的是一堆独立文本段，剪映不认它是一条字幕轨。要原生字幕轨得换 `caption`，本项目尚未接入。
- `import-srt` 不收逐段字号与位置，所以草稿侧只能对齐入场动画；对不齐的部分 `verify` 记 `unchecked`，不假装通过。
- 剪映不会按画布宽度自动折行。写入前脚本用 DP 折行，行宽上限 9 字，尽量不切开带色关键词。

## 本项目用到的调用

```bash
capcut init <dir> --name <草稿名> ...
capcut add-video <draft> <file> --track <track> --start <us> ...
capcut add-audio <draft> <file> --track <track> --start <us> --volume <v>
capcut import-srt <draft> <srt> --track <track> --style-ref <id>
capcut text-ranges <draft> <segment> --ranges @ranges.json
capcut text-anim <draft> <segment> --in 弹入 --out 渐隐
capcut relink <draft> --from <src> --to <dest>
capcut register <draft> --materials --apply
capcut lint <draft> --fix
capcut enums --filters --jianying
```

具体参数见仓库里的 `scripts/make_jianying_draft.py`；那里是唯一正本，本文只做索引。
