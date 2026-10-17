#!/usr/bin/env python3
"""Produce editable rough-cut plans for talking heads and multi-clip Vlogs."""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import urllib.error
from pathlib import Path
from typing import Callable

from _common import apply_defaults, find_ffmpeg, input_path, probe_media, run
from auto_captions import write_srt
from merge_cut import narration_slots, silences, speech_blocks
from transcribe_audio import transcribe
from workflow.edit_plan import render_plan, validate_plan
from workflow.storyboard import suggest_story
from workflow.visual_analysis import analyze_shots, api_key_from_env


def scene_cuts(path: Path) -> list[float]:
    """Return FFmpeg scene-change timestamps; these are not semantic events."""
    result = run([find_ffmpeg(), "-hide_banner", "-i", str(path), "-an",
                  "-vf", r"select=gt(scene\,0.35),showinfo", "-f", "null", "-"])
    return [float(t) for t in re.findall(r"showinfo.*?pts_time:\s*([\d.]+)",
                                          result.stderr)]


def talking_head_shots(clips: list[Path], info: dict[str, dict],
                       detect_silences: Callable[[Path], list[tuple[float, float]]] | None = None,
                       narration_slot_count: int = 0,
                       min_slot: float = 1.10) -> list[dict]:
    """说话段 + （可选）解说槽。

    `narration_slot_count > 0` 时，把最长的几段**真实静音**留进片子里当解说槽
    （`kind: "narration-slot"`）。这是「解说只落在现场人声的空隙里」的落地方式：
    槽是留出来的，不是事后补一段数字静音假装出来的。
    """
    detect_silences = detect_silences or (lambda p: silences(p, -34.0, 0.30))
    shots = []
    for clip in clips:
        meta = info[str(clip)]
        if not meta["has_audio"]:
            raise ValueError(f"{clip.name} 没有音轨，无法检测口播")
        sils = detect_silences(clip)
        slots = narration_slots(meta["duration"], sils, min_slot, narration_slot_count)
        blocks = speech_blocks(meta["duration"], sils, 0.10, 0.45, 0.40)
        for start, end in blocks:
            # 说话段的切点两侧各留了 0.10s，会从**两边**伸进解说槽里；重叠的后果是
            # 成片把同一段声音播两遍，所以槽前那段收到槽口、槽后那段从槽尾起。
            for a, b in slots:
                if start >= b or end <= a:
                    continue
                if start < a:
                    end = a
                else:
                    start = b
            if end - start < 0.20:
                continue
            shots.append({"source": str(clip), "in": round(start, 3),
                          "duration": round(end - start, 3),
                          "reason": "speech", "score": 0.5, "kind": "speech"})
        for a, b in slots:
            shots.append({"source": str(clip), "in": round(a, 3),
                          "duration": round(b - a, 3), "reason": "narration-slot",
                          "score": 0.5, "kind": "narration-slot"})
        shots.sort(key=lambda shot: shot["in"])
    if not shots:
        raise ValueError("没有检测到可用说话段，未生成粗剪")
    return shots


