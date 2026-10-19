#!/usr/bin/env python3
"""装配剪映草稿：把成片拆成「可在剪映里继续编辑」的轨道，而不是压平视频。

产物（默认同时装进剪映草稿箱）：

  video  主轨      work/graded.mp4 按粗剪段落切开（in/out 来自 work/rough-cut.json）
  video  包装层    work/body-anim-silent.mp4 只保留包装真正出现的时间窗
                   （卡段 / 结尾发光字 / 收尾淡黑）——这几块是烘进去的，改字要回 config 重出
  audio  人声      input/clean-cut.mp4 的原声（已做过响度归一），音量 1.0
  audio  音效      work/sfx-track.wav，音量取 config 的 audio.sfx_volume
  audio  旁白      work/voice.wav（可选；存在才上轨），音量取 audio.narration_volume
  audio  BGM       work/bgm.wav（可选；存在才上轨），音量取 audio.bgm_volume，带淡入淡出
  text   字幕      input/captions.srt（去掉 [[ ]] / (( )) 标记，| 变真换行）
                   关键词走 text-ranges 上色：[[词]] 强调色、((词)) 反差色

房规：字幕**不加**标点；卡段那几句（config 的 captions.skip）不导入——那一屏的字幕就是卡片本身。

用法：
    python scripts/make_jianying_draft.py PROJECT_DIR [--name 草稿名] [--no-install]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    env_get, find_ffmpeg, load_config, parse_caption_text, parse_srt, probe_media,
    project_paths, repo_root, resolve_video, write_json,
)
from workflow import caption_plan  # noqa: E402

# 剪映字号 15 时一行塞不下太多字：16 是 lint 的上限，实际 9 字以内最稳
JY_MAX_CHARS = 9
JY_FONT_SIZE = 15
JY_TEXT_Y = -0.44            # 字幕垂直位置（-1 顶 / 1 底 之间，和参考成片一致）
JY_STORE_DEFAULT = "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
# 逐条入场动画不再写在这里：它跟着 `work/style-plan.json` 走（正本 workflow/caption_plan.py），
# 否则 mp4 侧和草稿侧各推一份，迟早对不上。

_CAPCUT_CANDIDATES = (
    Path.home() / ".nvm/versions/node",   # 下面再展开版本目录
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def find_capcut() -> str:
    env = env_get("CAPCUT")
    if env and Path(env).is_file():
        return env
    hit = shutil.which("capcut")
    if hit:
        return hit
    # 一键安装器会把 capcut-cli 装进安装目录，避免动全局 npm
    for cand in (repo_root() / "vendor/npm/node_modules/.bin/capcut",
                 repo_root() / "vendor/bin/capcut"):
        if cand.is_file():
            return str(cand)
    nvm = Path.home() / ".nvm/versions/node"
    if nvm.is_dir():
        found = sorted(nvm.glob("*/bin/capcut"))
        if found:
            return str(found[-1])
    for d in (Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        if (d / "capcut").is_file():
            return str(d / "capcut")
    raise SystemExit(
        "找不到 capcut（capcut-cli）。装一个：npm install -g capcut-cli\n"
        "或者重跑一键安装：bash install.sh --full\n"
        "也可以设置 KOUBO_CAPCUT=/path/to/capcut。"
    )


class Capcut:
    def __init__(self) -> None:
        self.bin = find_capcut()

    def run(self, *args: str, check: bool = True) -> dict:
        p = subprocess.run([self.bin, *args], capture_output=True, text=True)
        if check and p.returncode != 0:
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-8:]
            raise SystemExit(f"capcut {' '.join(args)} 失败（exit {p.returncode}）\n" + "\n".join(tail))
        try:
            return json.loads(p.stdout or "{}")
        except json.JSONDecodeError:
            return {"raw": p.stdout.strip()}


def _audio_span(path: Path, total: float) -> float:
    """capcut 会拒绝「请求时长 > 源文件时长」的音频。

    AAC 源抽出来的 WAV 常比视频短 20–40ms（编码器 priming），如果直接拿视频总时长
    去 add-audio，人声轨会静默失败（check=False 时连报错都看不到）。这里按源文件
    实际时长夹一次，宁可在结尾少几十毫秒，也不能整条人声不上轨。
    """
    try:
        duration = float(probe_media(path)["duration"] or 0)
    except (OSError, SystemExit, ValueError):
        duration = float(total)
    return max(0.05, min(float(total), duration))


# ---------------------------------------------------------------- 字幕

def _relayout(raw_lines: list[str], limit: int) -> tuple[str, list[dict]]:
    """把一条带标记的字幕折成剪映能显示的多行，并给出关键词的字符区间。

    折行不是粗暴的「每 9 字一断」：先按 `|` 分段，再在段内做一次小 DP，
    挑「长度最均衡、且不切开带色关键词」的断点。`|` 是作者给的主断点，
    DP 只在段还超长时才介入。区间按 UTF-16 code unit 计（= Python 下标，BMP 一一对应）。
    """
    segs: list[list[tuple[str, str]]] = []
    for line in raw_lines:                      # raw_lines 的每个元素本身就是作者给的换行
        for part in line.split("|"):
            seg: list[tuple[str, str]] = []
            for text, role in parse_caption_text(part):
                seg.extend((ch, role) for ch in text)
            segs.append(seg)
    lines: list[list[tuple[str, str]]] = []
    for seg in (s for s in segs if s):
        lines.extend(_wrap(seg, limit))

    text, ranges, idx = "", [], 0
    for i, ln in enumerate(lines):
        if i:
            text += "\n"
            idx += 1
        start, role = idx, ""
        for ch, r in ln:
            if r != role:
                if role:
                    ranges.append({"start": start, "end": idx, "role": role})
                role, start = r, idx
            text += ch
            idx += 1
        if role:
            ranges.append({"start": start, "end": idx, "role": role})
    return text, ranges


def _wrap(chars: list[tuple[str, str]], limit: int) -> list[list[tuple[str, str]]]:
    """段内折行：行数取最少，断点尽量均衡，且尽量不切开同一个带色词。"""
    n = len(chars)
    if n <= limit:
        return [chars]
    k = -(-n // limit)
    target = n / k

    def cut_penalty(pos: int) -> float:
        a, b = chars[pos - 1][1], chars[pos][1]
        return 200.0 if a and a == b else 0.0

    memo: dict[tuple[int, int], tuple[float, list[int]]] = {}

    def best(i: int, j: int) -> tuple[float, list[int]]:
        """chars[i:] 排 j 行，返回（代价, 断点）。断点不含行尾。"""
        if j == 1:
            return ((n - i - target) ** 2 if n - i <= limit else float("inf"), [])
        if (i, j) in memo:
            return memo[(i, j)]
        out: tuple[float, list[int]] = (float("inf"), [])
        hi = min(n - (j - 1), i + limit)
        for p in range(i + 1, hi + 1):
            rest, cuts = best(p, j - 1)
            if rest == float("inf"):
                continue
            cost = (p - i - target) ** 2 + cut_penalty(p) + rest
            if cost < out[0]:
                out = (cost, [p] + cuts)
        memo[(i, j)] = out
        return out

    _, cuts = best(0, k)
    bounds = [0] + cuts + [n]
    return [chars[bounds[m]:bounds[m + 1]] for m in range(len(bounds) - 1)]


def build_captions(cfg: dict, project: Path, total: float | None = None
                   ) -> tuple[Path, list[dict], list[str]]:
    p = project_paths(project)
    accent = cfg["captions"]["palette"]["accent"]
    contrast = cfg["captions"]["palette"]["contrast"]
    # 逐条样式与动画从样式计划读（正本 workflow/caption_plan.py）——
    # 草稿侧的入场动画过去按序号循环 ANIM_PLAN，和 mp4 侧各推一份，必然漂移。
    plan = caption_plan.load(cfg, project)
    skip = len({int(i) for i in (cfg["captions"].get("skip") or [])})

    out_srt = p["work"] / "jy-stage" / "captions-jy.srt"
    out_srt.parent.mkdir(parents=True, exist_ok=True)
    blocks, meta = [], []
    for cue in plan["cues"]:
        # 计划里的 lines 已经脱掉 `{@...}` 指令，再折行才不会把指令写进草稿。
        text, ranges = _relayout(cue["lines"], JY_MAX_CHARS)
        text = text.strip("\n")
        for r in ranges:
            r["font_color"] = accent if r["role"] == "accent" else contrast
            r.pop("role")
        if not text:
            continue
        end = min(cue["end"], total) if total else cue["end"]   # 字幕不越过成片结尾
        n = len(blocks) + 1
        blocks.append(f"{n}\n{_ts(cue['start'])} --> {_ts(end)}\n{text}\n")
        meta.append({"index": cue["index"], "n": n, "text": text, "ranges": ranges,
                     "start": cue["start"], "end": end, "jy_anim": cue["jy_anim"]})
    out_srt.write_text("\n".join(blocks), encoding="utf-8")
    print(f"  字幕 {len(meta)} 条 → {out_srt.name}"
          f"（跳过卡段 {skip} 条，关键词区间 {sum(len(m['ranges']) for m in meta)} 个）")
    return out_srt, meta, [m["text"].replace("\n", "⏎") for m in meta]


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------- 轨道

def _frame_aligned(durs: list[float], total: float, fps: int) -> list[float]:
    """把镜头时长对齐到帧，并让总和回到成片实际时长。

    粗剪的 concat 会按输出帧率取整，plan 里 42.761s 的 8 段渲出来是 42.900s；
    如果因此退回「整条一个片段」，剪映里就没法逐镜头剪。这里把每段四舍五入到帧，
    把不足的帧补到最后一段，既保住切点，又让主轨总长和成片一致。
    """
    rate = max(int(fps), 1)
    target = max(1, round(float(total) * rate))
    frames = [max(1, round(float(d) * rate)) for d in durs]
    delta = target - sum(frames)
    if abs(delta) > len(frames) + 2:
        raise ValueError("镜头时长与成片总长差距过大，无法安全对齐帧")
    frames[-1] = max(1, frames[-1] + delta)
    out = [round(f / rate, 3) for f in frames]
    # 3 位小数会再丢 1ms；最后一段吃掉这点差，主轨结尾才能和成片严格对齐。
    out[-1] = round(float(total) - sum(out[:-1]), 3)
    return out


def main_video_segments(cfg: dict, project: Path, total: float) -> list[float]:
    """主轨沿粗剪镜头切点分段；没有有效记录时退回整条。"""
    p = project_paths(project)
    fps = int(cfg.get("canvas", {}).get("fps") or 30)
    # auto_edit 的可编辑镜头表没有 rough-cut.json。把压平视频按同一组切点
    # 分段，至少可在剪映里逐镜头调整时长和包装；原素材入点编辑仍属后续能力。
    plan_path = p["work"] / "edit-plan.json"
    if plan_path.is_file() and resolve_video(cfg, project).resolve() == (
            p["input"] / "clean-cut.mp4").resolve():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            durs = [round(float(shot["duration"]), 3) for shot in plan["shots"]]
            if durs and all(d > 0 for d in durs) and abs(sum(durs) - total) < 0.5:
                return _frame_aligned(durs, total, fps)
        except (KeyError, TypeError, ValueError):
            pass
    rough = p["work"] / "rough-cut.json"
    if rough.is_file():
        kept = json.loads(rough.read_text(encoding="utf-8")).get("kept") or []
        durs = [round(k["src_out"] - k["src_in"], 3) for k in kept]
        if durs and abs(sum(durs) - total) < 0.5:
            try:
                return _frame_aligned(durs, total, fps)
            except ValueError:
                pass
    return [round(total, 3)]


def overlay_windows(cfg: dict, total: float) -> list[tuple[str, float, float]]:
    """包装层要保留的时间窗（卡段 / 发光字 / 收尾淡黑）。"""
    wins: list[tuple[str, float, float]] = []
    card = cfg["card"]
    if card["enabled"] and card["end"] - card["start"] > 0.05:
        wins.append(("卡段", float(card["start"]), float(card["end"])))
    gold = cfg["gold"]
    if gold["enabled"] and gold.get("text") and gold["out"] - gold["in"] > 0.05:
        wins.append(("发光字", float(gold["in"]), float(gold["out"])))
    fade = float(cfg["segments"]["fade_out"])
    if fade > 0.05:
        wins.append(("收尾淡黑", round(total - fade, 3), round(total, 3)))
    return wins


def resolve_fx(cfg: dict, main_segments: list[tuple[str, float, float]],
               total: float) -> tuple[list[dict], list[str]]:
    """把 `jianying_fx` 解成「要调哪几条 capcut 命令」，顺便把写错的配置顶回去。

    纯计算、不碰草稿 —— 所以能单测，也能在真正写盘前就把错误报全，
    而不是写了一半才发现某个资源名不存在。
    """
    fx = cfg.get("jianying_fx") or {}
    if not fx.get("enabled"):
        return [], []
    plans, errors = [], []

    def near_cut(at: float):
        # 转场挂在「在切点处结束」的那一段上：剪映里转场是片段尾巴上的属性。
        return next((seg for seg in main_segments
                     if abs(seg[2] - at) <= 0.25), None)

    for i, item in enumerate(fx.get("effects") or [], 1):
        name = str(item.get("name") or "").strip()
        rid = str(item.get("resource_id") or "").strip()
        at, dur = float(item.get("at", 0)), float(item.get("dur", 0))
        if not (name or rid):
            errors.append(f"特效 #{i}：name 与 resource_id 至少要有一个")
        elif dur <= 0 or at < 0 or at + dur > total + 0.02:
            errors.append(f"特效 #{i}（{name or rid}）的 {at:.2f}–{at + dur:.2f}s 超出片长 {total:.2f}s")
        else:
            plans.append({"kind": "effect", "name": name or "resource", "resource_id": rid,
                          "at": at, "dur": dur,
                          "intensity": float(item.get("intensity", 1.0))})

    for i, item in enumerate(fx.get("filters") or [], 1):
        name = str(item.get("name") or "").strip()
        at = float(item.get("at", 0))
        dur = item.get("dur")
        if not name:
            errors.append(f"滤镜 #{i}：缺 name（照抄 `capcut enums --filters --jianying` 里的名字）")
            continue
        if dur is None:
            dur = total - at
        dur = float(dur)
        if dur <= 0 or at < 0 or at + dur > total + 0.02:
            errors.append(f"滤镜 #{i}（{name}）的区间越界")
        else:
            plans.append({"kind": "filter", "name": name, "at": at, "dur": dur,
                          "full": item.get("dur") is None,
                          "intensity": float(item.get("intensity", 1.0))})

    for i, item in enumerate(fx.get("transitions") or [], 1):
        name = str(item.get("name") or "").strip()
        at = float(item.get("at", -1))
        seg = near_cut(at)
        if not name:
            errors.append(f"转场 #{i}：缺 name")
        elif seg is None:
            cuts = "、".join(f"{s[2]:.2f}" for s in main_segments[:6])
            errors.append(f"转场 #{i} 的 at={at:.2f}s 不是主轨切点（现有切点如 {cuts}…）")
        else:
            plans.append({"kind": "transition", "name": name, "at": at,
                          "dur": float(item.get("dur", 0.5)), "segment_id": seg[0]})

    for i, item in enumerate(fx.get("sfx") or [], 1):
        name = str(item.get("name") or "").strip()
        at, dur = float(item.get("at", 0)), float(item.get("dur", 0))
        if not name:
            errors.append(f"音效 #{i}：缺 name（`capcut enums --audio-effects --jianying`）")
        elif dur <= 0 or at < 0 or at + dur > total + 0.02:
            errors.append(f"音效 #{i}（{name}）的 {at:.2f}–{at + dur:.2f}s 超出片长")
        else:
            plans.append({"kind": "sfx", "name": name, "at": at, "dur": dur,
                          "volume": float(item.get("volume", 0.6))})
    return plans, errors


def apply_fx(cap: "Capcut", proj: Path, cfg: dict, plans: list[dict]) -> list[dict]:
    """把解好的计划真正写进草稿；每条的结果都记下来（成功也记，失败也记）。"""
    ns = ["--jianying"] if str((cfg.get("jianying_fx") or {}).get("namespace",
                                                                   "jianying")) == "jianying" else []
    done = []
    for plan in plans:
        entry = {k: plan[k] for k in ("kind", "name", "at", "dur")}
        try:
            if plan["kind"] == "effect":
                extra = ["--resource-id", plan["resource_id"]] if plan.get("resource_id") else []
                out = cap.run("add-effect", str(proj), plan["name"], f"{plan['at']:.3f}s",
                              f"{plan['dur']:.3f}s", *extra,
                              "--intensity", f"{plan.get('intensity', 1.0):.2f}", *ns)
            elif plan["kind"] == "filter":
                # **不要用 --full**：它在实测里按「草稿时长」算，结果写出了 2× 片长的
                # 滤镜段（81.47s / 40.93s），草稿时间轴当场对不上。显式给起止最稳。
                out = cap.run("add-filter", str(proj), plan["name"],
                              f"{plan['at']:.3f}s", f"{plan['dur']:.3f}s",
                              "--intensity", f"{plan.get('intensity', 1.0):.2f}", *ns)
            elif plan["kind"] == "transition":
                out = cap.run("transition", str(proj), plan["segment_id"], plan["name"],
                              "--duration", f"{plan['dur']:.3f}s", *ns)
            else:
                out = cap.run("add-sfx", str(proj), plan["name"], f"{plan['at']:.3f}s",
                              f"{plan['dur']:.3f}s", "--volume", f"{plan['volume']:.2f}",
                              "--track-name", "剪映音效", *ns)
            entry["ok"] = bool(out.get("ok", True))
            entry["segment_id"] = out.get("segmentId") or out.get("segment_id")
        except SystemExit as exc:
            entry["ok"] = False
            entry["error"] = str(exc).strip().splitlines()[-1][:160]
        done.append(entry)
    return done


def build(cfg: dict, project: Path, name: str | None, install: bool,
          store: Path, ratio: str, force: bool, force_install: bool = False) -> dict:
    p = project_paths(project)
    from workflow.delivery import current_output, receipt_digest
    rendered, detail = current_output(project, cfg)
    if rendered is None:
        raise SystemExit(f"草稿不能引用旧成片：{detail}；先运行 render.py")
    render_identity = receipt_digest(project)
    cap = Capcut()
    graded = p["work"] / "graded.mp4"
    overlay = p["work"] / "body-anim-silent.mp4"
    sfx = p["work"] / "sfx-track.wav"
    # 可选干轨，和 render.py 同一套判定：文件在就上轨，不在就跟以前一样
    narration = p["work"] / "voice.wav"
    bgm = p["work"] / "bgm.wav"
    for f in (graded, overlay):
        if not f.is_file():
            raise SystemExit(f"缺 {f}，先跑 run_all.py（frames/render）")

    stage = p["work"] / "jy-stage"
    stage.mkdir(parents=True, exist_ok=True)
    src = resolve_video(cfg, project)
    total = float(probe_media(src)["duration"])

    # 1. 人声（成片用的那条，已经是归一过的电平）
    voice = stage / "voice.wav"
    print(f"  人声 ← {src.name}")
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-vn",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(voice)], check=True)

    # 2. 字幕
    srt_jy, cap_meta, _ = build_captions(cfg, project, total)

    # 3. 建稿
    draft_store = store
    draft_store.mkdir(parents=True, exist_ok=True)
    target = draft_store / name
    if target.exists():
        if not force:
            raise SystemExit(f"{target} 已存在。改名（--name）或加 --force 先删掉再建。")
        shutil.rmtree(target)
    info = cap.run("init", name, "--ratio", ratio, "--drafts", str(draft_store))
    proj = Path(info.get("draft_path") or target)
    print(f"  草稿 {proj}")

    # 4. 主轨
    pos = 0.0
    main_segments: list[tuple[str, float, float]] = []
    for i, dur in enumerate(main_video_segments(cfg, project, total), 1):
        # 不加 duration：让 capcut 用 ffprobe 拿真实时长与分辨率写素材，
        # 否则素材会被写成「这一段的时长」，trim 出来的 in-point 越界，剪映会把入点夹回 0。
        sid = cap.run("add-video", str(proj), str(graded), f"{pos:.3f}s")["segment_id"]
        cap.run("trim", str(proj), sid, f"{pos:.3f}s", f"{dur:.3f}s", check=False)
        main_segments.append((sid, pos, pos + dur))
        pos += dur
    print(f"  主轨 {i} 段 / {pos:.3f}s")

    # 剪映资源先解一遍：配置写错的话在写草稿之前就报全，不留半成品
    fx_plans, fx_errors = resolve_fx(cfg, main_segments, total)
    if fx_errors:
        raise SystemExit("剪映资源配置有误：\n  " + "\n  ".join(fx_errors))

    # 5. 包装层
    wins = overlay_windows(cfg, total)
    for label, a, b in wins:
        sid = cap.run("add-video", str(proj), str(overlay), f"{a:.3f}s",
                      "--track-name", "包装层")["segment_id"]
        cap.run("trim", str(proj), sid, f"{a:.3f}s", f"{b - a:.3f}s", check=False)
    print("  包装层 " + " / ".join(f"{w[0]} {w[1]:.2f}-{w[2]:.2f}s" for w in wins))

    # 6. 音频
    voice_span = _audio_span(voice, total)
    cap.run("add-audio", str(proj), str(voice), "0s", f"{voice_span:.3f}s",
            "--volume", "1.00", "--track-name", "人声", "-q")
    tracks = ["人声"]
    if sfx.is_file():
        sfx_span = _audio_span(sfx, total)
        cap.run("add-audio", str(proj), str(sfx), "0s", f"{sfx_span:.3f}s",
                "--volume", f"{cfg['audio']['sfx_volume']:.2f}",
                "--track-name", "音效", "-q")
        tracks.append("音效")
    if narration.is_file():
        narr_span = _audio_span(narration, total)
        cap.run("add-audio", str(proj), str(narration), "0s", f"{narr_span:.3f}s",
                "--volume", f"{cfg['audio']['narration_volume']:.2f}",
                "--track-name", "旁白", "-q")
        tracks.append("旁白")
    if bgm.is_file():
        # 这次不能带 -q：要拿 segment_id 给 audio-fade 用
        bgm_span = _audio_span(bgm, total)
        sid = cap.run("add-audio", str(proj), str(bgm), "0s", f"{bgm_span:.3f}s",
                      "--volume", f"{cfg['audio']['bgm_volume']:.2f}",
                      "--track-name", "BGM")["segment_id"]
        # 淡入 1.6s / 收尾 2.4s 淡出，和 tools/make_bgm.py 里的包络对齐
        cap.run("audio-fade", str(proj), sid, "--in", "1.6", "--fade-out", "2.4",
                check=False)
        tracks.append("BGM")
    print("  音频 " + " + ".join(tracks))

    # 7. 字幕 + 关键词上色 + 出入场动画
    # 全自动 Vlog 可能只有旁白、没有画面字幕：不建空字幕轨，草稿里只留旁白音频。
    if cap_meta:
        cap.run("import-srt", str(proj), str(srt_jy), "--track-name", "字幕",
                "--font-size", str(JY_FONT_SIZE), "--color", "#FFFFFF",
                "--border-width", "0.08", "--border-color", "#000000",
                "--shadow", "true", "--y", str(JY_TEXT_Y), "-q", check=False)
        segs = sorted(_as_list(cap.run("segments", str(proj), "--track", "text")),
                      key=lambda s: s.get("start_us", 0))
        if len(segs) != len(cap_meta):
            raise SystemExit(f"字幕段数对不上：草稿 {len(segs)} / SRT {len(cap_meta)}")
        for seg, meta in zip(segs, cap_meta):
            if meta["ranges"]:
                cap.run("text-ranges", str(proj), seg["id"],
                        "--styles", json.dumps(meta["ranges"]), check=False)
        for seg, meta in zip(segs, cap_meta):
            cap.run("text-anim", str(proj), seg["id"],
                    "--intro", meta["jy_anim"], "--intro-duration", "0.30s",
                    "--outro", "渐隐", "--outro-duration", "0.20s", "--jianying", "-q", check=False)
        print(f"  字幕 {len(segs)} 条（关键词上色 + 出入场动画）")
    else:
        print("  没有画面字幕，跳过草稿字幕轨（旁白字幕另存在 input/voice-captions.srt）")

    # 7.5 剪映资源库的特效 / 滤镜 / 转场 / 音效（**只进草稿**：mp4 是 ffmpeg 渲的）
    fx_done = apply_fx(cap, proj, cfg, fx_plans)
    if fx_done:
        failed = [x for x in fx_done if not x.get("ok")]
        names = "、".join(f"{x['kind']}:{x['name']}" for x in fx_done[:6])
        print(f"  剪映资源 {len(fx_done)} 项（{names}）"
              + (f"；⚠ {len(failed)} 项失败" if failed else ""))
    else:
        print("  jianying_fx 未启用，跳过剪映原生特效")

    # 7.6 贴纸层（草稿专属；全画布透明 PNG，进剪映是独立图片轨）
    sticker_count = 0
    sticker_cfg = cfg.get("stickers") or {}
    if sticker_cfg.get("enabled"):
        for i, item in enumerate(sticker_cfg.get("items") or [], 1):
            asset = p["assets"] / f"sticker-{i}.png"
            if not asset.is_file():
                continue
            at, dur = float(item.get("at", 0) or 0), float(item.get("dur", 0) or 0)
            if at < 0 or dur <= 0 or at + dur > total + 0.05:
                continue
            cap.run("add-video", str(proj), str(asset), f"{at:.3f}s",
                    f"{dur:.3f}s", "--track-name", "贴纸", "-q")
            sticker_count += 1
    if sticker_count:
        print(f"  贴纸 {sticker_count} 条（草稿专属，独立贴纸轨）")

    # 8. duration 回正 + 校验
    fix_duration(proj)
    stamp_jianying_platform(proj)
    cap.run("lint", str(proj), "--fix", check=False)
    lint = cap.run("lint", str(proj), check=False)
    check = verify_timeline(cap, proj, total, len(cap_meta))
    print(f"  lint {'干净' if lint.get('ok', True) else '有问题'}；"
          f"时间轴 {check['end']:.3f}s / 字幕 {check['texts']} 条")

    report = {"draft": str(proj), "name": name, "duration": total,
              "render_receipt_sha256": render_identity,
              "tracks": {"main_segments": len(main_video_segments(cfg, project, total)),
                         "overlay": [{"label": w[0], "start": w[1], "end": w[2]} for w in wins],
                         "captions": len(cap_meta)},
              # 逐条入场动画登记在报告里，好让 verify 拿它和样式计划对账 ——
              # 「草稿说它按计划做了」这件事必须能被复查，不能靠脚本自己声称。
              "caption_anims": [{"index": m["index"], "intro": m["jy_anim"]}
                                for m in cap_meta],
              # 剪映原生资源只在这份草稿里生效；verify 拿它对账，报告里也写得明明白白
              "fx": {"namespace": (cfg.get("jianying_fx") or {}).get("namespace", "jianying"),
                     "items": fx_done},
              "installed_to": None}
    if install:
        report["installed_to"] = install_draft(cap, proj, name, store, force_install)
    # import-srt 默认行距 0.02，双行字幕会叠在一起；在最后一步直接修草稿 JSON，
    # 不再触发 capcut 的 changed-on-disk 检查。项目内和草稿箱那份都要修。
    spacing = float((cfg.get("jianying") or {}).get("line_spacing", 0.22))
    set_text_line_spacing(proj, spacing)
    if report.get("installed_to"):
        set_text_line_spacing(Path(report["installed_to"]), spacing)
    report["text_line_spacing"] = spacing
    report["tracks"]["stickers"] = sticker_count
    write_json(p["work"] / "jianying-draft.json", report)
    return report


def _as_list(payload) -> list[dict]:
    """capcut 有的命令回数组、有的回 {"segments": [...]}，统一一下。"""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("segments", "items", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def verify_timeline(cap: Capcut, proj: Path, total: float, want_texts: int) -> dict:
    """复核：时间轴结尾对得上总时长、字幕条数对得上，否则草稿打开就是残的。"""
    segs = [s for s in _as_list(cap.run("segments", str(proj))) if s.get("type") != "text"]
    end = max((s.get("start_us", 0) + s.get("duration_us", 0)) for s in segs) / 1e6 if segs else 0.0
    # 没有画面字幕时 capcut 会直接报 "No tracks of type text"，不能把它当失败。
    texts = (len(_as_list(cap.run("segments", str(proj), "--track", "text")))
             if want_texts else 0)
    if abs(end - total) > 0.05:
        raise SystemExit(f"时间轴对不上：草稿 {end:.3f}s / 预期 {total:.3f}s")
    if texts != want_texts:
        raise SystemExit(f"字幕条数对不上：草稿 {texts} / SRT {want_texts}")
    return {"end": end, "texts": texts}


def set_text_line_spacing(proj: Path, spacing: float) -> None:
    """给草稿里的每条字幕写行距。

    capcut import-srt 默认 line_spacing=0.02，双行字幕在剪映里两行几乎贴在一起；
    0.22 是 22% 字高的安全行距。改的是草稿 JSON 的 text material，不影响 SRT。
    """
    path = Path(proj) / "draft_content.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    texts = (data.get("materials") or {}).get("texts") or []
    changed = False
    for material in texts:
        if "line_spacing" in material:
            material["line_spacing"] = round(float(spacing), 3)
            changed = True
    if changed:
        write_json(path, data)


def fix_duration(proj: Path) -> None:
    """add-video 会把顶层 duration 写成整段素材长度，按段落实际结束时间回正。"""
    for fname in ("draft_info.json", "draft_content.json"):
        f = proj / fname
        if not f.is_file():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        end = 0
        for track in data.get("tracks", []):
            for seg in track.get("segments", []):
                tr = seg.get("target_timerange") or {}
                end = max(end, int(tr.get("start", 0)) + int(tr.get("duration", 0)))
        data["duration"] = end
        f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def stamp_jianying_platform(proj: Path) -> None:
    """把草稿的来源标记改回剪映：`app_source` 必须是 "lv"，不能是 "cc"。

    种子模板是 CapCut 国际版 6.5.0 的，`capcut init` 出来的草稿带着
    `{"app_source": "cc", "app_version": "6.5.0"}` —— 等于告诉剪映「这是 CapCut 的工程」。
    `app_source` 是**真实语义分支**（capcut-cli 自己就拿它区分遮罩字段名、取值范围），
    剪映据此走 CapCut 的特效/动画命名空间，而草稿里的动画 id 是剪映命名空间的，
    对不上就是**字幕动画全部「加载失败」**。改成 "lv" 才认得出来。

    这里**故意不写 `app_version`**：capcut-cli 的写入护栏只要看到剪映 >= 6.0 的版本号
    就会拒绝写入（`version.js` 的 known-broken 区间），而那个护栏同时也是「剪映正开着
    这份草稿就别写」的保护，比版本号本身更有用，不能为了写进版本号把它一起关掉。
    标记本来就是可选的（`capcut create` 产出的草稿不带任何标记）。
    """
    platform = {"app_source": "lv", "os": "mac"}
    for fname in ("draft_info.json", "draft_content.json"):
        f = proj / fname
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue          # 已经被剪映加密的那份不碰
        if data.get("platform") == platform:
            continue
        data["platform"] = platform
        f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _app_written(draft: Path) -> bool:
    """剪映自己写过的草稿：draft_meta_info.json 被加密（6.0+）或出现 Timelines/。
    这类草稿不能盲覆盖 —— 里面可能是用户在剪映里改过的版本。"""
    if (draft / "Timelines").is_dir() or (draft / "Resources").is_dir():
        return True
    meta = draft / "draft_meta_info.json"
    if meta.is_file():
        try:
            json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return True
    return False


def install_draft(cap: Capcut, src: Path, name: str, store: Path,
                  force: bool = False) -> str:
    """装进剪映草稿箱：复制 → relink → register → lint --fix。"""
    dest_root = Path(env_get("JY_STORE",
                             os.environ.get("JY_STORE", JY_STORE_DEFAULT))).expanduser()
    dest = dest_root / name
    if not dest_root.is_dir():
        print(f"  ⚠ 剪映草稿箱不存在（{dest_root}），草稿只留在 {src}")
        return ""
    if not os.access(dest_root, os.W_OK):
        print(f"  ⚠ 剪映草稿箱不可写（{dest_root}），草稿只留在 {src}")
        return ""
    try:
        if dest.exists():
            if _app_written(dest) and not force:
                print(f"  ⚠ {dest} 已经被剪映改过（加密 / 带 Timelines），不覆盖。"
                      f"换一个 --name，或确认要丢弃手改再加 --force")
                return ""
            shutil.rmtree(dest)
            print(f"  → 覆盖同名草稿 {dest}")
        shutil.copytree(src, dest)
        print(f"  → 复制到 {dest}")
        cap.run("relink", str(dest), "--from", str(src), "--to", str(dest), "-q", check=False)
        cap.run("register", str(dest), "--apply", "--materials",
                "--drafts", str(dest_root), "-q", check=False)
        cap.run("lint", str(dest), "--fix", "-q", check=False)
        cap.run("lint", str(dest), check=False)
        print(f"  → 已登记进剪映草稿箱：{name}")
        return str(dest)
    except OSError as e:
        print(f"  ⚠ 写入剪映草稿箱失败（{e}），草稿仍在 {src}")
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="把成片装配成可继续编辑的剪映草稿")
    ap.add_argument("project")
    ap.add_argument("--name", default=None, help="草稿名（默认用 config.name）")
    ap.add_argument("--ratio", default=None, help="画布比例（默认读 config 的 jianying.ratio）")
    ap.add_argument("--store", default=None, help="草稿库（默认工程内 draft-store/）")
    ap.add_argument("--no-install", action="store_true", help="只建在工程里，不装进剪映草稿箱")
    ap.add_argument("--force", action="store_true",
                    help="工程内 draft-store 的同名草稿先删掉重建")
    ap.add_argument("--force-install", action="store_true",
                    help="连剪映里改过的那份同名草稿也覆盖（默认只提示，不动它）")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    p = project_paths(project)
    cfg = load_config(p["config"])
    jy = cfg["jianying"]
    name = a.name or jy["name"]
    store = Path(a.store).resolve() if a.store else p["draft_store"]
    build(cfg, project, name, not a.no_install, store,
          a.ratio or jy["ratio"], a.force, a.force_install)


if __name__ == "__main__":
    main()
