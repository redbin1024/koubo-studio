# package-only：只做包装，不重剪

`koubo package` 用于**已经剪好的口播成片 + 对应 SRT**：

```bash
koubo package my-package \
  --video ~/Movies/已剪好的口播.mp4 \
  --srt ~/Movies/已剪好的口播.srt \
  --captions burned-in
```

它不会调用 `auto_edit` / `merge_cut`，不会重排镜头、不会重新选段、不会改原声；
只做字幕 / 包装 / BGM / 草稿 / 质检。

## 和 `koubo auto` 的边界

| | `koubo auto` | `koubo package` |
| --- | --- | --- |
| 输入 | 原始素材 | 已经剪好的成片 + SRT |
| 粗剪 | 自动选段/排序 | **不做** |
| 原声 | 保留/旁白 | 保留 |
| 字幕 | ASR 生成 / burned-in / none | 使用给定 SRT；可 burned-in/none |
| 包装 | 自动基础包装 | 用 config 里的包装；默认关闭卡片/插图 |
| 草稿 | 逐镜头主轨 | 原成片作为一条主轨（不拆镜头） |

## 常用参数

```bash
# 只建工程与 config，不跑渲染
koubo package my-package --video in.mp4 --srt in.srt --prepare-only

# 源片已带烧录字幕：不再生成一层
koubo package my-package --video in.mp4 --srt in.srt --captions burned-in

# 不要画面字幕
koubo package my-package --video in.mp4 --srt in.srt --captions none

# 覆盖已有 config 的输入/画布
koubo package my-package --video in.mp4 --srt in.srt --force
```

## 包装从哪来

`package-only` 只负责“壳”和“流程”，默认包装是关闭的：

```json
"card": {"enabled": false},
"inserts": {"enabled": false},
"gold": {"enabled": false},
"stickers": {"enabled": false}
```

要卡片/插图/贴纸，编辑 `config.json` 后重跑 `koubo run my-package`，或在现有工程里
配置好包装再 `--prepare-only`。**不会自动编造卡片文案或品牌名。**

- 默认开启暖调 BGM（0.30），用于填原片静音，避免 `long-silence` 红项。
- 原声保留；`speech_mode=source`。
- `captions.mode=burned-in/none` 时画面字幕为空，草稿不建字幕轨。

## 产物

```text
my-package/output/final-*.mp4
my-package/draft-store/<name>/
my-package/work/qc-report.json
my-package/work/draft-qc.json
my-package/work/visual-contract.json     # 启用了包装时
my-package/work/packaging-review.json     # 启用了包装时
my-package/work/package-only.json          # 输入哈希与字幕模式
```

## 边界

- 输入必须是**已经定剪**的成片；这里不会修复重读、口误、长停顿。
- 主轨是一条原成片，不按镜头拆段；要逐镜头剪，请走 `auto` 或手动 `merge`。
- 原片已有烧录字幕时用 `burned-in`；没有 OCR 自动检测，需要人确认。
- 原生滤镜/特效/转场/贴纸仍只进草稿；最终以剪映导出为准。
