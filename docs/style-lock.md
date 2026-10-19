# 固定风格与 style-lock

口播风格不是一堆会漂移的 config 值，而是带 **ID / 版本 / 配方哈希 / 就绪范围** 的资产。
灵感来自 talking-head-motion 的 style-lock；这里不复制其 30 款内容。

## 风格目录

```bash
koubo style list
koubo style resolve KB-TH-01
```

当前只有一款真实风格：

| ID | 名称 | 版本 | 范围 |
| --- | --- | --- | --- |
| `KB-TH-01` | 暖食玻璃卡 | 1.2.0 | 4105 全功能版；无片头标题；字幕描边 8/阴影 4；卡片落位关键帧；行级音效；视觉审查 16 beat 中 14 个原生/高级操作待剪映导出确认 |

目录：`references/styles/catalog.json`
配方：`references/styles/recipes/KB-TH-01.json`

配方只含**风格参数**，不含文案、时间、素材：

- 画布、字幕字体/字号/描边/位置/动画、配色；
- 卡片/插图/金色品牌字几何；
- 调色、剪映滤镜/特效/转场；
- 编辑原则：人物主线、单处底部字幕、阅读窗口 ≥0.6s。

## 绑定到项目

```bash
koubo style bind my-video --style KB-TH-01 \
  --choice-source '用户在当前对话指定暖食玻璃卡'
```

写入 `work/style-lock.json`：完整配方快照 + `recipe_sha256` + 快照哈希 + 选择来源 + readiness。

## 校验

```bash
koubo style check my-video
```

`verify` 的 `style-lock` 项会检查：

- 锁存在；
- 风格库同版本配方哈希未变；
- 锁内快照未被改；
- **当前 config 的风格投影**与锁定配方一致。

**改风格参数但不升版本 → 红项。** 必须发布新版本、重新绑定。
文案、时间、素材等非风格字段（card.rows、inserts.items、captions.skip、转场 at 等）不参与投影。

## 边界

- 锁只证明“风格参数没漂移”，不证明审美、滤镜、关键帧在剪映里好看；视觉审查仍需人工。
- `readiness` 说明验证到哪；不要把它写成“全库通过”。
- 当前只有一款真实风格；不要为了凑数复制出 30 款。