def vlog_shots(clips: list[Path], info: dict[str, dict],
               detect_cuts: Callable[[Path], list[float]] = scene_cuts) -> list[dict]:
    shots = []
    for clip in clips:
        duration = float(info[str(clip)]["duration"])
        bounds = [0.0] + sorted({t for t in detect_cuts(clip) if 0 < t < duration}) + [duration]
        for start, end in zip(bounds, bounds[1:]):
            if end - start < 0.001:
                continue
            # Scene changes are only candidate boundaries. With no event evidence,
            # a fixed centre crop can remove the beginning/end of the action.
            shots.append({"source": str(clip), "in": round(start, 3),
                          "duration": round(end - start, 3),
                          "reason": "scene", "score": 0.5})
    if not shots:
        raise ValueError("没有检测到可用镜头，未生成粗剪")
    return shots


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def finish_with_captions(project: Path, plan: dict, cfg: dict, *,
                         transcript_path: Path | None, model: str,
                         replace_captions: bool) -> dict:
    """Stage video and captions together; do not promote either on ASR failure."""
    cut = project / "input" / "clean-cut.mp4"
    srt = project / "input" / (cfg["input"]["subtitle"] or "captions.srt")
    if srt.exists() and not replace_captions:
        raise FileExistsError(f"已有字幕 {srt}；确认重生成时加 --replace-captions")
    work = project / "work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="auto-edit-", dir=work) as stage:
        stage = Path(stage)
        video = stage / "clean-cut.mp4"
        canvas = cfg["canvas"]
        result = render_plan(plan, video, canvas["width"], canvas["height"], canvas["fps"])
        if transcript_path is not None:
            record = json.loads(transcript_path.read_text(encoding="utf-8"))
            if record.get("source") and Path(record["source"]).resolve() != cut.resolve():
                raise ValueError("提供的转写文件与这条粗剪不匹配")
        else:
            record = transcribe(video, stage / "transcript.json", model)
        if abs(float(record["duration"]) - result["duration"]) > 0.25:
            raise ValueError("转写时长与新粗剪不一致，不能把旧字幕接到新画面上")
        record["source"] = str(cut.resolve())
        caption_result = write_srt(record, stage / "captions.srt")
        if caption_result["status"] != "ok":
            raise ValueError("未检测到可转写语音；保留原工程，未生成猜测字幕")
        cut.parent.mkdir(parents=True, exist_ok=True)
        os.replace(video, cut)
        os.replace(stage / "captions.srt", srt)
        cfg["input"]["video"], cfg["input"]["clips"] = "clean-cut.mp4", []
        cfg["duration"] = round(result["duration"], 3)
        _atomic_json(project / "config.json", cfg)
        _atomic_json(work / "transcript.json", record)
        result["output"] = str(cut)
        return {"result": result, "captions": caption_result}


