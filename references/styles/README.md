# 风格规则库

风格 ≠ 操作 ≠ 手法。这里只放**风格**：切多快、怎么开场、字幕放哪、音乐什么情绪。

**规则必须从用户真实成片归纳，不能凭空写。** 当前仓库还没有足够的口播/Vlog 参考成片，
所以 `talking-head.md` 与 `vlog.md` 先保持空模板。

## 分析入口

```bash
python scripts/analyze_reference.py <参考成片> --out work/ref.json
python scripts/analyze_pacing.py <参考成片> --summary -o work/reference-pacing.json
python scripts/check_measured.py ...
```

需要量的指标：

- 总时长 / 镜头数 / 每分钟切点
- 平均、中位、最短、最长镜头
- 响度（LUFS）/ 真峰
- 字幕位置、行数、每行字数
- 转场频率与类型
- BGM 情绪 / 是否有鼓点
