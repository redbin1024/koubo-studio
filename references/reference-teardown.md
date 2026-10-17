# 参考片拆解

`analyze_reference.py` 的输出怎么读，以及**哪些数不能直接信**。

## 输出字段

```jsonc
{
  "probe":         { "width": 720, "height": 1280, "fps": 30, "duration": 24.148,
                     "video_codec": "hevc", "audio_codec": "aac",
                     "video_index": 1, "audio_index": 0 },
  "scene_cuts":    [ { "t": 14.8, "score": 0.62 }, ... ],
  "accent_colors": [ { "hex": "#E8D068", "hue": "yellow", "count": 14444 }, ... ],
  "card":          { "start": 14.75, "end": 20.5, "bbox_norm": [0.115,0.15,0.859,0.848],
                     "fill_hex": "#A09E9F", "area": 0.31, "rectangularity": 0.66 },
  "pip":           { "bbox_norm": [0.489,0.513,1.0,0.913], "sharpness_contrast": 2.93 },
  "caption_band":  { "detected": true, "y_top_norm": 0.577, "y_bottom_norm": 0.881,
                     "x_min_norm": 0.091, "x_max_norm": 0.993 },
  "flat_bands":    [ { "y_from": 0.8, "y_to": 0.85, "gradient": 6.2 }, ... ]
}
```

### `probe` — 先看流顺序

**`audio_index` 可能是 0。** 竖屏 HEVC 片常把音频排在视频前面，任何逐帧取像素的地方
都必须显式 `-map 0:v`，否则会拿到音频字节然后解码崩掉。脚本内部已经这么做了，
自己写 ffmpeg 命令时别忘了。

### `accent_colors` — 抄成字幕强调色

按 `count` 排序，**已经按色相去重**（每种色相最多 3 个）。
参考片里橙色（皮肤、木纹）数量碾压一切，不去重的话黄和粉会被挤掉。

挑法：
- `hue=yellow` 的那个 → `captions.palette.accent`（正向词）
- `hue=magenta` / `violet` / `red` → `captions.palette.contrast`（反差词、数字）

### `card` — 卡段起止与卡片几何

- `start` / `end`：卡段的起止时间，直接抄成 `card.start` / `card.end`。
  这个检测相当稳（判据是「长时段稳定的单色大块」），实测误差 < 0.2s。
- `bbox_norm`：含亮描边的外沿，抄成 `card.box`。
- `fill_hex`：卡片填充色，抄成 `card.fill`。
- **`radius` 与描边宽度量不出来**，按画布短边取：圆角 ≈ 2.5%、描边 ≈ 1.4%。

### `pip` — 画中画位置

- `bbox_norm` 抄成 `pip.box`。**贴到 1.0 的边表示画中画越出画面（出血）。**
- 返回的是**保守内框**：低对比的暗部边缘长不过去，实测比真值内缩 5–10%。
  外沿用 `--frames` 抽帧人眼微调。
- `pip.center`（画中画里人物取景的中心）脚本不猜，按构图填。默认是画布 (0.555, 0.432)。
- 只在卡段里检测。没有卡段的片子 `pip` 一定是 `null`，这是对的。

### `caption_band` — 字幕带

- `margin_v = (1 - y_bottom_norm) × 画布高`
- `max_width = (x_max_norm - x_min_norm) × 画布宽`，`margin_lr = x_min_norm × 画布宽`
- 判据是「亮像素 + 紧邻深色硬描边」，所以它**只认白字黑硬边**的自动字幕。
  参考片用的是柔和阴影或纯色无描边字幕时，这个字段会是 `detected: false`。
- `y_top_norm` 偏低（< 0.35）时说明把画面里的其他白色硬边也圈进来了，看一眼抽帧确认。

### `flat_bands` — 字幕放哪儿最干净

每 5% 高度一条，`gradient` 越小画面越平。把 `margin_v` 落在 gradient 最小的那几条里，
字幕就不会压在人脸或花哨背景上。

### `scene_cuts` — 别把字幕变化当镜头切换

`score` 高的才是真镜头切换。**字幕出现/消失也会被 scene 检测记为切点**，
所以切点数通常比真实镜头数多。参考片那种「一个长镜 + 中段切一次」的结构，
`scene_cuts` 里可能有 5 条，真镜头只有 2 个。

## 精度边界

| 字段 | 实测精度 | 备注 |
| --- | --- | --- |
| 卡段起止 | ±0.2s | 稳 |
| 卡片填充色 | ±3/255 | 稳 |
| 卡片 bbox | ±1.5% 画面 | 被画中画遮挡的边会内缩 |
| 画中画 bbox | 内缩 5–10% | 保守内框，需人工外扩 |
| 字幕带 | ±2% 画面 | 只对白字黑硬边有效 |
| 强调色 | 色相一致 | 具体 hex 会因编码有 ±8/255 偏差 |

**量完一定要看抽帧。** `--frames work/ref-frames` 会把抽到的帧存成 png，
对着它复核一遍比信任何数字都可靠。
