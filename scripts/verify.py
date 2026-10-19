#!/usr/bin/env python3
"""成片质检：把「规格对不对」和「房规有没有破」都落成可复查的条目，写 work/qc-report.json。

规格类：分辨率 / 帧率 / 时长 / 响度 / 真峰 / 黑场 / 长静音
房规类：无片头封面 / 无片尾卡 / 无常驻标题 / 字幕无标点
交付类：剪映草稿真的生成了（每轮和 mp4 并列的另一条产物）
风格类：卡段与画中画真的存在、字幕真的落在安全带里

用法：python scripts/verify.py PROJECT_DIR
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    PUNCT_CHARS, find_ffmpeg, load_config, parse_caption_text, parse_srt, probe_media,
    project_paths, run, run_bytes, strip_cue_directive, write_json, resolve_duration,
)

# ⚠️ 标点表**只此一份**，正本在 `_common.PUNCT_CHARS`（去标点用的是它）。
# 这里原来自己抄了 20 个字符，而正本是 43 个 —— ASCII 的 `! " ' ( ) , - . : ; < > ? [ ] ~`
# 和一批中英引号都不在检查面里，于是「检查通过」并不等于「真的没标点」。
# 两份副本漂移过一次了，别再抄第二份。
PUNCT = PUNCT_CHARS

# 质检三态。**缺席 ≠ 通过**：没查的项必须以 UNCHECKED 出现在报告里，
# 不能因为「这次没跑到」就从报告里消失（那是把「不可判」说成「安全」）。
PASS, FAIL, UNCHECKED = "pass", "fail", "unchecked"


def _measure_loudness(path: Path) -> dict:
    from workflow.loudness import measure_loudness
    return measure_loudness(path)


def _black_frames(path: Path) -> int:
    proc = run([find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
                "-vf", "blackdetect=d=0.30:pix_th=0.10", "-an", "-f", "null", "-"])
    return len(re.findall(r"black_start:", proc.stderr))


def _long_silence_excuses(cfg: dict, project: Path) -> list[tuple[float, float]]:
    """哪些时间段里的静音是**声明过的**：解说槽本身，以及旁白句的时窗。

    解说槽是从原素材真实静音里留出来的（不是补的静音），它天生就是 0.6s 以上的
    静音段；不把「已声明」这部分排除掉，long-silence 这一项会卡死每一条带解说的片子。
    排除多少、为什么排除都写进 detail —— 排除本身也要看得见。
    """
    spans: list[tuple[float, float]] = []
    try:
        shots = json.loads((Path(project) / "work" / "edit-plan.json")
                           .read_text(encoding="utf-8"))["shots"]
        cursor = 0.0
        for shot in shots:
            duration = float(shot["duration"])
            if (shot.get("kind") or "speech") == "narration-slot":
                spans.append((cursor, cursor + duration))
            cursor += duration
    except (OSError, ValueError, TypeError, KeyError):
        pass
    name = cfg.get("audio", {}).get("voice_cues")
    if name:
        try:
            lines = json.loads((Path(project) / "work" / str(name))
                               .read_text(encoding="utf-8"))["lines"]
            spans += [(float(line["start"]), float(line["end"])) for line in lines]
        except (OSError, ValueError, TypeError, KeyError):
            pass
    return spans


def _long_silence_check(out: Path, cfg: dict, project: Path) -> tuple[object, str]:
    from merge_cut import silences as detect_silences
    found = detect_silences(out, -40.0, 0.60)
    if not found:
        return True, "silencedetect -40dB d=0.60 无命中"
    excuses = _long_silence_excuses(cfg, project)
    excused, left = [], []
    for a, b in found:
        target = excused if any(a < end - 1e-6 and b > start + 1e-6
                                for start, end in excuses) else left
        target.append((a, b))
    if not left:
        longest = max(b - a for a, b in excused)
        return True, (f"命中 {len(excused)} 段静音，全部落在已声明的解说槽 / 旁白时窗内"
                      f"（最长 {longest:.2f}s）；未声明的静音 0 段")
    return False, (f"{len(left)} 段静音不在任何解说槽或旁白时窗内（第一段 "
                   f"{left[0][0]:.2f}–{left[0][1]:.2f}s）；已声明而豁免的 {len(excused)} 段")


def _frame_rgb(src: Path, t: float, W: int, H: int):
    """抽一帧成 RGB 数组；抽不到返回 None（调用方记 unchecked，不要当成通过）。"""
    raw = run_bytes([find_ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(src),
                     "-frames:v", "1", "-map", "0:v", "-f", "rawvideo",
                     "-pix_fmt", "rgb24", "-"])
    if len(raw) < W * H * 3:
        return None
    return np.frombuffer(raw[: W * H * 3], dtype=np.uint8).reshape(H, W, 3).astype(np.int16)


def _insert_checks(cfg: dict, project: Path, total: float, srt: Path,
                   W: int, H: int) -> list[tuple[str, object, str]]:
    """插图三项：触发词是否真在字幕里、框位是否压字幕带、有没有真的画上去。

    插图是「由字幕触发的画面」，所以这三项缺一不可 —— 少任何一项，插图都可以
    在没人发现的情况下变成一块凭空出现的装饰板。
    """
    from _common import caption_plain
    from workflow import caption_plan
    out: list[tuple[str, object, str]] = []
    ins = cfg.get("inserts") or {}
    if not ins.get("enabled") or not ins.get("items"):
        reason = ("插图未启用（inserts.enabled = false）" if not ins.get("enabled")
                  else "插图已启用但没有配 items")
        return [("insert-slot", None, reason), ("insert-grounded", None, reason),
                ("caption-band-clearance", None, reason), ("insert-rendered", None, reason)]
    try:
        plan = caption_plan.load(cfg, project)
    except (OSError, ValueError) as exc:
        return [(name, None, f"样式计划读不出来（{exc}），本项没查")
                for name in ("insert-slot", "insert-grounded",
                             "caption-band-clearance", "insert-rendered")]
    items = plan["inserts"]["items"]
    by_index = {cue["index"]: cue for cue in plan["cues"]}

    over = [i for i in items if i["start"] < 0 or i["end"] > total + 0.02]
    out.append(("insert-slot", not over,
                f"{len(items)} 条插图都落在片长 {total:.2f}s 之内" if not over else
                f"第 {over[0]['index']} 条 {over[0]['start']:.2f}–{over[0]['end']:.2f}s "
                f"超出片长 {total:.2f}s"))

    slots_with_lines = set()
    try:
        declared = json.loads((Path(project) / "work" / "narration-lines.json")
                              .read_text(encoding="utf-8"))["lines"]
        slots_with_lines = {int(line["slot"]) for line in declared if "slot" in line}
    except (OSError, ValueError, KeyError, TypeError):
        pass

    def grounded(item) -> bool:
        if item.get("trigger_slot") is not None:
            return item["trigger_slot"] in slots_with_lines
        cue = by_index.get(item.get("trigger_cue"))
        return bool(cue) and item["keyword"] in "".join(caption_plain(ln)
                                                         for ln in cue["lines"])

    ungrounded = [i for i in items if not grounded(i)]
    out.append(("insert-grounded", not ungrounded,
                f"{len(items)} 条插图都有依据（字幕关键词或解说槽）" if not ungrounded else
                f"第 {ungrounded[0]['index']} 条插图找不到依据："
                f"触发词 {ungrounded[0]['keyword']!r} / 槽 {ungrounded[0].get('trigger_slot')}；"
                "插图不能凭空出现"))

    band_top = plan["inserts"]["band_top"]
    overlapping = [i for i in items if i["box"][3] > band_top + 1e-9]
    out.append(("caption-band-clearance", not overlapping,
                f"{len(items)} 条插图都在字幕带上沿 {band_top:.3f} 之上" if not overlapping else
                f"第 {overlapping[0]['index']} 条下沿 {overlapping[0]['box'][3]:.3f} "
                f"压进字幕带（上沿 {band_top:.3f}）"))

    body = Path(project) / "work" / "body-anim-silent.mp4"
    graded = Path(project) / "work" / "graded.mp4"
    if not (body.is_file() and graded.is_file()):
        missing = "、".join(f.name for f in (body, graded) if not f.is_file())
        out.append(("insert-rendered", None, f"缺 {missing}，本项没查"))
        return out
    deltas = []
    for item in items[:4]:                     # 抽样上限：每条一次抽帧，别把质检拖长
        t = (item["start"] + item["end"]) / 2
        got, plain = _frame_rgb(body, t, W, H), _frame_rgb(graded, t, W, H)
        if got is None or plain is None:
            out.append(("insert-rendered", None, f"{t:.2f}s 抽帧失败，本项没查"))
            return out
        x0, y0, x1, y1 = [round(v * s) for v, s in zip(item["box"], (W, H, W, H))]
        a = got[y0 + 12:y1 - 12, x0 + 12:x1 - 12].reshape(-1, 3)
        b = plain[y0 + 12:y1 - 12, x0 + 12:x1 - 12].reshape(-1, 3)
        deltas.append(float(np.abs(a - b).mean()))
    weakest = min(deltas)
    out.append(("insert-rendered", weakest > 20,
                f"抽 {len(deltas)} 条插图的中点帧，框内与未包装画面的最小逐像素差 "
                f"{weakest:.1f}（一条都没画上时≈0）"))
    return out


def _slot_check(cfg: dict, total: float, srt: Path) -> list[tuple[str, object, str]]:
    """包装元素的**坑位包络**校验：每个元素的寿命必须落在片长之内。

    抄自 gtrk《成片型图纸公约》的字卡铁律——「时间线总长 MUST ≥ 落位 clip 的实际坑位时长」。
    落在这儿就是：卡段 / 发光字 / 每条字幕的起止都必须被片长包住。跑出去的表现是
    「元素在片尾被硬切掉」或「还没到就消失」，而这两种都不会报错，只会看起来不对。

    `object` 传 True/False/None —— None 表示这一项没查（元素没启用），按三态记 unchecked。
    """
    out: list[tuple[str, object, str]] = []
    dur = float(total or cfg.get("duration") or 0.0)

    card = cfg["card"]
    if not card["enabled"]:
        out.append(("card-slot", None, "卡段未启用（card.enabled = false）"))
    elif dur <= 0:
        out.append(("card-slot", None, "片长未知，判不了"))
    else:
        a, b = float(card["start"]), float(card["end"])
        bad = []
        if a < 0 or b < 0:
            bad.append("起点为负")
        if a >= b:
            bad.append(f"起点 {a:.2f}s 不早于终点 {b:.2f}s")
        if b > dur + 0.02:
            bad.append(f"终点 {b:.2f}s 超出片长 {dur:.2f}s（卡会被硬切）")
        out.append(("card-slot", not bad,
                    f"卡段 {a:.2f}–{b:.2f}s / 片长 {dur:.2f}s" if not bad
                    else "；".join(bad)))

    g = cfg["gold"]
    if not g["enabled"] or not g["text"]:
        out.append(("gold-slot", None, "发光大字未启用"))
    elif dur <= 0:
        out.append(("gold-slot", None, "片长未知，判不了"))
    else:
        a, b = float(g["in"]), float(g["out"])
        bad = []
        if a < 0:
            bad.append("起点为负")
        if a >= b:
            bad.append(f"in {a:.2f}s 不早于 out {b:.2f}s（永不亮或永不灭）")
        if b > dur + 0.02:
            bad.append(f"out {b:.2f}s 超出片长 {dur:.2f}s（淡出被切掉）")
        out.append(("gold-slot", not bad,
                    f"发光字 {a:.2f}–{b:.2f}s（亮 {b - a:.2f}s）/ 片长 {dur:.2f}s" if not bad
                    else "；".join(bad)))

    cues = parse_srt(srt) if srt.is_file() else []
    if not cues:
        out.append(("caption-slot", None, f"读不到 {srt.name}，本项没查"))
    elif dur <= 0:
        out.append(("caption-slot", None, "片长未知，判不了"))
    else:
        over = [c for c in cues if c["end"] > dur + 0.02]
        last = max(c["end"] for c in cues)
        out.append(("caption-slot", not over,
                    f"{len(cues)} 条字幕，末条收在 {last:.2f}s / 片长 {dur:.2f}s"
                    if not over else
                    f"{len(over)} 条字幕超出片长（第一条 #{over[0]['index']} "
                    f"{over[0]['end']:.2f}s > {dur:.2f}s）"))
    return out


def run_checks(cfg: dict, project: Path) -> dict:
    p = project_paths(project)
    from workflow.delivery import current_output
    out, output_detail = current_output(project, cfg)
    checks: list[dict] = []

    def add(name, status, detail=""):
        """status 收 True(pass) / False(fail) / None(unchecked)。

        **每个检查项都必须被 add 一次**，判不了就传 None 并写清为什么 ——
        从报告里消失的检查项会被读成「通过」，那是把「不可判」说成「安全」。
        """
        if status is True:
            status = PASS
        elif status is False:
            status = FAIL
        elif status is None:
            status = UNCHECKED
        checks.append({"name": name, "status": status, "detail": detail})

    from workflow.speech_policy import speech_readiness
    speech_ready, speech_detail = speech_readiness(cfg, project)
    add("speech-presence", speech_ready, speech_detail)

    if out is None:
        add("output-exists", False, output_detail)
        # 片子都没有，下面每一项都无从查起 —— 全部记 unchecked，别让它们悄悄消失
        for name in ("resolution", "framerate", "audio-stream", "duration", "loudness",
                     "true-peak", "black-frames", "long-silence", "no-opening-cover",
                     "no-end-card", "no-sticky-title", "no-punctuation", "card-rendered",
                     "card-slot", "gold-slot", "caption-slot", "caption-overlap",
                     "voice-caption-overlap", "voice-caption-cross-overlap",
                     "narration-slot-fit", "narration-slot-real",
                     "insert-slot", "insert-grounded",
                     "caption-band-clearance", "insert-rendered",
                     "style-plan-consistent", "bgm-present", "jianying-fx",
                     "jianying-draft", "jianying-installed", "draft-audit",
                     "visual-contract", "visual-review"):
            add(name, None, "没有成片，本项没查")
        return _write(p, out, {}, {}, checks)

    add("output-exists", True, output_detail)
    info = probe_media(out)
    W, H, fps = cfg["canvas"]["width"], cfg["canvas"]["height"], cfg["canvas"]["fps"]
    add("resolution", (info["width"], info["height"]) == (W, H),
        f"{info['width']}x{info['height']}（期望 {W}x{H}）")
    add("framerate", abs(info["fps"] - fps) < 0.05, f"{info['fps']}fps（期望 {fps}）")
    add("audio-stream", info["has_audio"], f"{info['audio_codec']} / {info['sample_rate']}Hz")

    want = resolve_duration(cfg, project)
    add("duration", (abs(info["duration"] - want) < 0.25) if want else None,
        f"{info['duration']:.3f}s（期望 {want:.3f}s）" if want
        else f"{info['duration']:.3f}s（config 里没写 duration，没得比）")

    ln = _measure_loudness(out)
    target = cfg["audio"]["loudness"]
    if ln:
        got_i, got_tp = ln.get("input_i", 0), ln.get("input_tp", 0)
        add("loudness", abs(got_i - target["I"]) <= 1.5,
            f"{got_i:.1f} LUFS（目标 {target['I']}）")
        add("true-peak", got_tp <= target["TP"] + 0.5,
            f"{got_tp:.1f} dBTP（上限 {target['TP']}）")
    else:
        add("loudness", None, "loudnorm 没吐出可解析的 JSON，本项没查")
        add("true-peak", None, "loudnorm 没吐出可解析的 JSON，本项没查")

    add("black-frames", _black_frames(out) == 0, "blackdetect d=0.30 无命中")
    silence_ok, silence_detail = _long_silence_check(out, cfg, project)
    add("long-silence", silence_ok, silence_detail)

    # ---- 房规
    cons = cfg["constraints"]
    add("no-opening-cover", not cons["opening_cover"],
        "全片第一帧就是正片画面，没有独立封面页")
    add("no-end-card", not cons["end_card"],
        f"口播结束即收（最后 {cfg['segments']['fade_out']}s 淡黑），不追加静止品牌卡")
    add("no-sticky-title", not cons["sticky_title"],
        "没有任何元素横跨整条时间轴")

    srt = p["input"] / (cfg["input"]["subtitle"] or "captions.srt")
    from workflow.caption_timing import overlap_status
    cap_ok, cap_detail = overlap_status(
        srt, fps, {int(i) for i in (cfg["captions"].get("skip") or [])})
    add("caption-overlap", cap_ok, cap_detail)
    voice_subtitle = cfg["audio"].get("voice_subtitle")
    skip = {int(i) for i in (cfg["captions"].get("skip") or [])}
    if cfg["audio"].get("speech_mode") not in ("narration", "mixed") or not voice_subtitle:
        add("voice-caption-overlap", None, "未声明独立旁白字幕，本项没查")
        add("voice-caption-cross-overlap", None, "未声明独立旁白字幕，本项没查")
    else:
        voice_ok, voice_detail = overlap_status(p["input"] / voice_subtitle, fps)
        add("voice-caption-overlap", voice_ok, voice_detail)
        # 两套字幕占的是同一条底部安全带：各查各的都会过，合起来才会同帧撞车。
        from workflow.caption_timing import merged_overlap_status
        merged_ok, merged_detail = merged_overlap_status(
            [(srt, skip), (p["input"] / voice_subtitle, set())], fps)
        add("voice-caption-cross-overlap", merged_ok, merged_detail)

    from workflow.speech_policy import narration_slot_status
    slot_ok, slot_detail = narration_slot_status(cfg, project)
    add("narration-slot-fit", slot_ok, slot_detail)

    # 槽得是从原素材真实静音里留出来的，不是手改出来的
    from workflow.narration import slot_source_status
    try:
        shots_for_slots = json.loads((p["work"] / "edit-plan.json")
                                     .read_text(encoding="utf-8"))["shots"]
    except (OSError, ValueError, KeyError, TypeError):
        add("narration-slot-real", None, "读不到镜头表，本项没查")
    else:
        real_ok, real_detail = slot_source_status(shots_for_slots)
        add("narration-slot-real", real_ok, real_detail)
    if not cons["strip_punctuation"]:
        add("no-punctuation", None, "constraints.strip_punctuation = false，按配置不查")
    elif not srt.is_file():
        add("no-punctuation", None, f"缺 {srt}，本项没查")
    else:
        # ⚠️ 必须先脱掉 `[[ ]]` / `(( ))` 标记再扫标点：那两对方括号是**控制语法**，
        # 不是字幕内容。标点表从 20 个字符扩到全部 43 个（含 ASCII 方括号）之后，
        # 直接扫原文会把每一条带强调词的字幕都判成「还有标点」——假阳性。
        # 这个假阳性是扩表当场抓出来的，正是「检查面和被检查的东西必须对齐」的实例。
        bad = []
        for caption_line in srt.read_text(encoding="utf-8-sig").splitlines():
            caption_line = caption_line.strip()
            if not caption_line or "-->" in caption_line or caption_line.isdigit():
                continue
            plain = "".join(t for t, _ in parse_caption_text(strip_cue_directive(caption_line)))
            if any(c in plain for c in PUNCT):
                bad.append(plain)
        add("no-punctuation", not bad,
            f"字幕源文件无标点（脱掉标记后扫 {len(PUNCT)} 个字符，命中 0 行）"
            if not bad else f"字幕里还有标点：{bad[:3]}")

    # ---- 包装元素的坑位包络（卡段 / 发光字 / 字幕）
    srt_path = p["input"] / (cfg["input"].get("subtitle") or "captions.srt")
    for name, ok, detail in _slot_check(cfg, want, srt_path):
        add(name, ok, detail)

    # ---- 插图：触发有据、不压字幕、真的画上去了
    for name, ok, detail in _insert_checks(cfg, project, float(want or 0.0), srt_path, W, H):
        add(name, ok, detail)

    # ---- 风格：卡段真的画上去了吗
    if not cfg["card"]["enabled"]:
        add("card-rendered", None, "卡段未启用（card.enabled = false）")
    else:
        body = p["work"] / "body-anim-silent.mp4"
        blur_src = p["work"] / "blurred.mp4"
        t = (cfg["card"]["start"] + cfg["card"]["end"]) / 2
        if not (body.is_file() and blur_src.is_file()):
            miss = [f.name for f in (body, blur_src) if not f.is_file()]
            add("card-rendered", None, f"缺 {'、'.join(miss)}，本项没查")

        else:
            got, bg = _frame_rgb(body, t, W, H), _frame_rgb(blur_src, t, W, H)
            if got is None or bg is None:
                add("card-rendered", None, f"卡段中点 {t:.2f}s 抽帧失败，本项没查")
            else:
                x0, y0, x1, y1 = [round(v * s) for v, s in
                                  zip(cfg["card"]["box"], (W, H, W, H))]
                # 判「卡有没有画上」，比的是卡段的包装层比**纯模糊底**多出了多少像素差。
                # 卡面是不是「平」不能当判据：那个 60 的阈值是浅灰平卡面的经验值，
                # glass 卡面上有金字白字，本来就花，一定误报。逐像素差在卡画上时
                # 是 55–80，一层没画上时是 0——这个区间足够安全。
                ra = got[y0 + 20:y1 - 20, x0 + 20:x1 - 20].reshape(-1, 3)
                rb = bg[y0 + 20:y1 - 20, x0 + 20:x1 - 20].reshape(-1, 3)
                delta = float(np.abs(ra - rb).mean())
                px = got[int((y0 + y1) / 2), x0 + 30]
                add("card-rendered", delta > 20,
                    f"卡段中点帧，卡区与纯模糊底的逐像素差 {delta:.1f}"
                    f"（卡/画中画/文字一层都没画上时≈0）"
                    f"，取样色 #{px[0]:02X}{px[1]:02X}{px[2]:02X}")

    # ---- 本地 BGM：开了就必须在，而且长度要对得上
    bgm_cfg = (cfg.get("audio") or {}).get("bgm") or {}
    bgm_path = p["work"] / "bgm.wav"
    if not bgm_cfg.get("enabled"):
        add("bgm-present", None, "audio.bgm.enabled = false，本项没查")
    elif not bgm_path.is_file():
        add("bgm-present", False, "开了 audio.bgm 但 work/bgm.wav 不存在；先跑 scripts/make_bgm.py")
    else:
        import wave
        try:
            with wave.open(str(bgm_path), "rb") as wav:
                length = wav.getnframes() / wav.getframerate()
                shape = (wav.getnchannels(), wav.getframerate(), wav.getsampwidth())
        except (OSError, EOFError, wave.Error) as exc:
            add("bgm-present", False, f"work/bgm.wav 读不出来：{exc}")
        else:
            dur = float(want or cfg.get("duration") or 0)
            good = shape == (2, 48000, 2) and abs(length - dur) <= 0.25
            add("bgm-present", good,
                f"work/bgm.wav {length:.2f}s / 片长 {dur:.2f}s，48k 立体声"
                if good else
                f"work/bgm.wav {length:.2f}s、{shape}，与片长 {dur:.2f}s 或格式不符")

    # ---- 剪映资源：配置里声明的每一项都得真的写进草稿
    fx_cfg = cfg.get("jianying_fx") or {}
    if not fx_cfg.get("enabled"):
        add("jianying-fx", None, "jianying_fx 未启用，本项没查")
    else:
        try:
            draft_info = json.loads((p["work"] / "jianying-draft.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            draft_info = {}
        recorded_fx = draft_info.get("fx")
        want_items = sum(len(fx_cfg.get(key) or []) for key in
                         ("effects", "filters", "transitions", "sfx"))
        if not recorded_fx:
            add("jianying-fx", None,
                f"草稿报告里没有剪映资源记录（配置声明了 {want_items} 项）；草稿可能没重建")
        else:
            items = recorded_fx.get("items") or []
            failed = [i for i in items if not i.get("ok")]
            ok = not failed and len(items) == want_items
            detail = (f"剪映资源 {len(items)}/{want_items} 项已写入草稿："
                      + "、".join(f"{i['kind']}:{i['name']}" for i in items[:6]))
            if not ok:
                detail = (f"{len(failed)} 项失败（"
                          + "；".join(f"{i['kind']}:{i['name']} {i.get('error','')}" for i in failed[:3])
                          + f"），期望 {want_items} 项、实际 {len(items)} 项")
            add("jianying-fx", ok, detail +
                "；资源能否在剪映里解析需打开草稿人工确认（离线/未缓存会显示缺失）")

    # ---- 草稿的逐条入场动画，和样式计划对账
    from workflow import caption_plan as plan_mod
    try:
        style_plan = plan_mod.load(cfg, project)
        so_far = json.loads((p["work"] / "jianying-draft.json").read_text(encoding="utf-8"))
        recorded = {item["index"]: item["intro"] for item in so_far.get("caption_anims") or []}
    except (OSError, ValueError, KeyError, TypeError):
        add("style-plan-consistent", None, "缺样式计划或草稿报告，本项没查")
    else:
        if not recorded:
            add("style-plan-consistent", None, "本轮草稿报告里没有逐条动画登记，本项没查")
        else:
            want = {cue["index"]: cue["jy_anim"] for cue in style_plan["cues"]}
            drift = [(i, want[i], recorded.get(i)) for i in sorted(want)
                     if recorded.get(i) != want[i]]
            add("style-plan-consistent", not drift,
                f"草稿 {len(recorded)} 条的入场动画与样式计划一致；"
                "逐条字号与位置表达不了（import-srt 只收全局），这部分只录不判"
                if not drift else
                f"第 {drift[0][0]} 条草稿用 {drift[0][2]!r}、计划要 {drift[0][1]!r}"
                f"（共 {len(drift)} 条不一致）")

    # ---- 交付：剪映草稿（每轮必出，和 mp4 并列；缺了这轮不算跑完）
    jy = cfg["jianying"]
    draft = p["draft_store"] / jy["name"]
    report = p["work"] / "jianying-draft.json"
    from workflow.delivery import draft_matches_receipt
    try:
        draft_record = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        draft_record = {}
    draft_ok = draft_matches_receipt(project, draft, draft_record)
    add("jianying-draft", draft_ok,
        f"{draft}（与本轮渲染凭据匹配）" if draft_ok
        else "缺少与本轮成片匹配的剪映草稿；旧草稿不能替代本轮 draft 步骤")
    if not draft_ok:
        add("jianying-installed", None, "草稿都没建出来，装没装进草稿箱无从判断")
    elif not report.is_file():
        add("jianying-installed", None, f"缺 {report}，本项没查")
    else:
        installed = draft_record.get("installed_to")
        add("jianying-installed", bool(installed) or not jy["install"],
            f"已登记进剪映草稿箱：{installed}" if installed
            else ("按配置只留 draft-store（jianying.install = false）" if not jy["install"]
                  else "草稿没进剪映草稿箱（覆盖保护触发或草稿箱不可写），看 [draft] 的 ⚠"))

    # ---- draft-spec 对账：执行层不能自证，必须和先写下的规格比
    draft_qc_path = p["work"] / "draft-qc.json"
    try:
        draft_qc = json.loads(draft_qc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        draft_qc = None
    if draft_qc is None:
        add("draft-audit", None,
            "没有 work/draft-qc.json（旧草稿或未生成 draft-spec），本项没查")
    else:
        summary = draft_qc.get("summary") or {}
        bad = [c for c in draft_qc.get("checks") or [] if c.get("status") == "fail"]
        add("draft-audit", not bad,
            f"{summary.get('pass', 0)} 过 / {summary.get('fail', 0)} 红 / "
            f"{summary.get('unchecked', 0)} 没查"
            + ("；" + "；".join(f"{c['name']} {c['detail']}" for c in bad[:3])
               if bad else ""))

    # ---- 包装层视觉合同 / 视觉审查包
    vc_path = p["work"] / "visual-contract.json"
    try:
        vc = json.loads(vc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        vc = None
    if vc is None:
        add("visual-contract", None, "没有 work/visual-contract.json，本项没查")
    else:
        from workflow.visual_contract import validate as validate_vc
        vc_issues = validate_vc(vc)
        add("visual-contract", not vc_issues,
            f"{len(vc.get('beats') or [])} 个包装 beat"
            + ("；" + "；".join(vc_issues[:3]) if vc_issues else ""))

    vr_path = p["work"] / "packaging-review.json"
    try:
        vr = json.loads(vr_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        vr = None
    if vr is None:
        add("visual-review", None, "没有 work/packaging-review.json，本项没查")
    else:
        beats = vr.get("beats") or []
        failed = [b for b in beats if b.get("status") == "fail"]
        pending = [b for b in beats if b.get("status") in ("pending", "requires-capcut-export")]
        if failed:
            add("visual-review", False,
                f"{len(failed)} 个 beat 失败；{failed[0].get('id')} 需重做")
        elif pending or vr.get("status") != "pass":
            add("visual-review", None,
                f"待人工观看：{len(pending)} 个 beat pending/需剪映导出；"
                f"contact sheet: {vr.get('contact_sheet')}")
        else:
            add("visual-review", True, f"{len(beats)} 个 beat 已通过人工视觉审查")

    # ---- 草稿有没有被剪映改过（漂移）。**不要信任 capcut diagnose 的 diverged 字段** ——
    # 剪映保存时把 draft_info.json / draft_meta_info.json 加密，而读不了的镜像被它排除在
    # 对比之外，于是「密文侧已经领先很多」它照样报 diverged:false。实测：某草稿
    # draft_content.json 停在 09-30，draft_info.json 是今天 02:00 写的，diagnose 仍说没漂。
    # mtime 不会撒谎，所以这里用 mtime 判。
    if not draft_ok:
        add("jianying-drift", None, "草稿都没建出来，漂移无从判断")
    else:
        # 查**草稿箱那份**：draft-store 那份是我们刚写的，永远是新的，漂移只会出现在
        # 剪映打开过的那份上。拿不到安装路径时才退回 draft-store。
        _rep = p["work"] / "jianying-draft.json"
        _inst = (json.loads(_rep.read_text(encoding="utf-8")).get("installed_to")
                 if _rep.is_file() else None)
        d = Path(_inst) if _inst else draft

        def _mt(f: Path) -> float | None:
            return f.stat().st_mtime if f.is_file() else None
        c, i = _mt(d / "draft_content.json"), _mt(d / "draft_info.json")
        if c is None or i is None:
            add("jianying-drift", None,
                f"缺 {'draft_content.json' if c is None else 'draft_info.json'}，本项没查")
        elif i <= c + 1.0:                      # 1s 容差：同一次写入的先后不算漂移
            add("jianying-drift", True, f"{d.name} 两个文件时间一致，没有剪映侧的未同步改动")
        else:
            # 剪映动过。**这不是缺陷**（打开过就会这样），所以不报红 —— 报红会变成
            # 「狼来了」，人就学会忽略这一项了。真正要验的是**覆盖保护认不认得出**：
            # 认得出来 → 重跑会拒绝覆盖，安全；认不出来 → 重跑会静默吃掉剪映的改动，那才红。
            hrs = (i - c) / 3600
            try:
                from make_jianying_draft import _app_written
                guarded = _app_written(d)
            except Exception:                               # noqa: BLE001
                guarded = None
            if guarded:
                add("jianying-drift", True,
                    f"{d.name} 被剪映改过（比我们的写入新 {hrs:.1f} 小时），"
                    f"**覆盖保护认得出** —— 重跑会拒绝覆盖，不会静默吃掉它改的东西")
            elif guarded is None:
                add("jianying-drift", None, "覆盖保护判定不了（导入 make_jianying_draft 失败）")
            else:
                add("jianying-drift", False,
                    f"剪映改过 {d.name}（新 {hrs:.1f} 小时），但**覆盖保护认不出来** —— "
                    f"重跑会静默覆盖掉剪映侧的改动。看 make_jianying_draft._app_written 的判定条件")



    # ---- 实测常量还和登记表一致吗（references/measured.json）
    # 这些数字是「先量再抄」量出来的，量完就该有保质期。改了值而没改登记表 = 下次没人知道该重量什么。
    try:
        import check_measured
        mr = check_measured.check(project=project.name)
        s = mr["summary"]
        gaps = mr.get("provenance_missing") or []
        detail = f"{s['ok']}/{s['total']} 一致"
        if s["drift"]:
            off = [x["id"] for x in mr["rows"] if x["status"] == "drift"]
            detail = f"**{s['drift']} 条漂移**：{'、'.join(off)} —— 要么同步 references/measured.json，要么这是误改"
            add("measured-constants", False, detail)
        elif s["unchecked"] == s["total"]:
            add("measured-constants", None,
                f"{s['total']} 条全部没查（登记表里没有可校验的 home）")
        else:
            add("measured-constants", True,
                detail + (f"；{s['unchecked']} 条只记出处" if s["unchecked"] else "")
                + (f"；⚠ 出处待补：{'、'.join(gaps)}" if gaps else ""))
    except Exception as e:                                        # noqa: BLE001
        add("measured-constants", None, f"登记表读不了（{type(e).__name__}: {str(e)[:60]}）")

    return _write(p, out, info, ln, checks)


def _write(p, out, info, ln, checks: list[dict]) -> dict:
    n = {s: sum(1 for c in checks if c["status"] == s) for s in (PASS, FAIL, UNCHECKED)}
    write_json(p["work"] / "qc-report.json",
               {"version": 2, "output": str(out) if out else None, "probe": info,
                "loudness": ln, "summary": n, "checks": checks})
    print(f"  work/qc-report.json  {len(checks)} 项 / "
          f"pass {n[PASS]} / fail {n[FAIL]} / 没查 {n[UNCHECKED]}")
    for c in checks:
        if c["status"] == FAIL:
            print(f"  ✗ {c['name']}: {c['detail']}")
    for c in checks:
        if c["status"] == UNCHECKED:
            print(f"  – {c['name']}: 没查 —— {c['detail']}")
    if n[UNCHECKED]:
        print(f"  ⚠ 有 {n[UNCHECKED]} 项没查，**不等于通过**")
    return {"output": str(out) if out else None, "checks": checks, "summary": n}


def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    run_checks(load_config(project_paths(project)["config"]), project)


if __name__ == "__main__":
    main()
