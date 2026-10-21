# 产出审查门

`verify.py` 是逐项机械检查；`review_outputs.py` 把它分成四道审查门，
并明确标出“自动查过”和“必须人看/人听”。

```bash
koubo review-outputs PROJECT --md
# 产物：work/review-report.json
```

## 四道门

| 审查门 | 自动查 | 必须人工 |
| --- | --- | --- |
| 文字 | 字幕重叠、标点、末条落点、包装复述、`grounded-claims`、样式计划一致 | 语义是否准确、是否像广告、口播与字幕是否逐句对得上 |
| 声音 | 采样率、响度、真峰、长静音、BGM、语音覆盖、清理记录 | 喇叭/环境噪声是否彻底没了、语气/节奏/齿音 |
| 插画 | 素材存在、最小边 ≥480px、`insert-rendered`、卡段渲染 | 构图、清晰度、是否像视频截图、版权/授权 |
| 视频 | 规格、帧率、时长、黑帧、片头/片尾/常驻标题、包装 beat、草稿 | 节奏、构图、审美、整体是否可发布 |

## 三态规矩

- `pass`：查过且通过
- `fail`：查过且不通过
- `unchecked`：判不了，必须写原因

**unchecked 不等于通过。** 四道门最终状态取最差项；只要有一项 unchecked，
`overall` 就是 `unchecked`，不能宣称“审查通过”。

## 当前新片审查结果

```text
text          pass       7 项自动
audio         unchecked  已静音 3 段非语音；喇叭是否彻底清除需人耳
illustration  unchecked  卡段渲染通过；素材审美/版权需人眼
video         unchecked  技术项通过；节奏/构图需人看
```

## 已知假阳性：草稿字体

`verify` 的 `draft-font` 只检查 `draft_content.json` 字段，不能证明 JianYing 真的用了字体。
JianYing 11.6 的 `draft_info.json` 加密，生成器无法验证；所以该检查现在是
**`unchecked`**，不是 `pass`。要确认字体，必须人工打开草稿看，或做烧录版。

## 边界

- 文字审查是 **token 级品牌/承诺依据检查**，不是语义事实核查；
- 声音审查没有自动喇叭/事件分类器，清理记录不是“听审通过”；
- 插画审查没有审美模型，只查存在/尺寸/渲染/来源；
- 视频审查没有审美模型，视觉审查包仍是人工 Gate。
