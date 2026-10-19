# 节奏与切点分析

```bash
python scripts/analyze_pacing.py REF.mp4 --summary -o work/reference-pacing.json
```

| 指标 | 用途 |
| --- | --- |
| `duration` / `width` / `height` / `avg_fps` | 规格；`vfr_suspect` 标可变帧率 |
| `stream_duration_delta` | 容器时长 − 视频流时长，排查尾部黑帧/音频尾巴 |
| `pacing.shot_count` / `cut_count` / `cuts_per_minute` | 节奏档位 |
| `avg / median / min / max / stdev shot_duration` | 镜头长短分布 |
| `loudness.input_i` / `input_tp` | LUFS / 真峰 |
| `cuts[]` | 切点与 scene score |

## 方法

- 全量 scene score（`select='gt(scene,0)'`），不先砍固定阈值；
- 用**中位数 + MAD** 自适应阈值，再按 `min_gap` 做非极大抑制；
- 输出切点、镜头统计、VFR 诊断和响度。

这比固定 `scene>0.35` 更不容易漏掉“等亮度换色”，但仍有两个限制：

1. **同背景跳切**（口播换句、人物位置不变）scene score 很低，可能识别不到；这类切点要靠 SRT/ASR 停顿或人工确认。
2. **教程录屏/深色 UI** 会产生大量低分变化；不要拿它当真实镜头切点。

## 和风格规则的关系

`references/styles/*.md` 的量化锚点（切点密度、镜长、LUFS）应该从这个分析器的输出归纳，
而不是凭感觉填数字。当前风格模板仍为空，等真实成片。
