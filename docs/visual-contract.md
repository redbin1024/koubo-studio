# 包装视觉合同与视觉审查包

`draft-spec.json` 解决“对象在不在、时长对不对”；`visual-contract.json` 解决
“这个包装 beat 是否有明确的语义结构、可见区域、稳定阅读窗口和证据边界”。

## visual-contract.json

每个 beat 记录：

```jsonc
{
  "id": "insert-1",
  "kind": "insert",              // card / insert / gold / sticker / native
  "structure": "icon-label",     // detail-list / icon-label / brand-stamp / decorative / style-layer
  "start": 19.51, "end": 21.71,
  "style_id": "editorial-insert",
  "visible_feature": { "description": "...", "region": [0.1, 0.54, 0.9, 0.72] },
  "reading": { "start": 19.81, "end": 21.71, "stable_text": true },
  "motion": { "mechanism": "rise+fade", "phase": "semantic-completion",
              "windows": [[19.51, 19.81]] },
  "assets": [{ "kind": "authored-graphic", "path": "assets/insert-1.png", "exists": true }],
  "claim_status": "speech",      // speech / brand / owner-confirmed / sourced / estimate / none
  "evidence_refs": [],
  "native": false
}
```

- `sourced` 必须带 `evidence_refs`；没有真实素材不能叫证据。
- 卡片/插图如果在片子里只是“口播主张”，`claim_status=speech`，不能升级成“官方数据”。
- 原生特效/滤镜/转场标 `native:true, visual_status=requires-capcut-export`；
  **mp4 预览不包含它们**，不能拿底层视频冒充效果证据。

`workflow/visual_contract.py` 会检查：结构合法、region 在画面内、阅读窗口 ≥0.5s
（装饰/原生除外）、素材存在、sourced 有依据。

## packaging-review.json

`make_visual_review.py`（`koubo visual-review`）对每个非原生、非草稿专属 beat：

- 抽 **72% 稳定帧**；
- 截 **完整 beat 片段**；
- 生成联系表；
- 写 `work/packaging-review.json`，初始 `status=pending`。

原生特效/滤镜/转场、以及只在剪映草稿里的贴纸，标
`requires-capcut-export`，**不生成假证据**，需要在剪映打开/导出后审查。

`verify.py` 的 `visual-review` 项：

- 没有包 → `unchecked`
- 有 pending / requires-capcut-export → `unchecked`，detail 写清原因
- 有 fail → `fail`
- 全部人工通过 → `pass`

自动审查不会把 pending 改成 pass；不能拿“渲染成功/联系表存在”冒充视觉验收。

## 当前 4105 全功能版

- 16 个包装 beat：5 个可看 mp4 证据（卡/品牌字/3 张插图），
  3 个贴纸 + 6 个原生资源 + 2 个镜头级高级操作需剪映导出后审查。
- 联系表：`work/packaging-review/contact-sheet.jpg`
- 逐 beat 片段：`work/packaging-review/clips/`
- 审查文件：`work/packaging-review.json`（pending）

## 怎么验收

1. 打开 `contact-sheet.jpg`，检查卡片/插图：文字是否重叠、是否压人物、是否对题。
2. 播放 `clips/` 下每个 beat 的完整片段，检查入场、稳定阅读、退出。
3. 打开剪映 `4105-全功能版-定稿`，检查贴纸/暖食/光晕/叠化；导出后再看最终效果。
4. 把实际观察写进 `packaging-review.json` 每个 beat 的 `observation`，逐项 `status=pass`，
   最后把顶层 `status` 改成 `pass`；`verify` 才会通过。

> 这一步是人工的，不能由脚本自动填 PASS。没有看过的项保持 pending，比伪造通过更有价值。
