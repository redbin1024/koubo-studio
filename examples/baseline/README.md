# 示例基线

`config.json` 是 `references/measured.json` 的**校验基线**，不是一条能直接跑的片子。

它保留了早期 9:16 口播工程量出来的字幕字号、墨迹底位置、描边、阴影与两个强调色。
`scripts/check_measured.py` 会读这里，确认实测常量没有和登记表漂移；`verify.py` 的
`measured-constants` 一项也用它。

这里没有素材，也没有可渲染的工程。要做片请用：

```bash
koubo new my-video --video /path/to/口播.mp4
```
