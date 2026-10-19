# Draft Spec / EDL 协议

本项目的“决策层”协议是 `work/draft-spec.json`。它不是剪映 JSON，而是剪映执行前的稳定接口。
设计原则借自 Edit-Skill 的 EDL：

- 时间是**秒（float）**，执行层换微秒；
- 轨道/片段/文本/原生资源各自有类型；
- 每个镜头有 `role`、`rule_id`、`reason`；
- 先写规格，再执行；执行后由 `draft_audit` 对账；
- 不把剪映内部 id 写进决策层。

## 顶层结构

```jsonc
{
  "version": 1,
  "project": "4105-全功能版",
  "canvas": {"width": 1080, "height": 1920, "fps": 30},
  "duration": 42.9,
  "tracks": [{"name": "main", "type": "video"}, ...],
  "clips": [
    {"id": "main-1", "track": "main", "type": "video",
     "source": "work/graded.mp4", "source_in": 0.0,
     "start": 0.0, "duration": 6.5,
     "role": "shot", "rule_id": "shot_1", "reason": "按镜头表切段"}
  ],
  "texts": [{"id": "text-1", "track": "captions", "content": "...",
             "start": 0.43, "duration": 3.42, "line_spacing": 0.22}],
  "native": [{"kind": "filter", "name": "暖食", "at": 0.0, "dur": 42.9}],
  "stickers": [{"id": "sticker-1", "track": "stickers", "start": 19.6,
                "duration": 2.2, "source": "assets/sticker-1.png"}],
  "audio": [{"id": "voice", "track": "voice", "duration": 42.869,
             "required": true}],
  "qa": {"min_main_segments": 8, "require_voice": true,
          "min_line_spacing": 0.12, "max_text_overlaps": 0,
          "planned_main_segments": 8, "require_installed": true}
}
```

## 单位与陷阱

1. 时间一律秒；剪映落盘是微秒，由 `make_jianying_draft` 转换。
2. 转场写在“进入哪个片段”的语义上；剪映内部存在**前序片段**，执行层负责映射。
3. 转场是**重叠**，不额外占时长；`Σ duration` 必须等于时间轴结尾，否则会出现无素材黑洞。
4. 主轨分段要按帧对齐；最后一帧差额补到最后一段，保证 `main end == duration`。
5. 文本 `line_spacing` 是剪映内部值；`import-srt` 默认 0.02 会叠字，本项目默认 0.22（L4）。

## 校验

- `make_jianying_draft` 写 `work/draft-spec.json`；
- `workflow/draft_audit.py` 生成 `work/draft-qc.json`；
- `verify.py` 的 `draft-audit` 红项以它为准。规格缺失时记 `unchecked`，不伪造通过。

## 与 Edit-Skill EDL 的差异

| 项 | Edit-Skill | Koubo Studio |
| --- | --- | --- |
| 执行层 | pyJianYingDraft | capcut-cli + 草稿 JSON 补丁 |
| 主轨来源 | 原始素材 source_in | 当前为压平 `graded.mp4` 切段 |
| 贴纸 | 剪映 resource-id / sticker 轨 | 本地全画布 PNG，独立贴纸轨 |
| 关键帧/蒙版 | EDL 已部分表达 | 尚未接入 |
| 导出 | 人工 | 人工 |
