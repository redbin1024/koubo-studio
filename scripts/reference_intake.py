#!/usr/bin/env python3
"""参考片入库：一条抖音链接（或本机文件）→ 可复核的参考片档案。

    koubo reference "https://v.douyin.com/xxxx/" -p my-video
    koubo reference ~/Movies/参考片.mp4 -o work/ref-analysis --no-llm

产出（默认写入 `work/reference-intake/`，给 `-p` 时写入 `<工程>/work/reference/`）：

    source.json        来源、作品元信息、实际下载地址、告警
    douyin.mp4         原片（仅链接来源；本地文件不复制）
    pacing.json        自适应切点、镜长分布、VFR、响度
    teardown.json      字幕带 / 强调色 / 卡片 / 画中画几何
    shots.json         镜头表 + 首/中/尾三联图 + ≤15s 分段
    frames/            strip-XX.jpg（左/中/右）与 shot-XX.jpg
    contact-sheet.jpg  所有镜头总览
    transcript.json    本地 ASR 逐词证据（装了 faster-whisper 时）
    transcript.srt     由逐词证据生成的字幕
    breakdown.json     全片结构 + 逐镜语义（有 DEEPSEEK_API_KEY 时）
    reference-profile.json  稳定的下游契约
    REPORT.md          人看的报告

三态原则：装不了 ASR、没有 Key、某批拆解失败，都会写进 `unchecked` 并说明原因，
不会从报告里消失，也不会把「没查」写成「通过」。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from _common import probe_media, write_json  # noqa: E402
from workflow import reference_shots as shots_lib  # noqa: E402
from workflow import reference_vision as vision  # noqa: E402
from workflow.pacing import report as pacing_report  # noqa: E402
from workflow.reference_source import ReferenceSourceError, fetch_reference  # noqa: E402

SCHEMA = "koubo-reference/1"
PROFILE_NAME = "reference-profile.json"
REPORT_NAME = "REPORT.md"


# ------------------------------------------------------------------ 小工具

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _signature(path: Path) -> dict:
    try:
        stat = path.stat()
    except OSError:
        return {}
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime": int(stat.st_mtime)}


def _same_source(source: dict | None, value: str, video: Path | None) -> bool:
    if not source or not video or not video.is_file():
        return False
    old = source.get("input")
    if str(old or "") != str(value):
        return False
    sig = source.get("signature") or {}
    if sig and sig.get("size") and sig.get("size") != video.stat().st_size:
        return False
    return True


def _safe_unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


def _clean_analysis(out: Path) -> None:
    for name in ("pacing.json", "teardown.json", "shots.json", "transcript.json",
                 "transcript.srt", "breakdown.json", PROFILE_NAME, REPORT_NAME,
                 "ref-frames", "frames"):
        target = out / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            _safe_unlink(target)


# ------------------------------------------------------------------ 各步骤

def _fetch(source: str, out: Path, *, project: Path | None, force: bool,
           cookie: str | None, engine: str, log) -> tuple[dict, Path]:
    cached = _read_json(out / "source.json")
    if cached and not force:
        video = Path(cached.get("video") or "")
        if _same_source(cached, source, video):
            log(f"  复用已下载的原片：{video}")
            return cached, video
    if force:
        # 只清下载产物；分析产物由 _clean_analysis 负责。
        for candidate in (out / "douyin" / "douyin.mp4", out / "yt-dlp"):
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)
            else:
                _safe_unlink(candidate)
    log(f"  取参考片：{source}")
    result = fetch_reference(source, out, cookie=cookie, engine=engine, log=log)
    video = Path(result["video"])
    result["fetched_at"] = _now()
    result["signature"] = _signature(video)
    result["project"] = str(project) if project else None
    write_json(out / "source.json", result)
    return result, video


def _pacing(video: Path, out: Path, *, force: bool, log) -> dict:
    cached = _read_json(out / "pacing.json")
    if cached and not force:
        log("  复用节奏分析")
        return cached
    log("  分析节奏与切点…")
    data = pacing_report(video)
    write_json(out / "pacing.json", data)
    log(f"  {data['pacing']['shot_count']} 个镜头 / "
        f"{data['pacing']['cuts_per_minute']} 切/分钟")
    return data


def _teardown(video: Path, out: Path, *, force: bool, log) -> tuple[dict | None, str | None]:
    target = out / "teardown.json"
    if target.is_file() and not force:
        log("  复用视觉几何拆解")
        return _read_json(target), None
    log("  量字幕带 / 强调色 / 卡片 / 画中画…")
    proc = subprocess.run([
        sys.executable, str(SCRIPTS / "analyze_reference.py"), str(video),
        "--out", str(target), "--frames", str(out / "ref-frames"),
        "--scene-threshold", "0.12",
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-4:])
        return None, f"视觉几何拆解失败：{tail or 'analyze_reference.py 非零退出'}"
    return _read_json(target), None


def _shots(video: Path, pacing: dict, out: Path, *, force: bool, min_shot: float,
           max_beat: float, max_shots: int, extra_cuts: list[dict] | None = None,
           analyze_seconds: float | None = None,
           log) -> tuple[list[dict], list[dict], str | None]:
    cached = _read_json(out / "shots.json")
    if cached and not force:
        rows = cached.get("shots") or []
        if rows and all((out / (row.get("strip") or "")).is_file() for row in rows):
            log(f"  复用 {len(rows)} 个镜头与三联图")
            return rows, cached.get("segments") or [], cached.get("contact_sheet")
    log("  切镜并抽首/中/尾三联图…")
    # 自适应阈值在「几乎每一帧都是切点」的短片上会把自己抬得过高；
    # 用固定阈值的拆解切点补一刀，再交给 min_shot / max_shots 去噪。
    cuts = list(pacing.get("cuts") or []) + list(extra_cuts or [])
    duration = float(analyze_seconds or pacing.get("duration") or 0)
    rows = shots_lib.build_shots(cuts, duration,
                                 min_shot=min_shot, max_beat=max_beat,
                                 max_shots=max_shots)
    rows = shots_lib.extract_strips(video, rows, out, log=log)
    segments = shots_lib.plan_segments(rows)
    sheet = shots_lib.contact_sheet(rows, out)
    sheet_rel = None
    if sheet:
        try:
            sheet_rel = str(Path(sheet).resolve().relative_to(out))
        except ValueError:
            sheet_rel = None
    write_json(out / "shots.json", {
        "schema": "koubo-reference-shots/1", "video": str(video),
        "count": len(rows), "shots": rows, "segments": segments,
        "contact_sheet": sheet_rel, "generated_at": _now(),
    })
    log(f"  {len(rows)} 镜 / {len(segments)} 段（每段 ≤15s）"
        + ("" if sheet_rel else "；接触表未生成"))
    return rows, segments, sheet_rel


def _transcript_from_words(words: list[dict]) -> str:
    text = "".join(str(w.get("text") or "") for w in words)
    text = re.sub(r"[ \t]+", " ", text).strip()
    # 中文词之间不需要空格；英文单词之间保留。
    text = re.sub(r"\s+(?=[\u3400-\u9fff，。！？、；：])", "", text)
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+", "", text)
    return text


def _transcribe(video: Path, out: Path, *, enabled: bool, force: bool,
                model: str, duration: float, log) -> tuple[dict | None, str | None]:
    if not enabled:
        return None, "使用了 --no-asr，没有转写口播；钩子/CTA 只能靠画面判断"
    cached = _read_json(out / "transcript.json")
    if cached and not force:
        log(f"  复用转写（{cached.get('status')}，{len(cached.get('words') or [])} 词）")
        return cached, None
    log(f"  本地转写口播（faster-whisper {model}）…")
    try:
        from transcribe_audio import transcribe
        data = transcribe(video, out / "transcript.json", model)
    except RuntimeError as exc:
        if "faster-whisper" in str(exc):
            return None, "缺少 faster-whisper，未转写口播；`pip install faster-whisper` 后重跑"
        return None, f"口播转写失败：{exc}"
    except Exception as exc:  # 模型下载/解码失败都只影响转写
        return None, f"口播转写失败：{exc}"
    words = data.get("words") or []
    text = _transcript_from_words(words)
    data["text"] = text
    data["chars"] = len(text.replace(" ", ""))
    data["chars_per_minute"] = (round(data["chars"] / duration * 60, 1)
                                if duration > 0 else None)
    data["hook"] = _transcript_from_words([w for w in words if float(w.get("start") or 0) < 3.0])
    data["cta"] = _transcript_from_words(
        [w for w in words if float(w.get("start") or 0) >= max(0.0, duration - 3.0)])
    write_json(out / "transcript.json", data)
    if data.get("status") == "ok":
        try:
            from auto_captions import write_transcript
            write_transcript(data, out / "transcript.srt", force=True)
        except (ValueError, OSError) as exc:
            log(f"  字幕生成失败（不影响拆解）：{exc}")
    log(f"  {data.get('status')}：{len(words)} 词 / {data.get('chars')} 字")
    return data, None


def _vision(rows: list[dict], out: Path, *, enabled: bool, force: bool,
            model: str, pacing: dict, transcript: dict | None, source: dict,
            max_shots: int, log) -> tuple[dict, str | None]:
    if not enabled:
        return {"status": "unchecked", "overview": None, "shots": {},
                "warnings": [], "usage": {}}, "使用了 --no-llm，镜头语义未拆解"
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return {"status": "unchecked", "overview": None, "shots": {},
                "warnings": [], "usage": {}}, "缺少 DEEPSEEK_API_KEY，镜头语义未拆解"
    cached = _read_json(out / "breakdown.json")
    if cached and not force:
        log(f"  复用视觉拆解（{cached.get('status')}）")
        return cached, None
    log(f"  视觉拆解 {min(len(rows), max_shots)} 镜…")
    text = (transcript or {}).get("text") or ""
    try:
        data = vision.analyze(rows, out, api_key=key, model=model,
                              pacing=(pacing or {}).get("pacing"),
                              transcript=text, meta=(source or {}).get("meta") or {},
                              max_shots=max_shots, log=log)
    except vision.VisionError as exc:
        return {"status": "unchecked", "overview": None, "shots": {},
                "warnings": [str(exc)], "usage": {}}, str(exc)
    data["generated_at"] = _now()
    write_json(out / "breakdown.json", data)
    log(f"  拆解 {len([v for v in data.get('shots', {}).values() if not v.get('unchecked')])}"
        f" 镜 / 全片结构 {'有' if data.get('overview') else '无'}")
    return data, None


# ------------------------------------------------------------------ 汇总

def _palette(teardown: dict | None) -> dict:
    by_hue: dict[str, str] = {}
    for color in (teardown or {}).get("accent_colors") or []:
        if isinstance(color, dict) and color.get("hue") and color.get("hex"):
            by_hue.setdefault(str(color["hue"]), str(color["hex"]))
    accent = by_hue.get("yellow")
    contrast = (by_hue.get("pink") or by_hue.get("magenta")
                or by_hue.get("violet") or by_hue.get("red"))
    return {"accent": accent, "contrast": contrast, "by_hue": by_hue}


def _style_block(teardown: dict | None, probe: dict) -> dict:
    palette = _palette(teardown)
    band = (teardown or {}).get("caption_band") or {}
    card = (teardown or {}).get("card")
    rejected = None
    if isinstance(card, dict):
        try:
            too_large = float(card.get("area") or 0) > 0.55
        except (TypeError, ValueError):
            too_large = False
        if too_large:
            rejected = card
            card = None
    pip = (teardown or {}).get("pip")
    flat = sorted(((teardown or {}).get("flat_bands") or []),
                  key=lambda row: row.get("gradient", 999))[:4]
    hints: dict = {}
    if palette["accent"]:
        hints["captions.palette.accent"] = palette["accent"]
    if palette["contrast"]:
        hints["captions.palette.contrast"] = palette["contrast"]
    if isinstance(card, dict):
        hints["card.enabled"] = True
        hints["card.start"] = card.get("start")
        hints["card.end"] = card.get("end")
        hints["card.box"] = card.get("bbox_norm")
        hints["card.fill"] = card.get("fill_hex")
        if isinstance(pip, dict) and card:
            hints["pip.enabled"] = True
            hints["pip.box"] = pip.get("bbox_norm")
            hints["pip.at"] = round(float(card.get("start") or 0) + 0.02, 3)
    return {
        "aspect": "9:16" if (probe.get("height") or 0) >= (probe.get("width") or 0) else "16:9",
        "accent_colors": (teardown or {}).get("accent_colors") or [],
        "palette_hint": {"accent": palette["accent"], "contrast": palette["contrast"]},
        "caption_band": band,
        "caption_band_note": ("字幕带只给几何；不要用 y_bottom_norm 反推 margin_v，"
                              "要用字幕墨迹下沿重新量。"),
        "card": card,
        "card_rejected": rejected,
        "pip": pip,
        "flat_bands": flat,
        "config_hints": hints,
        "font_note": "字体族、字号、描边宽度无法从像素可靠反推，需人工核对。",
    }


def _pacing_block(pacing: dict, rows: list[dict], analysis_duration: float | None = None) -> dict:
    values = sorted(float(s.get("duration") or 0) for s in rows)
    def pick(ratio: float) -> float | None:
        if not values:
            return None
        return round(values[min(len(values) - 1, max(0, int(len(values) * ratio)))], 3)
    pacing = pacing or {}
    stats = pacing.get("pacing") or {}
    used_cuts = max(0, len(rows) - 1)
    used_median = round(values[len(values) // 2], 3) if values else None
    effective = analysis_duration or pacing.get("duration")
    return {
        "duration": pacing.get("duration"),
        "analysis_duration": effective,
        "width": pacing.get("width"),
        "height": pacing.get("height"),
        "fps": pacing.get("avg_fps"),
        "vfr_suspect": pacing.get("vfr_suspect"),
        "loudness": pacing.get("loudness"),
        "shot_count": stats.get("shot_count"),
        "cut_count": stats.get("cut_count"),
        "cuts_per_minute": stats.get("cuts_per_minute"),
        "avg_shot_duration": stats.get("avg_shot_duration"),
        "median_shot_duration": stats.get("median_shot_duration"),
        "min_shot_duration": stats.get("min_shot_duration"),
        "max_shot_duration": stats.get("max_shot_duration"),
        "shot_seconds_p10": pick(0.1),
        "shot_seconds_p50": pick(0.5),
        "shot_seconds_p90": pick(0.9),
        "used_shot_count": len(rows),
        "used_cut_count": used_cuts,
        "used_cuts_per_minute": (round(used_cuts / float(effective) * 60, 2)
                                 if effective else None),
        "used_median_shot_duration": used_median,
        "used_min_shot_duration": min(values) if values else None,
        "used_max_shot_duration": max(values) if values else None,
        "beat_note": "超过 5 秒的长镜头已按 beat 拆开，避免一张三联图代表整段动作。",
    }


def _transcript_block(transcript: dict | None, reason: str | None) -> dict:
    if not transcript:
        return {"status": "unchecked", "reason": reason or "未转写"}
    return {
        "status": transcript.get("status"),
        "model": transcript.get("model"),
        "language": transcript.get("language"),
        "duration": transcript.get("duration"),
        "words": len(transcript.get("words") or []),
        "chars": transcript.get("chars"),
        "chars_per_minute": transcript.get("chars_per_minute"),
        "hook": transcript.get("hook") or None,
        "cta": transcript.get("cta") or None,
        "text": transcript.get("text") or "",
        "srt": "transcript.srt" if (transcript.get("status") == "ok") else None,
    }


def _coverage(unchecked: list[dict], breakdown: dict, transcript: dict | None,
              teardown: dict | None, rows: list[dict]) -> dict:
    analyzed = sum(1 for _id, rec in (breakdown.get("shots") or {}).items()
                   if isinstance(rec, dict) and not rec.get("unchecked"))
    return {
        "shots": len(rows),
        "shots_with_strip": sum(1 for s in rows if s.get("status") == "ok"),
        "shots_analyzed": analyzed,
        "visual_geometry": bool(teardown),
        "transcript": (transcript or {}).get("status") if transcript else "unchecked",
        "overview": bool(breakdown.get("overview")),
        "unchecked_items": len(unchecked),
    }


def _adaptations(pacing: dict, style: dict, transcript: dict | None,
                 overview: dict | None, rows: list[dict]) -> list[str]:
    out: list[str] = []
    if overview:
        out.extend(overview.get("adaptation") or [])
    rpm = pacing.get("used_cuts_per_minute") or pacing.get("cuts_per_minute")
    if rpm is not None and rpm >= 40:
        out.append(f"切点密度 {rpm}/分钟，节奏很快：复刻时优先保 1.5–2.5 秒的镜头，"
                   "不要为了多放信息把镜头拉长。")
    elif rpm is not None and rpm <= 12:
        out.append(f"切点密度 {rpm}/分钟，属于慢节奏：靠机位、景别和字幕变化撑住，"
                   "不要加无意义的快切。")
    band = style.get("caption_band") or {}
    if band.get("detected"):
        out.append("字幕带位置已量到（见 caption_band），但 margin_v 要用字幕墨迹下沿重算；"
                   "先把字幕烧一版再对位置。")
    if style.get("card"):
        out.append("卡片几何已量到，可直接填 config.card；圆角、描边、阴影只能目测补齐。")
    if (transcript or {}).get("hook"):
        out.append("前 3 秒口播钩子："
                   + str(transcript["hook"])[:80] + "；保留信息顺序，不要换成自我介绍。")
    if not rows:
        out.append("没有切出镜头，复刻节奏前先确认视频是否有画面。")
    return out[:10]


def build_profile(*, source: dict, probe: dict, pacing: dict, teardown: dict | None,
                  rows: list[dict], segments: list[dict], contact_sheet: str | None,
                  transcript: dict | None, breakdown: dict, unchecked: list[dict],
                  generated_at: str, analysis_duration: float | None = None) -> dict:
    style = _style_block(teardown, probe)
    pacing_block = _pacing_block(pacing, rows, analysis_duration)
    transcript_block = _transcript_block(transcript, _reason_for(unchecked, "口播转写"))
    overview = breakdown.get("overview")
    vision_map = breakdown.get("shots") or {}
    out_shots = []
    for shot in rows:
        record = {
            key: shot.get(key) for key in
            ("id", "index", "start", "end", "duration", "cut", "status", "strip",
             "keyframe", "strip_times")
            if key in shot
        }
        analyzed = vision_map.get(shot["id"])
        if isinstance(analyzed, dict) and not analyzed.get("unchecked"):
            record["analysis"] = analyzed
            record["analysis_status"] = "ok"
        else:
            record["analysis_status"] = "unchecked"
            record["analysis_reason"] = (
                (analyzed or {}).get("reason") if isinstance(analyzed, dict) else None
            ) or "未做视觉拆解"
        out_shots.append(record)
    status = "ok" if teardown and rows else "partial"
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "status": status,
        "source": {
            "platform": source.get("platform"),
            "engine": source.get("engine"),
            "input": source.get("input"),
            "resolved_url": source.get("resolved_url"),
            "aweme_id": source.get("aweme_id"),
            "fetched_at": source.get("fetched_at"),
            "meta": source.get("meta") or {},
            "warnings": source.get("warnings") or [],
        },
        "video": probe,
        "pacing": pacing_block,
        "style": style,
        "transcript": transcript_block,
        "shots": out_shots,
        "segments": segments,
        "breakdown": {
            "status": breakdown.get("status"),
            "overview": overview,
            "warnings": breakdown.get("warnings") or [],
            "usage": breakdown.get("usage") or {},
        },
        "recommendations": {
            "pacing_targets": {
                "cuts_per_minute": pacing_block.get("used_cuts_per_minute"),
                "median_shot_duration": pacing_block.get("used_median_shot_duration"),
                "shot_seconds_p10": pacing_block.get("shot_seconds_p10"),
                "shot_seconds_p90": pacing_block.get("shot_seconds_p90"),
                "adaptive_shot_count": pacing_block.get("shot_count"),
            },
            "copy": {
                "hook": (transcript_block.get("hook") if transcript_block["status"] != "unchecked"
                         else None),
                "cta": (transcript_block.get("cta") if transcript_block["status"] != "unchecked"
                        else None),
            },
            "config_hints": style["config_hints"],
            "adaptations": _adaptations(pacing_block, style, transcript, overview, rows),
        },
        "coverage": _coverage(unchecked, breakdown, transcript, teardown, rows),
        "unchecked": unchecked,
        "artifacts": {
            "source": "source.json",
            "pacing": "pacing.json",
            "teardown": "teardown.json" if teardown else None,
            "shots": "shots.json",
            "contact_sheet": contact_sheet,
            "transcript": "transcript.json" if transcript else None,
            "transcript_srt": transcript_block.get("srt"),
            "breakdown": "breakdown.json" if breakdown.get("overview") or breakdown.get("shots") else None,
            "report": REPORT_NAME,
        },
    }


def _reason_for(unchecked: list[dict], item: str) -> str | None:
    for entry in unchecked:
        if entry.get("item") == item:
            return entry.get("reason")
    return None


# ------------------------------------------------------------------ 报告

def _cell(value, limit: int = 120) -> str:
    text = str(value if value is not None else "").replace("\r", " ").replace("\n", " ").strip()
    text = text.replace("|", "\\|")
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    return text or "—"


def _report(profile: dict, out: Path) -> str:
    src = profile["source"]
    video = profile["video"]
    pacing = profile["pacing"]
    style = profile["style"]
    transcript = profile["transcript"]
    overview = profile["breakdown"].get("overview") or {}
    recommendations = profile["recommendations"]
    meta = src.get("meta") or {}
    lines: list[str] = []
    add = lines.append

    add("# 参考片拆解报告")
    add("")
    add(f"生成时间：{profile['generated_at']}  ")
    add(f"来源：{src.get('platform')} / {src.get('engine')}  ")
    if src.get("input"):
        add(f"输入：`{_cell(src['input'], 300)}`  ")
    if meta.get("author"):
        add(f"作者：{_cell(meta['author'])}  ")
    add(f"标题：{_cell(meta.get('title'), 180)}")
    add("")
    add("> 这份报告只描述**这条参考片**量到了什么、看到了什么。")
    add("> 没装 ASR、没有 Key、某批拆解失败，都会列在文末「未检查」，")
    add("> 不会从报告里消失。参考片只用来取数和拆结构，任何一帧都不进成片。")
    add("")

    add("## 技术参数")
    add("")
    add("| 项 | 值 |")
    add("| --- | --- |")
    add(f"| 文件时长 | {video.get('duration')}s |")
    if pacing.get("analysis_duration") and abs(float(pacing["analysis_duration"])
                                               - float(video.get("duration") or 0)) > 1:
        add(f"| 分析时长 | {pacing['analysis_duration']:.2f}s（切镜/节奏按此计算） |")
    add(f"| 画布 | {video.get('width')}×{video.get('height')}（{style['aspect']}） |")
    add(f"| 帧率 | {video.get('fps')} fps{'（疑似 VFR）' if pacing.get('vfr_suspect') else ''} |")
    add(f"| 编码 | {video.get('video_codec')} + {video.get('audio_codec') or '无音轨'} |")
    if pacing.get("loudness"):
        ln = pacing["loudness"]
        add(f"| 响度 | {ln.get('input_i')} LUFS / 真峰 {ln.get('input_tp')} dBTP |")
    add(f"| 实际切镜 | {pacing.get('used_shot_count')} 镜 / {pacing.get('used_cut_count')} 个切点 |")
    add(f"| 自适应切点 | {pacing.get('shot_count')} 镜（pacing 原始结果，仅作对照） |")
    add("")

    add("## 节奏")
    add("")
    add(f"- 每分钟切点：**{pacing.get('used_cuts_per_minute')}**"
        f"（pacing 自适应原始值 {pacing.get('cuts_per_minute')}）")
    add(f"- 中位镜头：**{pacing.get('used_median_shot_duration')}s**"
        f"（P10 {pacing.get('shot_seconds_p10')}s / P90 {pacing.get('shot_seconds_p90')}s）")
    add(f"- 最短 / 最长：{pacing.get('used_min_shot_duration')}s / {pacing.get('used_max_shot_duration')}s")
    add(f"- {pacing.get('beat_note')}")
    add("")

    add("## 视觉风格（量出来的，不是猜的）")
    add("")
    colors = style.get("accent_colors") or []
    if colors:
        add("| 强调色 | 色相 | 像素数 |")
        add("| --- | --- | --- |")
        for color in colors[:8]:
            add(f"| `{color.get('hex')}` | {color.get('hue')} | {color.get('count', '—')} |")
        add("")
    else:
        add("- 没有检出稳定的强调色。")
    band = style.get("caption_band") or {}
    if band.get("detected"):
        add(f"- 字幕带：y {band.get('y_top_norm')}–{band.get('y_bottom_norm')}，"
            f"x {band.get('x_min_norm')}–{band.get('x_max_norm')}；"
            f"{style.get('caption_band_note')}")
    else:
        add("- 没有检出自动字幕带（可能是无字幕或字幕不是白字黑边）。")
    card = style.get("card")
    if style.get("card_rejected"):
        add(f"- 卡片：检出的色块占画面 "
            f"{float(style['card_rejected'].get('area') or 0):.0%}，更像满屏背景而不是信息卡；"
            "没有写进 config 建议。")
    elif card:
        add(f"- 卡片：{card.get('start')}–{card.get('end')}s，"
            f"bbox {card.get('bbox_norm')}，填充 `{card.get('fill_hex')}`；"
            "圆角与描边需目测。")
    else:
        add("- 没有检出长时段稳定的大色块卡片。")
    if style.get("pip"):
        add(f"- 画中画：bbox {style['pip'].get('bbox_norm')}（保守内框，外沿需微调）。")
    if style.get("flat_bands"):
        add("- 最平的安全带（字幕优先放这里）："
            + "、".join(f"{x.get('y_from')}–{x.get('y_to')}" for x in style["flat_bands"]))
    add(f"- {style.get('font_note')}")
    add("")

    add("## 镜头表")
    add("")
    if profile.get("artifacts", {}).get("contact_sheet"):
        add(f"![contact sheet]({profile['artifacts']['contact_sheet']})")
        add("")
    add("每镜三联图：左 = 切入后，中 = 中点，右 = 切出前。")
    add("")
    add("| # | 时间 | 景别 | 运镜 | 动作 | 画面文字 | 证据/状态 |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for shot in profile["shots"]:
        analysis = shot.get("analysis") or {}
        label = f"[{shot['id']}]({shot.get('strip')})" if shot.get("strip") else shot["id"]
        if analysis:
            add(f"| {label} | {shot['start']:.2f}–{shot['end']:.2f}s "
                f"({shot['duration']:.2f}s) | {_cell(analysis.get('shot_size'))} | "
                f"{_cell(analysis.get('camera'))} | {_cell(analysis.get('action'))} | "
                f"{_cell(analysis.get('on_screen_text'))} | {_cell(analysis.get('evidence'))} |")
        else:
            add(f"| {label} | {shot['start']:.2f}–{shot['end']:.2f}s "
                f"({shot['duration']:.2f}s) | unchecked | unchecked | "
                f"{_cell(shot.get('analysis_reason'))} | — | — |")
    add("")

    add("## 口播与结构")
    add("")
    if transcript.get("status") == "unchecked":
        add(f"- 未转写：{transcript.get('reason')}")
    elif transcript.get("status") == "no_speech":
        add("- 没有识别到可用的中文人声（不代表一定没有音乐或音效）。")
    else:
        add(f"- 转写：{transcript.get('words')} 词 / {transcript.get('chars')} 字 / "
            f"{transcript.get('chars_per_minute')} 字每分钟")
        if transcript.get("hook"):
            add(f"- 前 3 秒钩子：{transcript['hook']}")
        if transcript.get("cta"):
            add(f"- 最后 3 秒：{transcript['cta']}")
        if transcript.get("srt"):
            add(f"- 字幕：`{transcript['srt']}`")
    add("")
    if overview:
        add(f"- **钩子**：{overview.get('hook')}")
        add(f"- **结构**：{overview.get('structure')}")
        add(f"- **画面风格**：{overview.get('visual_style')}")
        add(f"- **节奏**：{overview.get('rhythm')}")
        add(f"- **声音**：{overview.get('audio')}")
        add(f"- **受众**：{overview.get('target_audience')}")
        add("")
        if overview.get("why_it_works"):
            add("**为什么成立**")
            add("")
            for item in overview["why_it_works"]:
                add(f"- {item}")
            add("")
    else:
        add("- 全片结构未拆解（见文末未检查项）。")
        add("")

    add("## 怎么借鉴")
    add("")
    if recommendations.get("adaptations"):
        for item in recommendations["adaptations"]:
            add(f"- {item}")
    else:
        add("- 暂无自动建议；先看镜头表与节奏数字。")
    add("")
    if profile["style"].get("config_hints"):
        add("可直接抄进 `config.json` 的数值（抄之前先看字段说明）：")
        add("")
        add("```json")
        add(json.dumps(profile["style"]["config_hints"], ensure_ascii=False, indent=2))
        add("```")
        add("")

    add("## 未检查")
    add("")
    unchecked = profile.get("unchecked") or []
    if unchecked:
        add("| 项 | 原因 |")
        add("| --- | --- |")
        for entry in unchecked:
            add(f"| {_cell(entry.get('item'))} | {_cell(entry.get('reason'), 240)} |")
    else:
        add("无。仍然不代表语义拆解必然正确，关键镜头要人眼复核。")
    add("")

    add("## 产物")
    add("")
    for name, rel in (profile.get("artifacts") or {}).items():
        if rel:
            target = out / rel
            add(f"- `{name}` → `{rel}`" + ("" if target.exists() else "（缺失）"))
    add("")
    add("---")
    add("")
    add("方法参考 `Joho6666/video-replicate-studio` 的「抓取 → 切镜 → 导演拆解」流程；")
    add("本报告由口播工坊的本地测量 + 可选 DeepSeek 视觉拆解生成。")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ 主流程

def run(source: str, out: str | Path, *, project: str | Path | None = None,
        cookie: str | None = None, engine: str = "auto", no_asr: bool = False,
        asr_model: str = "small", no_llm: bool = False,
        llm_model: str = "deepseek-flash", max_shots: int = 30,
        min_shot: float = shots_lib.MIN_SHOT, max_beat: float = shots_lib.MAX_BEAT,
        force: bool = False, pick_font: bool = False, font_library: str = "auto",
        log=print) -> dict:
    out = Path(out).resolve()
    project_path = Path(project).resolve() if project else None
    out.mkdir(parents=True, exist_ok=True)
    if force:
        _clean_analysis(out)
    log(f"参考片入库 → {out}")

    unchecked: list[dict] = []
    log("[1/6] 取参考片")
    try:
        src, video = _fetch(str(source), out, project=project_path, force=force,
                            cookie=cookie, engine=engine, log=log)
    except ReferenceSourceError as exc:
        raise SystemExit(f"取参考片失败：{exc}") from exc
    for warning in src.get("warnings") or []:
        unchecked.append({"item": "来源告警", "reason": str(warning)})

    try:
        probe = probe_media(video)
    except SystemExit as exc:
        raise SystemExit(f"参考片读不了：{exc}") from exc
    duration = float(probe.get("duration") or 0)

    log("[2/6] 节奏与视觉几何")
    pacing = _pacing(video, out, force=force, log=log)
    teardown, teardown_error = _teardown(video, out, force=force, log=log)
    if teardown_error:
        unchecked.append({"item": "视觉几何（字幕带/强调色/卡片/画中画）",
                          "reason": teardown_error})
    card = (teardown or {}).get("card")
    if isinstance(card, dict):
        try:
            if float(card.get("area") or 0) > 0.55:
                unchecked.append({
                    "item": "卡片几何",
                    "reason": f"检出的色块占画面 {float(card.get('area')):.0%}，"
                              "更像满屏背景而不是信息卡，已从 config 建议里剔除"})
        except (TypeError, ValueError):
            pass

    log("[3/6] 切镜与三联图")
    file_duration = float(pacing.get("duration") or duration)
    meta_duration = (src.get("meta") or {}).get("duration")
    analysis_limit = file_duration
    try:
        meta_duration = float(meta_duration) if meta_duration else None
    except (TypeError, ValueError):
        meta_duration = None
    if meta_duration and 0 < meta_duration < file_duration - 1.0:
        analysis_limit = meta_duration
        unchecked.append({
            "item": "分析区间",
            "reason": f"作品元信息 {meta_duration:.2f}s，下载文件 {file_duration:.2f}s；"
                      "切镜只到元信息时长，排除 App 追加的尾部"})
    rows, segments, sheet = _shots(video, pacing, out, force=force, min_shot=min_shot,
                                   max_beat=max_beat, max_shots=max_shots,
                                   extra_cuts=(teardown or {}).get("scene_cuts"),
                                   analyze_seconds=analysis_limit, log=log)
    broken = [s["id"] for s in rows if s.get("status") != "ok"]
    if broken:
        unchecked.append({"item": "部分镜头三联图",
                          "reason": f"{len(broken)} 镜抽取失败：{'、'.join(broken[:8])}"})

    log("[4/6] 口播转写")
    transcript, asr_error = _transcribe(video, out, enabled=not no_asr, force=force,
                                       model=asr_model, duration=duration, log=log)
    if asr_error:
        unchecked.append({"item": "口播转写", "reason": asr_error})

    log("[5/6] 视觉拆解")
    breakdown, llm_error = _vision(rows, out, enabled=not no_llm, force=force,
                                   model=llm_model, pacing=pacing, transcript=transcript,
                                   source=src, max_shots=max_shots, log=log)
    if llm_error:
        unchecked.append({"item": "镜头语义 / 全片结构", "reason": llm_error})
    for warning in breakdown.get("warnings") or []:
        unchecked.append({"item": "视觉拆解批次", "reason": str(warning)})
    hidden = [rec for rec in (breakdown.get("shots") or {}).values()
              if isinstance(rec, dict) and rec.get("hidden_cut")]
    if hidden:
        unchecked.append({"item": "漏检切点定位",
                          "reason": f"模型认为 {len(hidden)} 镜的三联图不像连续机位；"
                                    "未做逐帧 SSIM 定位，切点时间不保证准确"})
    unchecked.append({"item": "字体与字号",
                      "reason": "字体族、字号、描边宽度无法从像素可靠反推，需人工核对"})
    unchecked.append({"item": "配乐与音效",
                      "reason": "只做了口播转写，没有做音乐/音效识别；不要从节奏反推 BGM"})
    if (teardown or {}).get("caption_band", {}).get("detected"):
        unchecked.append({"item": "字幕 margin_v",
                          "reason": "字幕带 y_bottom 不能直接反推 margin_v；需用字幕墨迹下沿重算"})

    log("[6/6] 汇总")
    generated = _now()
    profile = build_profile(source=src, probe=probe, pacing=pacing, teardown=teardown,
                            rows=rows, segments=segments, contact_sheet=sheet,
                            transcript=transcript, breakdown=breakdown,
                            unchecked=unchecked, generated_at=generated,
                            analysis_duration=analysis_limit)
    if pick_font:
        log("[7/7] 字体选择")
        try:
            from workflow import font_picker
            picked = font_picker.select(project_path, profile, library=font_library,
                                        no_llm=no_llm, force=force, log=log)
            write_json(out / "font-selection.json", picked)
            if project_path:
                font_picker.save_result(project_path, picked)
            profile["font_selection"] = {
                "selected": picked.get("selected"),
                "mode": picked.get("mode"),
                "reason": picked.get("reason"),
                "license": (picked.get("selected") or {}).get("license"),
                "applied": None,
                "file": "font-selection.json",
            }
            for row in picked.get("unchecked") or []:
                unchecked.append({"item": "字体选择：" + str(row.get("item")),
                                  "reason": str(row.get("reason"))})
            log(f"  选中 {((picked.get('selected') or {}).get('name'))}（{picked.get('mode')}）")
        except Exception as exc:  # 字体选择失败不影响参考片档案
            unchecked.append({"item": "字体选择", "reason": str(exc)})
            log(f"  字体选择失败（不影响拆解）：{exc}")
    profile["coverage"]["unchecked_items"] = len(profile["unchecked"])
    write_json(out / PROFILE_NAME, profile)
    (out / REPORT_NAME).write_text(_report(profile, out), encoding="utf-8")
    if project_path:
        project_path.mkdir(parents=True, exist_ok=True)
        write_json(project_path / "work" / "reference-profile.json", profile)
    log("")
    log(f"参考片档案：{out / PROFILE_NAME}")
    log(f"人看的报告：{out / REPORT_NAME}")
    if profile["coverage"]["overview"]:
        log(f"全片结构：{profile['breakdown']['overview'].get('structure')}")
    if unchecked:
        log(f"未检查 {len(unchecked)} 项（见报告末尾）")
    return profile


def main() -> None:
    ap = argparse.ArgumentParser(description="把抖音参考片拆成可复核的数值与结构")
    ap.add_argument("source", help="抖音分享链接 / 分享文案，或本机视频路径")
    ap.add_argument("-o", "--out", help="输出目录（默认 work/reference-intake）")
    ap.add_argument("-p", "--project", help="工程目录；给了就写到 <工程>/work/reference")
    ap.add_argument("--cookie", help="抖音 Cookie：cookies.txt 路径，或 `a=b; c=d` 原文")
    ap.add_argument("--engine", choices=("auto", "share", "yt-dlp"), default="auto",
                    help="下载引擎；auto = 分享页失败后回退 yt-dlp")
    ap.add_argument("--no-asr", action="store_true", help="不转写口播")
    ap.add_argument("--asr-model", default="small", help="faster-whisper 模型（默认 small）")
    ap.add_argument("--no-llm", action="store_true", help="不调用 DeepSeek 视觉拆解")
    ap.add_argument("--llm-model", default="deepseek-flash")
    ap.add_argument("--max-shots", type=int, default=30, help="最多送几镜给视觉模型")
    ap.add_argument("--min-shot", type=float, default=shots_lib.MIN_SHOT)
    ap.add_argument("--max-beat", type=float, default=shots_lib.MAX_BEAT)
    ap.add_argument("--force", action="store_true", help="清掉旧分析并全部重算")
    ap.add_argument("--pick-font", action="store_true",
                    help="拆完后按分析选一款字幕字体（写 font-selection.json，不自动应用）")
    ap.add_argument("--font-library", choices=("auto", "local", "emfont"), default="auto",
                    help="字体库；auto = 本地 + emfont")
    ap.add_argument("--json", action="store_true", help="只打印 profile 路径")
    args = ap.parse_args()

    out = (Path(args.project).resolve() / "work" / "reference"
           if args.project else Path(args.out or "work/reference-intake").resolve())
    log = (lambda *_: None) if args.json else print
    try:
        profile = run(args.source, out, project=args.project, cookie=args.cookie,
                      engine=args.engine, no_asr=args.no_asr, asr_model=args.asr_model,
                      no_llm=args.no_llm, llm_model=args.llm_model,
                      max_shots=max(1, args.max_shots), min_shot=args.min_shot,
                      max_beat=args.max_beat, force=args.force,
                      pick_font=args.pick_font, font_library=args.font_library, log=log)
    except ReferenceSourceError as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(out / PROFILE_NAME)
    else:
        print(f"\n结论：{profile['coverage']}")
        print(f"下一步：koubo auto 某个工程 --video 你的素材 --reference {out}")


if __name__ == "__main__":
    main()
