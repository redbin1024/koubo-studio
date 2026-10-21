# 音频真重音

从口播/ promo 音频里找“真重音”，输出 `work/beats.json`。不依赖 librosa/scipy。

```bash
koubo beats PROJECT
# 或指定媒体
python scripts/audio_beats.py PROJECT --media input/clean-cut.mp4
```

## 算法

- ffmpeg 抽 16kHz 单声道 PCM
- 80ms 窗口算 RMS
- 800ms 滚动中位数做局部参考
- 当前能量 ≥ 邻域中位数 × 1.6，且 ≥ 0.015
- 相邻峰 < 12 帧（0.4s @30fps）去重，保留更强峰

输出：

```json
{
  "source": "input/clean-cut.mp4",
  "duration": 32.7,
  "fps": 30,
  "beats": [{"frame": 204, "time": 6.8, "energy": 0.0823}]
}
```

## 用途

- promo 卡点、口头重读的切点候选；
- B-roll / overlay 入场时间参考；
- 不是 BPM 检测，也不是“每拍必切”的命令。

## 边界

- 噪声大的素材会误检；`beats.json` 是候选，不是自动剪辑决策；
- 只作为 `run_all` 的一个诊断步骤，当前不自动改切点；
- 需要更细的鼓点/BPM，应另接音乐分析，不要拿它冒充。
