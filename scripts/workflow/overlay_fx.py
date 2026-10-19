"""包装层的关键帧：让卡片/品牌字落位时有一点速度，而不是整块静态出现。

只作用于 overlay_windows 产生的“包装层”片段；卡片内部的行/图标动画仍在
build_frames 里烧好。只进草稿，mp4 预览不含。
"""
from __future__ import annotations

from workflow.advanced_fx import KEY_PROPS


def resolve(cfg: dict, overlay_segments: list[dict]) -> tuple[list[dict], list[str]]:
    fx = cfg.get("overlay_fx") or {}
    if not fx.get("enabled"):
        return [], []
    by_label = {str(s["label"]): s for s in overlay_segments}
    plans, errors = [], []
    for i, item in enumerate(fx.get("items") or [], 1):
        label = str(item.get("label") or "")
        seg = by_label.get(label)
        if not seg:
            errors.append(f"overlay_fx #{i} 的 label={label!r} 不在包装层 {sorted(by_label)}")
            continue
        duration = float(seg["end"]) - float(seg["start"])
        keyframes = item.get("keyframes") or []
        for kf in keyframes:
            prop = str(kf.get("property") or "")
            if prop not in KEY_PROPS:
                errors.append(f"overlay_fx #{i} 属性不支持 {prop!r}")
            try:
                at = float(kf.get("time"))
            except (TypeError, ValueError):
                errors.append(f"overlay_fx #{i} time 无效")
                continue
            if at < -0.01 or at > duration + 0.05:
                errors.append(f"overlay_fx #{i} time={at} 超出片段 {duration:.2f}s")
        plans.append({"index": i, "label": label, "segment_id": seg["id"],
                      "start": float(seg["start"]), "end": float(seg["end"]),
                      "keyframes": keyframes})
    return plans, errors


def apply(cap, proj, plans: list[dict]) -> list[dict]:
    done = []
    for plan in plans:
        entry = {"index": plan["index"], "label": plan["label"],
                 "segment_id": plan["segment_id"], "applied": []}
        for kf in plan["keyframes"]:
            at = plan["start"] + float(kf["time"])
            args = ["keyframe", str(proj), plan["segment_id"], str(kf["property"]),
                    f"{at:.3f}", str(kf["value"])]
            if kf.get("easing"):
                args += ["--easing", str(kf["easing"])]
            cap.run(*args)
            entry["applied"].append("keyframe")
        done.append(entry)
    return done
