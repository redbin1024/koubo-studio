#!/usr/bin/env python3
"""量旁白语速：把「多少字 = 多少秒」变成可复算的数，而不是凭感觉。

三个口径分开算（混用是这类估算出错的唯一原因，见 references/speech-rate.md）：
  · 净说话语速   = 字数 ÷ 净说话时长        —— 嘴动起来有多快
  · 旁白段挂钟   = 字数 ÷ (末句结束−首句起播) —— 一段连续旁白占多少秒
  · 全片铺开     = 字数 ÷ 片长              —— **写稿前的字数预算**

数据源：工程的 `work/voice-report.json`（`tools/make_voiceover.py` 产的），
没有就退回 `work/voice.wav` + `work/vo-lines.json`。

用法：
    python scripts/speech_rate.py PROJECT_DIR              # 只量
    python scripts/speech_rate.py PROJECT_DIR --archive    # 量完追加进数值正本
    python scripts/speech_rate.py --plan 60                # 反查：60s 片子写多少字
    python scripts/speech_rate.py --plan 60 --coverage 0.5 # 指定旁白占比
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from datetime import date
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ARCHIVE = SKILL_DIR / "references" / "speech-rate.json"
sys.path.insert(0, str(SCRIPT_DIR))
from _common import load_config, project_paths, write_json  # noqa: E402

# 字数口径：Unicode 码点、**去掉空白**、保留标点与英文数字（与 TTS 服务端口径一致）。
# 换口径必须同时改这里和 speech-rate.json 里已归档记录的 char_count_basis。
CHAR_BASIS = "unicode-codepoints, whitespace-stripped, punctuation-kept"


def count_chars(text: str) -> int:
    return len([c for c in text if not c.isspace()])


def measure_voice_wav(wav: Path) -> dict:
    """直接读 wav，用能量门限找说话段 —— 不依赖 ffmpeg silencedetect 的输出格式。"""
    with wave.open(str(wav), "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        raw = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64) / 32768.0
    mono = raw.reshape(-1, ch).mean(axis=1) if ch > 1 else raw
    hop = int(sr * 0.02)
    nf = len(mono) // hop
    if nf == 0:
        return {"speech_sec": 0.0, "span": (0.0, 0.0)}
    e = 20 * np.log10(np.sqrt((mono[: nf * hop].reshape(nf, hop) ** 2).mean(1)) + 1e-9)
    voiced = e > (e.max() - 35.0)
    # 合并小于 min_gap 的空隙
    idx = np.nonzero(voiced)[0]
    if len(idx) == 0:
        return {"speech_sec": 0.0, "span": (0.0, 0.0)}
    gaps = np.nonzero(np.diff(idx) > 1)[0]
    starts = np.r_[idx[0], idx[gaps + 1]]
    ends = np.r_[idx[gaps], idx[-1]]
    keep = [(s, t) for s, t in zip(starts, ends) if (t - s) * 0.02 >= 0.05]
    speech = sum((t - s + 1) * 0.02 for s, t in keep)
    return {"speech_sec": float(speech), "span": (keep[0][0] * 0.02, (keep[-1][1] + 1) * 0.02)}


def read_project(project: Path) -> dict | None:
    p = project_paths(project)
    cfg = load_config(p["config"])
    total = float(cfg.get("duration") or 0.0)

    rep = p["work"] / "voice-report.json"
    lines: list[dict] = []
    voice = "unknown"
    rates: set[int] = set()
    if rep.is_file():
        d = json.loads(rep.read_text(encoding="utf-8"))
        voice = d.get("voice", "unknown")
        total = float(d.get("total") or total)
        for l in d.get("lines", []):
            lines.append({"text": l["text"], "dur": float(l["dur"]),
                          "start": float(l["start"]), "end": float(l["end"])})
            rates.add(int(l.get("rate", 0)))
    else:
        spec = p["work"] / "vo-lines.json"
        if not spec.is_file():
            return None
        d = json.loads(spec.read_text(encoding="utf-8"))
        voice = d.get("voice", "unknown")
        lines = [{"text": l["text"], "dur": 0.0, "start": float(l["t"]), "end": 0.0}
                 for l in d.get("lines", [])]

    if not lines:
        return None
    chars = sum(count_chars(l["text"]) for l in lines)
    return {"project": project.name, "voice": voice, "total": total, "chars": chars,
            "lines": lines, "n": len(lines), "rates": sorted(rates),
            "wav": p["work"] / "voice.wav", "coverage": None,
            "narr_min": min(l["start"] for l in lines),
            "narr_max": max(l["end"] for l in lines)}


def compute(m: dict) -> dict:
    """三个口径一起算。净说话时长优先用 wav 实测（更准），没有就用逐句 dur 求和。"""
    net = 0.0
    span = (m["narr_min"], m["narr_max"])
    if m["wav"].is_file():
        got = measure_voice_wav(m["wav"])
        if got["speech_sec"] > 0:
            net = got["speech_sec"]
            span = got["span"]
    if net <= 0:
        net = sum(l["dur"] for l in m["lines"])
    span_sec = max(span[1] - span[0], 1e-6)
    total = m["total"] or span_sec

    def cpm(sec):
        return m["chars"] / sec * 60 if sec > 0 else 0.0

    return {**m, "speech_sec": net, "span_sec": span_sec,
            "cpm_speech": cpm(net), "cpm_narration": cpm(span_sec), "cpm_film": cpm(total),
            # 两个「占比」不是一回事，别混：
            #   coverage_span   = 首句到末句占片长多少（旁白**铺**了多宽）—— 总是接近 1
            #   coverage_speech = 真正在说话的时间占片长多少（旁白**占**了多少）—— 这才是「留白」
            "coverage_span": span_sec / total if total else 0.0,
            "coverage_speech": net / total if total else 0.0}


def load_archive() -> dict:
    if ARCHIVE.is_file():
        try:
            return json.loads(ARCHIVE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"version": 1, "char_count_basis": CHAR_BASIS, "records": []}


def archive(r: dict) -> None:
    """按五项格式追加一条记录（音色/参数/稿件与字数口径/测量方法/结果+样本+日期）。"""
    d = load_archive()
    d["records"].append({
        "date": date.today().isoformat(),
        "project": r["project"],
        "voice": r["voice"],                                  # ① 音色与引擎
        "synth_params": {"engine": "edge-tts",                # ② 合成参数
                         "rate": (f"+{r['rates'][0]}%" if r["rates"] and r["rates"][0] >= 0
                                  else (f"{r['rates'][0]}%" if r["rates"] else "n/a"))},
        "script": {"lines": r["n"], "chars": r["chars"],      # ③ 稿件与字数口径
                   "char_count_basis": CHAR_BASIS},
        "method": {"speech_sec": round(r["speech_sec"], 2),   # ④ 测量方法
                   "span_sec": round(r["span_sec"], 2),
                   "note": "净说话 = 能量门限 −35dB 相对峰值、去首尾静音；"
                           "跨度 = 首句起播→末句结束"},
        "result": {"cpm_speech": round(r["cpm_speech"], 1),   # ⑤ 结果 + 样本数 + 日期
                   "cpm_narration": round(r["cpm_narration"], 1),
                   "cpm_film": round(r["cpm_film"], 1),
                   "coverage_span": round(r["coverage_span"], 3),
                   "coverage_speech": round(r["coverage_speech"], 3),
                   "samples": r["n"]},
    })
    write_json(ARCHIVE, d)


def plan(seconds: float, coverage: float, cpm: float) -> None:
    chars = cpm * seconds * coverage / 60
    print(f"  按 {cpm:.0f} 字/分钟（净说话）× 旁白占比 {coverage:.0%} × 片长 {seconds:.0f}s")
    print(f"  → 旁白预算约 {chars:.0f} 字")
    print(f"  对照（同一语速）：占比 50% → {cpm * seconds * 0.50 / 60:.0f} 字 / "
          f"75% → {cpm * seconds * 0.75 / 60:.0f} 字 / 95% → {cpm * seconds * 0.95 / 60:.0f} 字")


def main() -> None:
    ap = argparse.ArgumentParser(description="量旁白语速 / 反查字数预算")
    ap.add_argument("project", nargs="?", default=None)
    ap.add_argument("--archive", action="store_true", help="把这次测量追加进数值正本")
    ap.add_argument("--plan", type=float, default=None, metavar="SECONDS",
                    help="不量片子，反查：N 秒的片子写多少字")
    ap.add_argument("--coverage", type=float, default=0.5, help="旁白占片长的比例（配 --plan）")
    a = ap.parse_args()

    if a.plan is not None:
        d = load_archive()
        recs = [r for r in d["records"] if r["result"].get("cpm_speech")]
        cpm = (sum(r["result"]["cpm_speech"] for r in recs) / len(recs)) if recs else 293.0
        src = f"档案里 {len(recs)} 条记录的均值" if recs else "缺省估值（无档案）"
        print(f"  语速来源：{src} = {cpm:.0f} 字/分钟")
        plan(a.plan, a.coverage, cpm)
        return

    if not a.project:
        ap.error("要么给 PROJECT_DIR，要么给 --plan SECONDS")
    project = Path(a.project).resolve()
    m = read_project(project)
    if m is None:
        raise SystemExit(f"{project} 里没有 work/voice-report.json 也没有 work/vo-lines.json，量不了")
    r = compute(m)

    print(f"  {r['project']}  ·  {r['voice']}  ·  {r['n']} 句 / {r['chars']} 字 / 片长 {r['total']:.1f}s")
    if r["rates"] and any(r["rates"]):
        print(f"  ⚠ 有句子用了升速（{r['rates']}），语速会被抬高，归档时记进合成参数")
    print(f"    净说话语速   {r['cpm_speech']:6.0f} 字/分钟   （{r['speech_sec']:.1f}s 净说话）")
    print(f"    旁白段挂钟   {r['cpm_narration']:6.0f} 字/分钟   （跨度 {r['span_sec']:.1f}s）")
    print(f"    全片铺开     {r['cpm_film']:6.0f} 字/分钟   "
          f"（旁白铺了片长的 {r['coverage_span']:.0%}，真正在说话 {r['coverage_speech']:.0%}）")

    d = load_archive()
    est = [x for x in d["records"] if x["voice"] == r["voice"] and x["result"].get("cpm_speech")]
    if est:
        prev = sum(x["result"]["cpm_speech"] for x in est) / len(est)
        dev = (r["cpm_speech"] - prev) / prev * 100
        flag = "  ⚠ 偏差 >15%，值得回头看一眼是不是换了口径" if abs(dev) > 15 else ""
        print(f"    与档案均值（{len(est)} 条 {prev:.0f}）比：{dev:+.1f}%{flag}")

    if a.archive:
        archive(r)
        print(f"    → 已追加进 {ARCHIVE.relative_to(SKILL_DIR)}"
              f"（现有 {len(load_archive()['records'])} 条）")
    else:
        print("    （加 --archive 把这次测量追加进数值正本）")


if __name__ == "__main__":
    main()
