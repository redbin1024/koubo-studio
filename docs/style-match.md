# 按内容匹配固定风格

不是把 30 个 recipe 复制进项目，而是：

1. 读你的字幕/镜头表/已有版式；
2. 给每款参考风格打分（内容语义、ready 程度、CapCut 可执行性）；
3. 输出“可以参考哪款 + 该改哪些动作”，不假装已经实现。

## 命令

```bash
python scripts/style_match.py 4105-全功能版 \
  --catalog /path/to/talking-head-motion/assets/fixed-styles/catalog.json \
  --limit 5 --out work/style-match.json
```

只读外部 catalog/recipes；不复制配方、视频或字体。

## 打分看什么

- 内容信号：步骤/清单、细节、数字、前后对比、情绪、钩子、品牌词；
- 画面信号：镜头数、每分钟切点、已有卡片 skin、已有插图数；
- readiness：`partial_native_windows_reviewed` 优先，`mechanism_preview_only` 降权；
- 引擎：`d08/d06/d14/d19/d28/d22` 可 CapCut 近似；`d13/d15/d18/...` 必须 overlay；
- 现有版式：已有玻璃卡时，d08 直接加权。

## 当前实测

4105：

```text
TH-DY-08 暗玻璃三卡递进 15.0 capcut
TH-DY-14 薄荷绿三联卡   12.0 capcut
TH-DY-06 白毛玻璃章节卡  9.0 capcut
TH-DY-19 四角重点词      8.0 capcut
TH-DY-02 逐字方块        6.0 capcut
```

接送：

```text
TH-DY-02 逐字方块        8.0 capcut
TH-DY-19 四角重点词      6.0 capcut
TH-DY-01 三段式          5.0 capcut
TH-DY-11 关键词重击      5.0 capcut
TH-DY-22 趋势图卡        4.0 capcut
```

## 怎么“参考剪辑”

把结果当 **adaptation brief**，不是模板：

| 命中 | 可以做什么 | 不能做什么 |
| --- | --- | --- |
| `d08_glass_stack` | 复用现有玻璃卡，三行逐项揭示 + 扫描光条 | 不能直接搬它的配色/字体/视频 |
| `d02_word_tiles` | 钩子句逐字/短块入场 | 不能把整片做成字块 |
| `d19_corner_keywords` | 四个短词放四角 | 需要四个真的关键词，不能凑 |
| `d14_collage_cards` | 3 张真实图/插画拼贴 | 没有 3 张素材就别选 |
| `d13_cutout_outline` | 人物描边 overlay | 不是 CapCut 原生，不能假装可编辑 |

## 边界

- 这是推荐器，不是自动复刻器；不保证审美通过。
- 外部 recipe 的 CDN/源视频/字体不随我们分发。
- 参考风格是“改编依据”，不是原作者素材的替代。
