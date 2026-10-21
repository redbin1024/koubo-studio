# 草稿规格与草稿审计

## 两个文件

```text
work/draft-spec.json   先写下的决策：轨道 / 镜头 / 文本 / 原生资源 / 音频 / QA
work/draft-qc.json     执行后和规格对账的结果
```

`draft-spec.json` 由 `make_jianying_draft` 在写草稿前生成，原则与 Edit-Skill 的 EDL 相同：
时间用秒、每个镜头有 role/rule_id/reason、原生资源只记名字与参数、验收要求先写。

`draft-qc.json` 由 `workflow/draft_audit.py` 生成，检查：

- 主轨段数 / 时长 / 结尾 / 间隙（能否逐镜头剪）
- 人声 / 音效 / BGM 轨是否存在、是否静音
- 字幕条数 / 时间重叠 / `line_spacing`
- 贴纸 / 特效 / 滤镜 / 转场数量
- 素材路径是否存在
- 草稿是否真的装进剪映草稿箱
- 活动文件与明文副本是否一致（`draft-twin`）

> 审计读的是**活动文件**（macOS `draft_info.json`，Windows `draft_content.json`），
> 不是只读 `draft_content.json`。剪映保存过、文件被加密时，经 `workflow/draft_native.py`
> 的 jianying-tool 桥解出来再对账；桥不可用时 `draft-readable` 直接红，
> 不会拿旧副本冒充通过。两份文件不一致时，先跑 `python scripts/draft_native.py sync`。

`verify.py` 会把它作为 **`draft-audit`** 一项计入三态质检；失败是红项，不是“没查”。

## 为什么需要它

`verify.py` 检查的是成片元数据，无法证明草稿里的声音、字幕、轨道是对的。实际踩过：

- 成片有人声，草稿没有人声；
- SRT 时间不重叠，剪映文本 `line_spacing=0.02` 叠字；
- 计划 8 个镜头，草稿主轨退回 1 段；
- `pip.enabled=false`，卡片仍画 PiP。

这些都在“日志正常、mp4 正常”时发生。`draft-audit` 是对执行层的独立对账。

## 用法

```bash
# 重建草稿并生成规格/审计
python scripts/make_jianying_draft.py PROJECT --force

# 只审计已有草稿
python - <<'PY'
import json
from pathlib import Path
from workflow.draft_audit import audit
spec=json.loads(Path("PROJECT/work/draft-spec.json").read_text())
print(audit(spec, Path("PROJECT/draft-store/NAME")))
PY
```

## 包装视觉合同与审查包

`draft-spec` 之外，`make_jianying_draft` 还会写：

- `draft-spec.advanced`：镜头级关键帧/蒙版/混合模式/背景模糊/逐段滤镜；
- 草稿的 B-roll 轨：真实细节镜头，按字幕关键词时窗插入（只进草稿）；
- `work/visual-contract.json`：每个卡片/插图/贴纸/原生资源的语义结构、可见区域、
  稳定阅读窗口、动效机制、claim_status 和证据边界；
- `work/packaging-review.json`：`make_visual_review.py` 生成的 72% 静帧 + 完整 beat 片段 +
  联系表，初始 pending；原生/草稿专属资源标 `requires-capcut-export`。

`verify.py` 的 `visual-contract` / `visual-review` 会分别检查合同合规与人工审查状态。
详见 [包装视觉合同与审查包](visual-contract.md)。

## 边界

- 规格由当前 planner 生成，不是完全独立的人类 EDL；它主要防“执行层丢东西”，还不能证明风格正确。
- 原生滤镜/特效/转场的视觉正确性仍需打开剪映确认，标 L3。
- 旧工程没有 `draft-spec.json` 时，`draft-audit` 记 `unchecked`，不伪造通过。