def main() -> None:
    ap = argparse.ArgumentParser(description="生成可修改的自动粗剪方案并执行")
    ap.add_argument("project")
    ap.add_argument("--mode", choices=("talking-head", "vlog"))
    ap.add_argument("--clips", nargs="+", default=[])
    ap.add_argument("--narration-slots", type=int, default=0,
                    help="口播：留住最长的 N 段真实静音当解说槽（0 = 不留，行为同以前）")
    ap.add_argument("--apply-plan", action="store_true", help="只执行已修改的 work/edit-plan.json")
    ap.add_argument("--plan-only", action="store_true", help="只生成方案，不输出粗剪")
    ap.add_argument("--auto-captions", action="store_true", help="粗剪后离线识别语音并生成 SRT")
    ap.add_argument("--replace-captions", action="store_true", help="显式替换已有字幕")
    ap.add_argument("--transcript", type=Path, help="导入已转写的 JSON，跳过模型调用")
    ap.add_argument("--model", default="large-v3", help="本地 faster-whisper 模型")
    ap.add_argument("--vision", action="store_true",
                    help="上传每镜头的一张缩小代表帧，生成可审核的视觉建议")
    ap.add_argument("--vision-model", default="deepseek-flash")
    ap.add_argument("--story", action="store_true",
                    help="从视觉证据生成待审核的镜头顺序、旁白及音乐情绪")
    args = ap.parse_args()
    if args.story and not args.vision:
        ap.error("--story 需要 --vision")
    if args.vision and not api_key_from_env():
        ap.error("缺少 DEEPSEEK_API_KEY；未抽帧、未上传素材")
    if (args.transcript or args.replace_captions) and not args.auto_captions:
        ap.error("--transcript/--replace-captions 需与 --auto-captions 一起使用")
    if args.plan_only and args.auto_captions:
        ap.error("--plan-only 不执行粗剪，不能同时生成字幕")
    project = Path(args.project).resolve()
    plan_path = project / "work" / "edit-plan.json"
    config_path = project / "config.json"
    if args.apply_plan:
        if args.clips or args.mode or args.plan_only:
            ap.error("--apply-plan 不能同时提供 --mode、--clips 或 --plan-only")
        if not plan_path.is_file():
            ap.error(f"找不到 {plan_path}")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        if not args.mode or not args.clips:
            ap.error("自动生成方案需要 --mode 和 --clips")
        clips = [input_path(project, value).resolve() for value in args.clips]
        if not all(clip.is_file() for clip in clips):
            ap.error("素材不存在：" + ", ".join(str(c) for c in clips if not c.is_file()))
        info = {str(clip): probe_media(clip) for clip in clips}
        shots = (talking_head_shots(clips, info,
                                    narration_slot_count=args.narration_slots)
                 if args.mode == "talking-head" else vlog_shots(clips, info))
        plan = {"version": 1, "mode": args.mode, "shots": shots,
                "timing": {"policy": "selected_content", "target_duration": None,
                           "source_duration": round(sum(meta["duration"] for meta in info.values()), 3),
                           "planned_duration": round(sum(shot["duration"] for shot in shots), 3)}}
        validate_plan(plan, {source: meta["duration"] for source, meta in info.items()})
        if not args.auto_captions and not args.vision:
            _atomic_json(plan_path, plan)
    review = None
    story = None
    if args.vision:
        try:
            review = analyze_shots(plan, model=args.vision_model)
            if args.story:
                # New ASR output is not available yet; never reuse an older transcript.
                story = suggest_story(review, model=args.vision_model)
        except (ValueError, RuntimeError, urllib.error.URLError) as exc:
            raise SystemExit(f"视觉分析未完成：{exc}") from exc
    if args.plan_only:
        if not args.apply_plan:
            _atomic_json(plan_path, plan)
        if review is not None:
            _atomic_json(project / "work" / "visual-review.json", review)
        if story is not None:
            _atomic_json(project / "work" / "storyboard.json", story)
        print(f"方案已保存：{plan_path}（{len(plan['shots'])} 个镜头）")
        return

    cfg = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {
        "name": project.name}
    cfg["mode"] = plan["mode"]
    if cfg.get("audio", {}).get("speech_mode") is None:
        cfg.setdefault("audio", {}).pop("speech_mode", None)
    cfg = apply_defaults(cfg)
    if args.narration_slots and plan["mode"] == "talking-head":
        # 留了槽就意味着要有解说：语音契约从「只有现场人声」变成「现场人声 + 解说」。
        cfg.setdefault("audio", {})["speech_mode"] = "mixed"
    if args.auto_captions:
        try:
            finished = finish_with_captions(
                project, plan, cfg, transcript_path=args.transcript, model=args.model,
                replace_captions=args.replace_captions)
        except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc
        if not args.apply_plan:
            _atomic_json(plan_path, plan)
        if review is not None:
            _atomic_json(project / "work" / "visual-review.json", review)
        if story is not None:
            _atomic_json(project / "work" / "storyboard.json", story)
        result, captions = finished["result"], finished["captions"]
        print(f"粗剪 + 自动字幕：{result['shots']} 镜头 / "
              f"{captions['cues']} 条 → {result['output']}")
        return
    canvas = cfg["canvas"]
    result = render_plan(plan, project / "input" / "clean-cut.mp4",
                         canvas["width"], canvas["height"], canvas["fps"])
    cfg["input"]["video"] = "clean-cut.mp4"
    cfg["input"]["clips"] = []
    cfg["duration"] = round(result["duration"], 3)
    _atomic_json(config_path, cfg)
    if not args.apply_plan and args.vision:
        _atomic_json(plan_path, plan)
    if review is not None:
        _atomic_json(project / "work" / "visual-review.json", review)
    if story is not None:
        _atomic_json(project / "work" / "storyboard.json", story)
    print(f"粗剪已生成：{result['output']}（{result['shots']} 个镜头，"
          f"{result['duration']:.3f}s）；配置已更新：{config_path}")


if __name__ == "__main__":
    main()
