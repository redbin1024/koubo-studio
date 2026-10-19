"""高级剪映片段操作：关键帧 / 蒙版 / 混合模式 / 背景模糊 / 透明度 / 逐段滤镜。

这些能力只进剪映草稿，mp4 预览不含。配置是显式的，默认不启用：
  "shot_fx": {
    "enabled": true,
    "items": [
      {"shot": 1, "keyframes": [
        {"property": "scale", "time": 0.0, "value": "1.0"},
        {"property": "scale", "time": 1.2, "value": "1.06", "easing": "ease-out"}
      ]}
    ]
  }

约束：
- shot 是主轨 1-based 序号；
- keyframe.time 相对该镜头起点，执行层换成时间线绝对秒；
- duplicate=true 时复制一条上层 video-copy，把 mask/mix/bg_blur/opacity 作用在副本上，
  原主轨保留；副本默认静音，避免声音叠两遍。
"""
from __future__ import annotations

MASK_SLUGS = {"linear", "mirror", "circle", "rectangle", "heart", "star"}
MIX_MODES = {"normal", "multiply", "screen", "overlay", "soft-light", "hard-light",
             "color-dodge", "color-burn", "darken", "lighten", "difference", "exclusion"}
KEY_PROPS = {"position_x", "position_y", "rotation", "scale", "scale_x", "scale_y",
             "alpha", "opacity", "saturation", "contrast", "brightness", "volume"}
MASK_FLAGS = {"center_x": "--center-x", "center_y": "--center-y", "size": "--size",
              "rotation": "--rotation", "feather": "--feather",
              "rect_width": "--rect-width", "round_corner": "--round-corner"}


def resolve(cfg: dict, main_segments: list[tuple[str, float, float]]) -> tuple[list[dict], list[str]]:
    fx = cfg.get("shot_fx") or {}
    if not fx.get("enabled"):
        return [], []
    plans, errors = [], []
    for i, item in enumerate(fx.get("items") or [], 1):
        if not isinstance(item, dict):
            errors.append(f"shot_fx #{i} 不是对象")
            continue
        try:
            shot = int(item.get("shot"))
        except (TypeError, ValueError):
            errors.append(f"shot_fx #{i} 缺 shot 序号")
            continue
        if not 1 <= shot <= len(main_segments):
            errors.append(f"shot_fx #{i} 的 shot={shot} 超出主轨 {len(main_segments)} 段")
            continue
        sid, start, end = main_segments[shot - 1]
        duration = end - start
        duplicate = bool(item.get("duplicate"))
        mask = item.get("mask")
        mask_slug = None
        if mask:
            if isinstance(mask, str):
                mask = {"type": mask}
            mask_slug = str(mask.get("type") or "").strip().lower()
            if mask_slug not in MASK_SLUGS:
                errors.append(f"shot_fx #{i} mask 不支持 {mask_slug!r}")
                continue
        mix = item.get("mix_mode")
        if mix is not None and str(mix).lower() not in MIX_MODES:
            errors.append(f"shot_fx #{i} mix_mode 不支持 {mix!r}")
            continue
        keyframes = item.get("keyframes") or []
        for kf in keyframes:
            if not isinstance(kf, dict):
                errors.append(f"shot_fx #{i} keyframe 不是对象")
                continue
            prop = str(kf.get("property") or "")
            if prop not in KEY_PROPS:
                errors.append(f"shot_fx #{i} keyframe 属性不支持 {prop!r}")
            try:
                at = float(kf.get("time"))
            except (TypeError, ValueError):
                errors.append(f"shot_fx #{i} keyframe time 无效")
                continue
            if at < -0.01 or at > duration + 0.05:
                errors.append(f"shot_fx #{i} keyframe time={at} 超出镜头 {duration:.2f}s")
        plans.append({
            "index": i, "shot": shot, "segment_id": sid, "start": start,
            "end": end, "duration": duration, "duplicate": duplicate,
            "mask": mask, "mask_slug": mask_slug, "mix_mode": mix,
            "bg_blur": item.get("bg_blur"), "opacity": item.get("opacity"),
            "keyframes": keyframes, "filters": item.get("filters") or [],
            "mute_duplicate": bool(item.get("mute_duplicate", True)),
        })
    return plans, errors


def apply(cap, proj, plans: list[dict]) -> list[dict]:
    done = []
    for plan in plans:
        target = plan["segment_id"]
        entry = {"index": plan["index"], "shot": plan["shot"],
                 "segment_id": target, "duplicate": plan["duplicate"], "applied": []}
        if plan["duplicate"]:
            out = cap.run("duplicate", str(proj), target, "--new-track")
            new_id = out.get("new_segment_id") or out.get("segment_id")
            if not new_id:
                raise SystemExit(f"duplicate shot {plan['shot']} 没返回 segment id：{out}")
            target = new_id
            entry["target_segment_id"] = target
            entry["applied"].append("duplicate")
            if plan.get("mute_duplicate"):
                cap.run("volume", str(proj), target, "0.0", check=False)
                entry["applied"].append("mute_duplicate")
        if plan.get("opacity") is not None:
            cap.run("opacity", str(proj), target, str(float(plan["opacity"])))
            entry["applied"].append("opacity")
        if plan.get("bg_blur") is not None:
            level = int(plan["bg_blur"])
            if 1 <= level <= 4:
                cap.run("bg-blur", str(proj), target, str(level))
                entry["applied"].append("bg_blur")
        if plan.get("mask_slug"):
            opts = []
            mask = plan["mask"] or {}
            for key, flag in MASK_FLAGS.items():
                if key in mask and mask[key] is not None:
                    opts += [flag, str(mask[key])]
            if mask.get("invert"):
                opts.append("--invert")
            cap.run("mask", str(proj), target, plan["mask_slug"], *opts)
            entry["applied"].append("mask")
        if plan.get("mix_mode"):
            cap.run("mix-mode", str(proj), target, str(plan["mix_mode"]).lower())
            entry["applied"].append("mix_mode")
        for kf in plan["keyframes"]:
            at = plan["start"] + float(kf["time"])
            args = ["keyframe", str(proj), target, str(kf["property"]), f"{at:.3f}",
                    str(kf["value"])]
            if kf.get("easing"):
                args += ["--easing", str(kf["easing"])]
            cap.run(*args)
            entry["applied"].append("keyframe")
        for flt in plan["filters"]:
            name = str(flt.get("name") or "").strip()
            if not name:
                continue
            cap.run("add-filter", str(proj), name, f"{plan['start']:.3f}",
                    f"{plan['duration']:.3f}", "--intensity",
                    str(float(flt.get("intensity", 1.0))))
            entry["applied"].append(f"filter:{name}")
        done.append(entry)
    return done
