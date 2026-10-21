"""B-roll 槽位：在字幕关键词时窗里插入真实细节镜头。

这一版只写剪映草稿（`B-roll` 轨），不进入 ffmpeg 预览；
因为真实 B-roll 要由用户提供，且草稿优先。素材必须真实，不能用生成图冒充证据。

配置：
  "broll": {
    "enabled": true,
    "items": [
      {"cue": 7, "keyword": "放心", "source": "broll/tea.mp4",
       "in": 0.5, "dur": 1.8, "volume": 0.0}
    ]
  }
"""
from __future__ import annotations

from pathlib import Path

from _common import caption_plain, input_path


def resolve(cfg: dict, project: Path, cues: list[dict]) -> tuple[list[dict], list[str]]:
    block = cfg.get("broll") or {}
    if not block.get("enabled"):
        return [], []
    by_index = {int(c["index"]): c for c in cues}
    plans, errors = [], []
    for i, item in enumerate(block.get("items") or [], 1):
        try:
            cue_index = int(item.get("cue"))
        except (TypeError, ValueError):
            errors.append(f"broll #{i} 缺 cue")
            continue
        cue = by_index.get(cue_index)
        if cue is None:
            errors.append(f"broll #{i} 的 cue={cue_index} 不在当前字幕里")
            continue
        keyword = str(item.get("keyword") or "")
        plain = "".join(caption_plain(line) for line in cue.get("lines") or [])
        if keyword and keyword not in plain:
            errors.append(f"broll #{i} 的触发词 {keyword!r} 不在第 {cue_index} 条字幕")
            continue
        raw_source = str(item.get("source") or "")
        if raw_source.startswith(("asset:", "library:")):
            try:
                from workflow import asset_library
                got = asset_library.resolve_ref(
                    raw_source, project=project,
                    library_root=(cfg.get("assets") or {}).get("library"))
                source = Path(got["path"])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"broll #{i} 的 {raw_source} 解析失败：{exc}")
                continue
        else:
            source = Path(raw_source)
            if not source.is_absolute():
                source = input_path(project, raw_source)
        if not source.is_file():
            errors.append(f"broll #{i} 找不到素材 {source}")
            continue
        try:
            in_at = float(item.get("in") or 0.0)
            dur = float(item.get("dur") or 0.0)
        except (TypeError, ValueError):
            errors.append(f"broll #{i} 的 in/dur 无效")
            continue
        if in_at < 0 or dur <= 0.1:
            errors.append(f"broll #{i} 的 in/dur 不合理")
            continue
        start = float(item.get("at") if item.get("at") is not None
                      else cue["start"] + 0.12)
        end = start + dur
        if start < float(cue["start"]) - 1e-9 or end > float(cue["end"]) + 1e-9:
            errors.append(f"broll #{i} {start:.2f}–{end:.2f}s 超出字幕 "
                          f"#{cue_index} {cue['start']:.2f}–{cue['end']:.2f}s")
            continue
        plans.append({"index": i, "cue": cue_index, "start": round(start, 3),
                      "end": round(end, 3), "source": str(source.resolve()),
                      "in": in_at, "dur": dur,
                      "volume": float(item.get("volume", 0.0))})
    return plans, errors
