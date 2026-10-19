#!/usr/bin/env python3
"""一条命令全自动成片：原始素材 → mp4 + 剪映草稿。

    python scripts/auto_film.py my-video --video ~/Movies/口播.mp4
    koubo auto my-video --video ~/Movies/口播.mp4 --reference ~/Movies/参考片.mp4

没有 API Key 时可在 DeepSeek / Agent 窗口里用宿主导演模式：
    koubo auto my-video --video ~/Movies/口播.mp4 --prepare
    # 当前窗口的模型读 work/host-director-request.json，写 host-director-decision.json
    koubo auto my-video --video ~/Movies/口播.mp4 --resume

它做的是「决策 + 执行 + 修复」三件事：

1. 本地规则先跑：探测素材、静音/场景切点、ASR、候选镜头表；
2. 有 DEEPSEEK_API_KEY 时让模型做导演决策（口播选段/排序/高亮/音乐，
   Vlog 走视觉分析 + 故事方案）；模型输出全部要过校验，不合法就回退本地结果；
3. 自动完成粗剪、字幕、原声证据、旁白（无声素材）、BGM、音效、渲染、剪映草稿，
   跑 `run_all --auto`，再按 `work/qc-report.json` 的红项做有限次自动修复。

它不是“跳过质检”：质检照跑，只是人工听审不再阻塞（需要复核时另跑
`export_voice_review.py`）。所有自动决策写在 `work/auto-decisions.json`，
每个回退原因写在 `work/auto-report.json`，方便事后追。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (  # noqa: E402
    apply_defaults, ensure_dirs, find_font, font_display_name, input_path, load_config,
    parse_srt, probe_media, project_paths, resolve_duration, strip_punct, write_json,
)
from auto_edit import talking_head_shots, vlog_shots  # noqa: E402
from auto_captions import write_cues, write_srt  # noqa: E402
from new_project import build_config  # noqa: E402
from transcribe_audio import transcribe  # noqa: E402
from workflow import auto_director  # noqa: E402
from workflow.auto_voice import AutoVoiceError, build_narration  # noqa: E402
from workflow.edit_plan import render_plan, validate_plan  # noqa: E402
from workflow.source_speech import (  # noqa: E402
    EVIDENCE_NAME, evidence_status, source_signature,
)
from workflow.visual_analysis import api_key_from_env  # noqa: E402


AUTO_DECISIONS = "auto-decisions.json"
AUTO_REPORT = "auto-report.json"
ASR_DIR = "asr"
TRANSCRIPT = "transcript.json"
MAX_SFX = 8
ASR_DEFAULT = "small"
LLM_DEFAULT = "deepseek-flash"


class AutoError(RuntimeError):
    """自动流程无法继续；消息要能直接告诉用户下一步做什么。"""


# ---------------------------------------------------------------- 小工具

def _sha(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _clean_shot(shot: dict) -> dict:
    """只保留镜头表认识的字段；transcript 留给自动报告，不写进 edit-plan。"""
    keep = ("source", "in", "duration", "kind", "reason", "score", "transition",
            "audio_gain", "id")
    return {key: shot[key] for key in keep if key in shot}


def _write_empty_captions(project: Path, cfg: dict) -> Path:
    path = project_paths(project)["input"] / (cfg["input"]["subtitle"] or "captions.srt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _strip_line_punct(line: str) -> str:
    """保留 [[ ]] / (( )) 标记，只清掉标记内外的标点；房规要求字幕无标点。"""
    parts = re.split(r"(\[\[.*?\]\]|\(\(.*?\)\))", line)
    out = []
    for part in parts:
        if part.startswith("[[") and part.endswith("]]"):
            inner = strip_punct(part[2:-2])
            if inner:
                out.append(f"[[{inner}]]")
        elif part.startswith("((") and part.endswith("))"):
            inner = strip_punct(part[2:-2])
            if inner:
                out.append(f"(({inner}))")
        else:
            out.append(strip_punct(part))
    return "".join(out)


def _strip_caption_punct(path: Path) -> bool:
    if not path.is_file():
        return False
    cues = parse_srt(path)
    if not cues:
        return False
    changed = False
    out = []
    for cue in cues:
        text = cue["raw"]
        fixed = "|".join(_strip_line_punct(line) for line in text.split("|"))
        changed = changed or fixed != text
        out.append({"start": cue["start"], "end": cue["end"], "text": fixed})
    if changed:
        write_cues(out, path, force=True)
    return changed


def _wrap_highlights(text: str, highlights: list[str], budget: int) -> tuple[str, int]:
    """把关键词第一次出现处包成 [[词]]；已在标记里的不重复包。"""
    for word in sorted(highlights, key=len, reverse=True):
        if budget <= 0:
            break
        if not word or word not in text:
            continue
        spans = [m.span() for m in re.finditer(r"\[\[.*?\]\]|\(\(.*?\)\)", text)]
        position = text.find(word)
        if position < 0 or any(a <= position < b for a, b in spans):
            continue
        text = text[:position] + f"[[{word}]]" + text[position + len(word):]
        budget -= 1
    return text, budget


def _apply_highlights(path: Path, highlights: list[str]) -> int:
    if not highlights or not path.is_file():
        return 0
    cues = parse_srt(path)
    if not cues:
        return 0
    budget = auto_director.MAX_HIGHLIGHTS
    out = []
    for cue in cues:
        text, budget = _wrap_highlights(cue["raw"], highlights, budget)
        out.append({"start": cue["start"], "end": cue["end"], "text": text})
    write_cues(out, path, force=True)
    return auto_director.MAX_HIGHLIGHTS - budget


def _read_qc(project: Path) -> dict | None:
    path = project_paths(project)["work"] / "qc-report.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _qc_fails(qc: dict | None) -> list[dict]:
    if not qc:
        return []
    return [c for c in qc.get("checks", []) if c.get("status") == "fail"]


def _asr_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _clean_voice(project: Path, cfg: dict) -> None:
    p = project_paths(project)
    for path in (p["work"] / "voice.wav", p["work"] / "voice-cues.json",
                 p["input"] / "voice-captions.srt"):
        path.unlink(missing_ok=True)
    cfg.setdefault("audio", {}).pop("voice_cues", None)
    cfg["audio"].pop("voice_subtitle", None)


def _reset_work(project: Path) -> None:
    """--force 时清掉可再生的中间产物；保留 ASR / TTS 缓存，重跑不用重新识别。"""
    p = project_paths(project)
    keep = {"asr", "tts-cache"}
    for entry in p["work"].iterdir():
        if entry.name in keep:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for directory in (p["captions"], p["assets"]):
        if directory.is_dir():
            for entry in directory.iterdir():
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
    for name in ("captions.srt", "voice-captions.srt", "clean-cut.mp4"):
        (p["input"] / name).unlink(missing_ok=True)
    for movie in p["output"].glob("final-*.mp4"):
        movie.unlink(missing_ok=True)


# ---------------------------------------------------------------- 工程与素材

def _measure_reference(project: Path, reference: Path) -> dict:
    p = project_paths(project)
    out = p["work"] / "reference-teardown.json"
    print(f"  量参考片 → {out}")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "analyze_reference.py"),
         str(reference), "--out", str(out), "--frames", str(p["work"] / "ref-frames")],
        capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-6:])
        raise AutoError(f"参考片拆解失败：\n{tail}")
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AutoError(f"参考片拆解结果读不了：{exc}") from exc


def _resolve_clips(args, project: Path) -> list[Path]:
    values: list[str] = []
    if args.video and args.clips:
        raise AutoError("--video 与 --clips 只能二选一")
    if args.video:
        values = [args.video]
    elif args.clips:
        values = list(args.clips)
    else:
        cfg_path = project_paths(project)["config"]
        if not cfg_path.is_file():
            raise AutoError("没有素材：请给 --video 或 --clips")
        cfg = load_config(cfg_path)
        values = [cfg["input"]["video"]] if cfg["input"].get("video") else [
            *cfg["input"].get("clips", [])]
    clips = [input_path(project, value).resolve() for value in values if value]
    missing = [str(clip) for clip in clips if not clip.is_file()]
    if missing:
        raise AutoError("素材不存在：" + "、".join(missing))
    if not clips:
        raise AutoError("没有素材：请给 --video 或 --clips")
    return clips


def _aspect(clips: list[Path]) -> str:
    info = probe_media(clips[0])
    return "9:16" if (info["height"] or 0) >= (info["width"] or 0) else "16:9"


def _load_or_build_config(args, project: Path, clips: list[Path]) -> dict:
    p = project_paths(project)
    if p["config"].is_file() and not args.force:
        cfg = load_config(p["config"])
        if args.reference:
            print("  已有 config.json：本次不重新量参考片；要重量加 --force")
        if len(clips) == 1:
            cfg["input"]["video"] = str(clips[0])
            cfg["input"]["clips"] = []
        else:
            cfg["input"]["video"] = None
            cfg["input"]["clips"] = [str(c) for c in clips]
        write_json(p["config"], cfg)
        return cfg

    if args.force:
        _reset_work(project)
    teardown = _measure_reference(project, Path(args.reference).expanduser().resolve()) \
        if args.reference else None
    mode_hint = args.mode if args.mode != "auto" else ("vlog" if len(clips) > 1 else "talking-head")
    cfg = build_config(project.name, _aspect(clips),
                       str(clips[0]) if len(clips) == 1 else None,
                       [str(c) for c in clips] if len(clips) > 1 else [],
                       teardown, mode=mode_hint)
    cfg["mode"] = mode_hint
    cfg["name"] = project.name
    cfg["jianying"].update({"name": project.name, "install": True,
                            "ratio": _aspect(clips)})
    write_json(p["config"], cfg)
    return apply_defaults(cfg)


def _resolve_mode(clips: list[Path], requested: str) -> str:
    if requested != "auto":
        return requested
    if len(clips) > 1:
        return "vlog"
    info = {str(clips[0]): probe_media(clips[0])}
    if not info[str(clips[0])]["has_audio"]:
        return "vlog"
    try:
        shots = talking_head_shots(
                clips, info, pad=0.12, merge_gap=0.55, lead=0.70, tail=0.15)
        return "talking-head" if shots else "vlog"
    except (ValueError, SystemExit):
        return "vlog"


# ---------------------------------------------------------------- ASR / 候选

def _transcribe_clip(clip: Path, model: str, work: Path, *, required: bool) -> dict | None:
    if not _asr_available():
        if required:
            raise AutoError("口播自动字幕需要 faster-whisper；先跑 "
                            "`pip install -r requirements-transcribe.txt`，"
                            "或重跑 `bash install.sh`")
        return None
    key = _sha(f"{clip.resolve()}|{clip.stat().st_mtime_ns}|{clip.stat().st_size}|{model}")
    cache = work / ASR_DIR / f"{key}.json"
    try:
        if cache.is_file():
            record = json.loads(cache.read_text(encoding="utf-8"))
            if (record.get("source") == str(clip.resolve()) and
                    Path(record.get("source", "")).is_file()):
                return record
    except (OSError, ValueError):
        pass
    try:
        record = transcribe(clip, cache, model)
    except Exception as exc:                                    # noqa: BLE001
        if required:
            raise AutoError(f"离线转写失败：{type(exc).__name__}: {str(exc)[:160]}") from exc
        return None
    return record


def _words_text(record: dict | None, start: float, end: float) -> str:
    if not record or not record.get("words"):
        return ""
    words = []
    for word in record["words"]:
        try:
            mid = (float(word["start"]) + float(word["end"])) / 2
            text = str(word["text"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if text and start - 0.03 <= mid < end + 0.03:
            words.append(text)
    return strip_punct("".join(words))


def _merge_scene_candidates(shots: list[dict], limit: int = auto_director.MAX_SHOTS
                            ) -> list[dict]:
    """Vlog 超过视觉分析上限时，只合并同源且连续的相邻镜头，绝不截掉片尾。"""
    out = [dict(s) for s in shots]
    while len(out) > limit:
        best = None
        for i in range(len(out) - 1):
            a, b = out[i], out[i + 1]
            if (str(Path(a["source"]).resolve()) == str(Path(b["source"]).resolve()) and
                    abs(float(a["in"]) + float(a["duration"]) - float(b["in"])) < 0.06):
                cost = float(a["duration"]) + float(b["duration"])
                if best is None or cost < best[0]:
                    best = (cost, i)
        if best is None:
            break
        i = best[1]
        a, b = out[i], out[i + 1]
        merged = {**a,
                  "duration": round(float(a["duration"]) + float(b["duration"]), 3),
                  "reason": "scene-merged",
                  "transcript": strip_punct(str(a.get("transcript") or "") +
                                            str(b.get("transcript") or ""))}
        out[i:i + 2] = [merged]
    return out


# ---------------------------------------------------------------- 语音与字幕

def _transcribe_cut(project: Path, clean_cut: Path, model: str, *, required: bool
                    ) -> dict | None:
    work = project_paths(project)["work"]
    try:
        info = probe_media(clean_cut)
    except SystemExit as exc:
        raise AutoError(f"粗剪文件不可读：{exc}") from exc
    signature = source_signature(clean_cut, info["duration"])
    cached = work / TRANSCRIPT
    try:
        old = json.loads(cached.read_text(encoding="utf-8"))
        if old.get("signature") == signature and old.get("source") == str(clean_cut.resolve()):
            return old
    except (OSError, ValueError, AttributeError):
        pass
    record = _transcribe_clip(clean_cut, model, work, required=required)
    if record is None:
        return None
    record = {**record, "signature": signature}
    write_json(cached, record)
    return record


def _source_evidence(record: dict | None, clean_cut: Path, total: float
                     ) -> tuple[dict | None, bool, str]:
    if not record:
        return None, False, "没有可用的离线转写"
    signature = source_signature(clean_cut, total)
    bound = {**record, "signature": signature}
    ready, detail = evidence_status(bound, signature)
    return bound, ready, detail


def _narration_windows(plan: dict, result: auto_director.DirectorResult,
                       total: float) -> list[dict]:
    if not result.story or not result.narration:
        return []
    try:
        from story_audio import validate_audio_story
        scheduled = validate_audio_story(result.story, plan)
    except (ValueError, KeyError, TypeError) as exc:
        raise AutoError(f"故事旁白与镜头表对不上：{exc}") from exc
    anchors = {round(float(a["start"]), 3): a for a in scheduled.get("anchors", [])}
    windows = []
    for line in scheduled.get("windows", []):
        item = {"start": float(line["start"]), "end": float(line["end"]),
                "text": line["text"]}
        anchor = anchors.get(round(item["start"], 3))
        if anchor:
            item.update({"shot_index": anchor["shot_index"],
                         "shot_ref": anchor["shot_ref"]})
        windows.append(item)
    # 旁白可以跨镜头：把窗口延到下一句之前，给 TTS 留出真实的时间。
    for i, item in enumerate(windows):
        next_start = windows[i + 1]["start"] if i + 1 < len(windows) else total
        extended = min(total - 0.10, next_start - 0.15)
        if extended > item["start"] + 0.35:
            item["end"] = max(item["end"], extended)
    return windows


def _prepare_voice(project: Path, cfg: dict, mode: str,
                   result: auto_director.DirectorResult, plan: dict, clean_cut: Path,
                   total: float, asr_model: str,
                   no_narration: bool) -> tuple[str, list[str], dict | None]:
    """决定原声/旁白/无语音，并写好字幕与证据。返回 (speech_mode, notes, voice_info)。"""
    notes: list[str] = []
    record = _transcribe_cut(project, clean_cut, asr_model,
                             required=(mode == "talking-head"))
    bound, ready, detail = _source_evidence(record, clean_cut, total)
    if ready:
        write_json(project_paths(project)["work"] / EVIDENCE_NAME, bound)
        _clean_voice(project, cfg)
        srt = project_paths(project)["input"] / (cfg["input"]["subtitle"] or "captions.srt")
        result_srt = write_srt(record, srt, force=True)
        if result_srt.get("status") != "ok":
            raise AutoError("原声转写成功但生成不了字幕")
        _apply_highlights(srt, result.highlights)
        cfg["audio"]["speech_mode"] = "source"
        notes.append(f"保留原声：{detail}")
        return "source", notes, None

    notes.append(f"原声不可用作口播：{detail}")
    _write_empty_captions(project, cfg)
    if mode == "vlog" and result.narration and not no_narration:
        cfg["audio"]["voice_subtitle"] = "voice-captions.srt"
        cfg["audio"]["voice_cues"] = "voice-cues.json"
        try:
            windows = _narration_windows(plan, result, total)
        except AutoError as exc:
            notes.append(f"旁白窗口不可用：{exc}")
            windows = []
        if windows:
            try:
                voice = build_narration(project, cfg, windows, total=total)
                cfg["audio"]["speech_mode"] = "narration"
                notes.append(f"自动旁白 {len(voice['lines'])} 句"
                             + (f"，跳过 {len(voice['skipped'])} 句" if voice["skipped"] else ""))
                return "narration", notes, voice
            except AutoVoiceError as exc:
                notes.append(f"旁白生成失败，回退无旁白：{exc}")
        else:
            notes.append("故事方案没有可执行的旁白，回退无旁白")
    _clean_voice(project, cfg)
    cfg["audio"]["speech_mode"] = "none"
    notes.append("无旁白，保留 BGM/环境声")
    return "none", notes, None


# ---------------------------------------------------------------- 配置与包装

def _configure_style(cfg: dict, project: Path, result: auto_director.DirectorResult,
                     mode: str) -> None:
    cfg["mode"] = mode
    cap = cfg["captions"]
    # 主题会盖过显式 font/palette；自动模式已经定好实际字体，去掉主题避免
    # run_all 重新 load_config 时把字体覆盖回一个系统里没有的族名。
    cap.pop("theme", None)
    try:
        find_font(cap.get("font"), project)
    except SystemExit:
        try:
            fallback = find_font(None, project)
            cap["font"] = font_display_name(fallback)
        except SystemExit as exc:
            raise AutoError(f"找不到可用中文字体：{exc}") from exc
    cap["strip_punctuation"] = True
    cap["burn"] = "layer"
    cap["skip"] = []
    cap.setdefault("hook", {})["enabled"] = True
    # 全自动第一版不做需要内容支撑的卡片/画中画/插图；参考片只取字幕几何与配色。
    cfg["card"]["enabled"] = False
    cfg["pip"]["enabled"] = False
    cfg["gold"]["enabled"] = False
    cfg["inserts"]["enabled"] = False
    cfg["inserts"]["items"] = []
    cfg["segments"]["fade_out"] = 0.4
    cfg["grade"].update({
        "enabled": True,
        "eq": "eq=contrast=1.04:saturation=1.08:brightness=0.008",
        "blur": "gblur=sigma=20",
        "darken": 0.20,
    })
    mood = result.music_mood if result.music_mood in ("calm", "upbeat", "warm", "tense", "none") \
        else "warm"
    cfg["audio"]["bgm"] = {"enabled": mood != "none", "mood": mood if mood != "none" else "warm"}
    cfg["audio"]["bgm_volume"] = 0.30
    cfg["audio"]["sfx_volume"] = 0.75
    canvas = cfg["canvas"]
    ratio = "9:16" if int(canvas["height"]) >= int(canvas["width"]) else "16:9"
    cfg["jianying"].update({"name": project.name, "install": True, "ratio": ratio})
    cfg["jianying_fx"]["enabled"] = False


def _build_sfx(cfg: dict, result: auto_director.DirectorResult, plan: dict,
               total: float) -> None:
    starts: dict[str, float] = {}
    cursor = 0.0
    for shot in plan["shots"]:
        duration = float(shot["duration"])
        if shot.get("id"):
            starts[str(shot["id"])] = round(cursor, 3)
        cursor += duration
    events: list[dict] = []
    if total >= 1.0:
        events.append({"t": 0.0, "cue": "hook"})
    for i, shot in enumerate(plan["shots"][1:], 1):
        t = round(starts.get(str(shot.get("id")), 0.0), 3)
        if t <= 0.05:
            continue
        prev = plan["shots"][i - 1]
        cue = "cut" if prev.get("source") == shot.get("source") else "wipe"
        events.append({"t": t, "cue": cue})
        if len(events) >= 6:
            break
    for beat in result.beats:
        t = starts.get(str(beat.get("shot_id")))
        if t is None:
            continue
        events.append({"t": round(t, 3), "cue": beat["cue"]})
    events.sort(key=lambda item: float(item["t"]))
    dedup = []
    for event in events:
        if dedup and abs(float(event["t"]) - float(dedup[-1]["t"])) < 0.20:
            continue
        if 0 <= float(event["t"]) < total:
            dedup.append(event)
    cfg["sfx"]["events"] = dedup[:MAX_SFX]


def _plan_from_result(result: auto_director.DirectorResult, mode: str) -> dict:
    shots = []
    for i, shot in enumerate(result.shots):
        clean = _clean_shot(shot)
        clean["source"] = str(Path(clean["source"]).resolve())
        clean["transition"] = "cut"
        clean.setdefault("audio_gain", 1.0)
        clean["id"] = str(shot.get("id") or f"shot_{i + 1}")
        shots.append(clean)
    plan = {
        "version": 1, "mode": mode, "shots": shots,
        "timing": {
            "policy": "auto",
            "target_duration": None,
            "planned_duration": round(sum(float(s["duration"]) for s in shots), 3),
        },
    }
    durations = {str(Path(s["source"]).resolve()): float(probe_media(s["source"])["duration"])
                 for s in shots}
    validate_plan(plan, durations)
    return plan


def _render_cut(project: Path, cfg: dict, plan: dict) -> float:
    out = project_paths(project)["input"] / "clean-cut.mp4"
    canvas = cfg["canvas"]
    print(f"  粗剪 {len(plan['shots'])} 镜头 → {out.name}")
    result = render_plan(plan, out, canvas["width"], canvas["height"], canvas["fps"])
    cfg["input"]["video"] = "clean-cut.mp4"
    cfg["input"]["clips"] = []
    cfg["duration"] = round(float(result["duration"]), 3)
    write_json(project_paths(project)["config"], cfg)
    return cfg["duration"]


# ---------------------------------------------------------------- 执行 + 修复

def _run_pipeline(project: Path) -> int:
    print("\n  跑流水线（--auto，跳过人工听审）")
    work = project_paths(project)["work"]
    for name in ("qc-report.json", "pipeline.json", "jianying-draft.json"):
        (work / name).unlink(missing_ok=True)
    cmd = [sys.executable, str(Path(__file__).parent / "run_all.py"),
           str(project), "--auto"]
    proc = subprocess.run(cmd)
    return proc.returncode


def _fix_overlaps(path: Path, fps: int, total: float) -> bool:
    cues = parse_srt(path)
    if not cues:
        return False
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    gap = 1.0 / max(fps, 1)
    changed = False
    previous_end = 0.0
    out = []
    for cue in cues:
        start, end = float(cue["start"]), float(cue["end"])
        if start < previous_end:
            start = min(total - gap, previous_end + gap)
            changed = True
        if end <= start:
            end = min(total, start + max(gap, 0.3))
            changed = True
        previous_end = end
        out.append({"start": round(start, 3), "end": round(end, 3), "text": cue["raw"]})
    if changed:
        write_cues(out, path, force=True)
    return changed


def _repair(cfg: dict, project: Path, qc: dict, total: float) -> tuple[bool, list[str]]:
    """按 qc 红项做确定性修复；返回 (是否改了配置/素材, 说明)。"""
    fails = {str(c.get("name")) for c in _qc_fails(qc)}
    if not fails:
        return False, []
    p = project_paths(project)
    srt = p["input"] / (cfg["input"]["subtitle"] or "captions.srt")
    changed, notes = False, []

    def mark(message: str) -> None:
        nonlocal changed
        changed = True
        notes.append(message)

    if "long-silence" in fails:
        cfg["audio"].setdefault("bgm", {})["enabled"] = True
        cfg["audio"]["bgm"].setdefault("mood", "warm")
        if cfg["audio"]["bgm"]["mood"] == "none":
            cfg["audio"]["bgm"]["mood"] = "warm"
        mark("long-silence：打开 BGM 填静音")
    if "bgm-present" in fails:
        cfg["audio"].setdefault("bgm", {})["enabled"] = True
        mark("bgm-present：打开 BGM")
    if "caption-overlap" in fails and _fix_overlaps(srt, int(cfg["canvas"]["fps"]), total):
        mark("caption-overlap：收紧画面字幕时码")
    if "no-punctuation" in fails and _strip_caption_punct(srt):
        mark("no-punctuation：清掉画面字幕标点")
    if "voice-caption-cross-overlap" in fails:
        _write_empty_captions(project, cfg)
        mark("voice-caption-cross-overlap：清空画面字幕，只保留旁白字幕")
    if "voice-caption-overlap" in fails or "narration-slot-fit" in fails or \
            "narration-slot-real" in fails:
        _clean_voice(project, cfg)
        _write_empty_captions(project, cfg)
        cfg["audio"]["speech_mode"] = "none"
        mark("旁白字幕/解说槽不可用：回退无旁白 + BGM")
    if "speech-presence" in fails:
        if cfg["audio"].get("speech_mode") in ("narration", "mixed"):
            _clean_voice(project, cfg)
        _write_empty_captions(project, cfg)
        cfg["audio"]["speech_mode"] = "none"
        mark("speech-presence：回退无语音，保留 BGM/环境声")
    if "jianying-fx" in fails:
        cfg["jianying_fx"]["enabled"] = False
        mark("jianying-fx：关闭剪映原生资源声明")
    if any(name.startswith("insert-") or name == "caption-band-clearance" for name in fails):
        cfg["inserts"]["enabled"] = False
        cfg["inserts"]["items"] = []
        mark("插图质检失败：关闭插图")
    if any(name in fails for name in ("card-rendered", "card-slot", "gold-slot")):
        cfg["card"]["enabled"] = False
        cfg["pip"]["enabled"] = False
        cfg["gold"]["enabled"] = False
        mark("包装质检失败：关闭卡片/画中画/发光字")
    if "loudness" in fails or "true-peak" in fails:
        loud = cfg["audio"]["loudness"]
        loud["I"] = float(loud.get("I", -14)) - 1.0
        loud["TP"] = float(loud.get("TP", -2.6)) - 1.0
        mark("响度/真峰：目标各降 1dB 后重渲")
    if "duration" in fails:
        cfg["duration"] = resolve_duration(cfg, project)
        mark("duration：按当前粗剪回写片长")
    if "resolution" in fails or "framerate" in fails:
        try:
            info = probe_media(p["input"] / "clean-cut.mp4")
            cfg["canvas"]["width"] = int(info["width"])
            cfg["canvas"]["height"] = int(info["height"])
            cfg["canvas"]["fps"] = int(round(info["fps"])) or 30
            mark("resolution/framerate：画布改为当前粗剪规格")
        except (SystemExit, OSError, ValueError):
            pass
    if any(name in fails for name in ("no-opening-cover", "no-end-card", "no-sticky-title")):
        cfg["constraints"].update({"opening_cover": False, "end_card": False,
                                   "sticky_title": False})
        mark("房规：关闭封面/片尾卡/常驻标题")
    if fails & {"jianying-draft", "jianying-installed", "output-exists"}:
        # 没有可改的配置，但值得重跑一次草稿/渲染；交给外层循环。
        notes.append("草稿/成片缺失：重跑一次渲染与草稿")
        changed = True
    return changed, notes


def _write_decisions(project: Path, mode: str, candidates: list[dict],
                     result: auto_director.DirectorResult) -> None:
    work = project_paths(project)["work"]
    write_json(work / AUTO_DECISIONS, {
        "version": 1,
        "mode": mode,
        "source": result.source,
        "summary": result.summary(),
        "selected": [{"id": s.get("id"), "source": Path(s["source"]).name,
                      "in": s["in"], "duration": s["duration"]}
                     for s in result.shots],
        "candidates": [{"id": s.get("id"), "source": Path(s["source"]).name,
                        "in": s["in"], "duration": s["duration"],
                        "transcript": str(s.get("transcript") or "")[:300]}
                       for s in candidates],
    })
    if result.story:
        write_json(work / "auto-storyboard.json", result.story)
    if result.visual_review:
        write_json(work / "auto-visual-review.json", result.visual_review)


def _write_report(project: Path, *, mode: str, clips: list[Path], cfg: dict,
                  result: auto_director.DirectorResult, speech_mode: str,
                  notes: list[str], repairs: list[str], qc: dict | None,
                  voice: dict | None, elapsed: float) -> dict:
    work = project_paths(project)["work"]
    failed = _qc_fails(qc)
    report = {
        "version": 1,
        "mode": mode,
        "clips": [str(c) for c in clips],
        "speech_mode": speech_mode,
        "director": result.summary(),
        "narration": ({"lines": len(voice["lines"]), "skipped": voice["skipped"]}
                      if voice else None),
        "notes": notes,
        "repairs": repairs,
        "elapsed_seconds": round(elapsed, 1),
        "qc": (qc.get("summary") if qc else None),
        "qc_failed": [{"name": c.get("name"), "detail": c.get("detail")} for c in failed],
        "output": (qc or {}).get("output"),
        "draft": str(project_paths(project)["draft_store"] / cfg["jianying"]["name"]),
    }
    try:
        pipeline = json.loads((work / "pipeline.json").read_text(encoding="utf-8"))
        report["pipeline_status"] = pipeline.get("status")
        report["pipeline_automation_complete"] = pipeline.get("automation_complete")
    except (OSError, ValueError):
        report["pipeline_status"] = None
    write_json(work / AUTO_REPORT, report)
    return report


# ---------------------------------------------------------------- 宿主 Agent 导演

HOST_REQUEST = "host-director-request.json"
HOST_DECISION = "host-director-decision.json"
HOST_PROMPT = "host-director-prompt.md"

HOST_RULES = {
    "talking-head": [
        "shots 是最终播放顺序，只能引用候选 id，不能重复，不能改片段边界。",
        "只删口头填充、重复、未完句和废话；选中的总时长不得低于候选总时长的 35%。",
        "highlights 是 0–8 个关键词，必须逐字出现在候选转录里，不带标点。",
        "music_mood 只能是 calm/upbeat/warm/tense/none。",
        "beats 最多三个，shot_id 必须被选中，cue 只能是 cut/wipe/reveal。",
    ],
    "vlog": [
        "order 必须覆盖全部候选 id，不能重复；自动模式不删场景。",
        "narration 每句 1–30 字，shot_id 必须存在，evidence 必须包含该 shot_id。",
        "音乐情绪只能是 calm/upbeat/warm/tense/none。",
        "beats 最多三个，cue 只能是 cut/wipe/reveal。",
    ],
}


def _host_frames(project: Path, candidates: list[dict], mode: str) -> dict[str, str]:
    """Vlog 给宿主抽代表帧；口播主要靠转录，不抽。"""
    if mode != "vlog" or not candidates:
        return {}
    from workflow.visual_analysis import extract_frame
    work = project_paths(project)["work"]
    out_dir = work / "host-frames"
    frames = {}
    for shot in candidates[:auto_director.MAX_SHOTS]:
        target = out_dir / f"{shot['id']}.jpg"
        try:
            extract_frame(Path(shot["source"]),
                          float(shot["in"]) + float(shot["duration"]) / 2, target)
            frames[str(shot["id"])] = str(target.relative_to(project))
        except (OSError, ValueError):
            continue
    return frames


def _write_host_request(project: Path, mode: str, candidates: list[dict]) -> Path:
    work = project_paths(project)["work"]
    frames = _host_frames(project, candidates, mode)
    payload = [{"id": str(s["id"]), "duration": round(float(s["duration"]), 3),
                "transcript": str(s.get("transcript") or "")[:800]}
               for s in candidates]
    if frames:
        for row in payload:
            row["frame"] = frames.get(row["id"])
    request = {
        "version": 1,
        "mode": mode,
        "project": project.name,
        "candidates": payload,
        "transcript_text": "\n".join(str(s.get("transcript") or "") for s in candidates)[:6000],
        "rules": HOST_RULES[mode],
        "decision_schema": ("{shots:[id...],highlights:[词...],music_mood:'warm',"
                            "beats:[{shot_id:'shot_1',cue:'cut'}],notes:'...'}"
                            if mode == "talking-head" else
                            "{order:[id...],narration:[{shot_id:'shot_1',text:'...',"
                            "evidence:['shot_1']}],music_mood:'warm',"
                            "beats:[{shot_id:'shot_1',cue:'cut'}],notes:'...'}"),
        "decision_path": f"work/{HOST_DECISION}",
        "resume_command": f"koubo auto {project} --resume",
    }
    request_path = work / HOST_REQUEST
    write_json(request_path, request)
    lines = [
        f"# 宿主导演请求 · {project.name}",
        "",
        f"模式：**{mode}**。请直接根据本文件与候选转录（Vlog 还看 `work/host-frames/` 的帧）",
        "做导演决策，然后把 JSON 写到：",
        "",
        f"```text\nwork/{HOST_DECISION}\n```",
        "",
        "## 规则",
        "",
        *[f"- {rule}" for rule in HOST_RULES[mode]],
        "",
        "## 输出 JSON",
        "",
        "```json",
        request["decision_schema"],
        "```",
        "",
        f"写完后运行：`{request['resume_command']}`",
    ]
    (work / HOST_PROMPT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  宿主导演请求 → {request_path}")
    print(f"  说明 → {work / HOST_PROMPT}")
    print(f"  写好后跑：koubo auto {project} --resume")
    return request_path


def _load_host_decision(project: Path, explicit: str | None) -> dict:
    path = Path(explicit).expanduser() if explicit else project_paths(project)["work"] / HOST_DECISION
    if not path.is_file():
        raise AutoError(f"找不到宿主导演结果：{path}\n"
                        f"  先跑 --prepare，把 work/{HOST_REQUEST} 交给当前窗口的 DeepSeek/Agent，"
                        f"把决策写到 work/{HOST_DECISION}，再 --resume")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AutoError(f"宿主导演结果不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise AutoError("宿主导演结果必须是 JSON 对象")
    return data


# ---------------------------------------------------------------- 主流程

def _check_capcut() -> None:
    from make_jianying_draft import find_capcut
    try:
        find_capcut()
    except SystemExit as exc:
        raise AutoError(f"剪映草稿需要 capcut-cli：{exc}\n"
                        "  一键安装：bash install.sh（或 npm install -g capcut-cli）") from exc


def _check_llm() -> str:
    key = api_key_from_env()
    if not key:
        print("  ⚠ 没有 DEEPSEEK_API_KEY：导演决策回退本地规则；"
              "Vlog 无声时不会自动写旁白")
    return key


def main() -> None:
    ap = argparse.ArgumentParser(description="一条命令全自动成片（mp4 + 剪映草稿）")
    ap.add_argument("project")
    ap.add_argument("--video", help="单条口播/素材路径")
    ap.add_argument("--clips", nargs="+", help="多段素材路径（Vlog）")
    ap.add_argument("--reference", help="参考片；只取字幕几何、配色与布局数值")
    ap.add_argument("--mode", choices=("auto", "talking-head", "vlog"), default="auto")
    ap.add_argument("--asr-model", default=ASR_DEFAULT,
                    help=f"faster-whisper 模型（默认 {ASR_DEFAULT}；可选 large-v3）")
    ap.add_argument("--llm-model", default=LLM_DEFAULT)
    ap.add_argument("--no-llm", action="store_true", help="不调用云端模型，只用本地规则")
    ap.add_argument("--no-narration", action="store_true", help="无声素材也不生成旁白")
    ap.add_argument("--max-repairs", type=int, default=2,
                    help="质检红项的最多自动修复轮数（默认 2）")
    ap.add_argument("--force", action="store_true", help="重建配置并清掉可再生的中间产物")
    ap.add_argument("--prepare", action="store_true",
                    help="只生成候选与宿主导演请求；让当前窗口的 Agent 写 decision 后 --resume")
    ap.add_argument("--resume", action="store_true",
                    help="读取 work/host-director-decision.json 继续出片（无需 API Key）")
    ap.add_argument("--decision", help="宿主导演 decision JSON 路径（默认 work/host-director-decision.json）")
    args = ap.parse_args()
    if args.prepare and args.resume:
        ap.error("--prepare 与 --resume 只能二选一")

    started = time.time()
    project = Path(args.project).resolve()
    ensure_dirs(project)
    clips = _resolve_clips(args, project)
    if not args.prepare:
        _check_capcut()
    if args.prepare:
        print("  --prepare：生成候选与宿主导演请求，让当前窗口的 Agent 直接做决策")
    elif args.resume:
        print("  --resume：读取宿主导演结果继续，不需要 DEEPSEEK_API_KEY")
    elif args.no_llm:
        print("  --no-llm：只用本地规则，不调用云端模型")
    else:
        _check_llm()
    if args.force:
        print("  --force：重建配置并清理中间产物")
    cfg = _load_or_build_config(args, project, clips)
    mode = _resolve_mode(clips, args.mode)
    cfg["mode"] = mode
    print(f"  素材 {len(clips)} 条 / 模式 {mode} / 画布 {cfg['canvas']['width']}x"
          f"{cfg['canvas']['height']}")

    work = project_paths(project)["work"]
    info = {str(clip): probe_media(clip) for clip in clips}
    records: dict[str, dict | None] = {}
    if mode == "talking-head" or _asr_available():
        for clip in clips:
            records[str(clip)] = _transcribe_clip(
                clip, args.asr_model, work, required=(mode == "talking-head"))
    try:
        if mode == "talking-head":
            shots = talking_head_shots(
                clips, info, pad=0.12, merge_gap=0.55, lead=0.70, tail=0.15)
        else:
            shots = vlog_shots(clips, info)
            shots = _merge_scene_candidates(shots)
    except (ValueError, SystemExit) as exc:
        raise AutoError(f"无法生成候选镜头：{exc}") from exc
    candidates = []
    for index, shot in enumerate(shots, 1):
        record = records.get(str(Path(shot["source"]).resolve()))
        text = _words_text(record, float(shot["in"]),
                           float(shot["in"]) + float(shot["duration"]))
        candidates.append({**shot, "id": f"shot_{index}", "transcript": text})
    if not candidates:
        raise AutoError("没有生成候选镜头；检查素材是否有可检测的说话段/场景")

    if args.prepare:
        _write_host_request(project, mode, candidates)
        return

    transcript_text = "\n".join(str(c.get("transcript") or "") for c in candidates)
    if args.resume:
        decision = _load_host_decision(project, args.decision)
        try:
            result = auto_director.from_host(candidates, mode, decision)
        except ValueError as exc:
            raise AutoError(f"宿主导演结果校验失败：{exc}") from exc
    else:
        key = None if args.no_llm else api_key_from_env()
        result = auto_director.direct(
            candidates, mode, transcript_text=transcript_text,
            api_key=key, model=args.llm_model)
    print(f"  导演决策：{result.source} / {len(result.shots)} 镜头"
          + (f" / 高亮 {len(result.highlights)}" if result.highlights else "")
          + (f" / 旁白 {len(result.narration)}" if result.narration else ""))
    for note in result.notes:
        print(f"    · {note}")

    try:
        plan = _plan_from_result(result, mode)
    except (ValueError, SystemExit) as exc:
        raise AutoError(f"镜头表校验失败：{exc}") from exc
    write_json(work / "edit-plan.json", plan)
    try:
        total = _render_cut(project, cfg, plan)
    except (ValueError, SystemExit) as exc:
        raise AutoError(f"粗剪失败：{exc}") from exc
    _configure_style(cfg, project, result, mode)
    speech_mode, speech_notes, voice = _prepare_voice(
        project, cfg, mode, result, plan,
        project_paths(project)["input"] / "clean-cut.mp4",
        total, args.asr_model, args.no_narration)
    _build_sfx(cfg, result, plan, total)
    write_json(project_paths(project)["config"], cfg)
    _write_decisions(project, mode, candidates, result)
    print(f"  语音：{speech_mode}")

    repairs: list[str] = []
    rc = _run_pipeline(project)
    qc = _read_qc(project)
    for _ in range(max(args.max_repairs, 0)):
        if qc and not _qc_fails(qc):
            break
        if not qc:
            break
        changed, notes = _repair(cfg, project, qc, total)
        if not changed:
            break
        repairs.extend(notes)
        write_json(project_paths(project)["config"], cfg)
        print(f"  自动修复 {len(notes)} 项：" + "；".join(notes))
        rc = _run_pipeline(project)
        qc = _read_qc(project)

    # 修复可能把语音从 narration/source 改成 none；报告以最终配置为准。
    speech_mode = str(cfg.get("audio", {}).get("speech_mode") or speech_mode)
    if speech_mode != "narration":
        voice = None
    report = _write_report(project, mode=mode, clips=clips, cfg=cfg,
                           result=result, speech_mode=speech_mode,
                           notes=speech_notes + result.notes + repairs,
                           repairs=repairs, qc=qc, voice=voice,
                           elapsed=time.time() - started)
    failed = _qc_fails(qc)
    if qc is None:
        print("  ✗ 没有拿到 work/qc-report.json；本轮不能算自动交付")
        rc = 1
    print(f"\n自动报告 → {project_paths(project)['work'] / AUTO_REPORT}")
    if report.get("output"):
        print(f"  成片 → {report['output']}")
    print(f"  草稿 → {report['draft']}")
    if failed:
        print(f"  ✗ 仍有 {len(failed)} 项质检红项："
              + "、".join(str(c.get("name")) for c in failed[:8]))
        raise SystemExit(1)
    if rc != 0:
        raise SystemExit(rc)
    print("  ✓ 全自动成片完成（质检无红项；具体三态见 work/qc-report.json）")


if __name__ == "__main__":
    try:
        main()
    except AutoError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        raise SystemExit(2)
