#!/usr/bin/env python3
"""统一产出审查门：文字 / 声音 / 插画 / 视频四类，汇总 QC 与人工门。

不替代 verify：verify 是逐项机械检查；这里把它们分成四道审查门，明确
哪些是自动查过、哪些必须人看/人听，绝不把 unchecked 写成 pass。
"""
from __future__ import annotations
import argparse, difflib, json, re, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent))
from _common import load_config, project_paths, write_json

TEXT = ["speech-presence", "caption-overlap", "no-punctuation", "caption-slot",
        "caption-role", "grounded-claims", "style-plan-consistent"]
AUDIO = ["audio-stream", "loudness", "true-peak", "long-silence", "bgm-present",
         "bgm-cloud", "speech-presence"]
ILLUSTRATION = ["insert-slot", "insert-grounded", "caption-band-clearance",
                "insert-rendered", "card-rendered"]
VIDEO = ["output-exists", "resolution", "framerate", "duration", "black-frames",
         "no-opening-cover", "no-end-card", "no-sticky-title", "visual-contract",
         "visual-review", "jianying-draft", "jianying-installed", "draft-audit",
         "jianying-fx", "jianying-drift", "measured-constants", "asset-license"]


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _gate(name: str, qc: dict, names: list[str]) -> dict:
    checks = [qc.get(n) for n in names if qc.get(n)]
    statuses = [c.get("status") for c in checks]
    if "fail" in statuses:
        status = "fail"
    elif "unchecked" in statuses or not checks:
        status = "unchecked"
    else:
        status = "pass"
    return {"name": name, "status": status, "checks": checks}


def _caption_asr(project: Path) -> tuple[float | None, str]:
    srt = project_paths(project)["input"] / "captions.srt"
    try:
        raw = srt.read_text(encoding="utf-8")
    except OSError:
        return None, "没有 captions.srt"
    raw = re.sub(r"^\d+\s*$|^\d\d:\d\d:\d\d[,.]\d+ --> .*$", "", raw, flags=re.M)
    cap = re.sub(r"\s+|\[\[|\]\]|\{@[^}]+\}", "", raw)
    try:
        data = json.loads((project / "work" / "transcript.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "没有 work/transcript.json，无法比对字幕与口播"
    transcript = (str(data.get("text") or "")
                  if data.get("text") else
                  "".join(str(w.get("text") or "") for w in data.get("words") or []))
    transcript = re.sub(r"\s+", "", transcript)
    if not cap or not transcript:
        return None, "字幕或转写为空，无法比对"
    ratio = difflib.SequenceMatcher(None, cap, transcript).ratio()
    if ratio < 0.35:
        return False, f"字幕与 ASR 字符相似度 {ratio:.2f}，疑似重写/错位，需人工核对"
    if ratio < 0.60:
        return None, f"字幕与 ASR 字符相似度 {ratio:.2f} 偏低，需人工核对"
    return True, f"字幕与 ASR 字符相似度 {ratio:.2f}"


def _illustration_assets(project: Path, cfg: dict) -> list[dict]:
    p = project_paths(project)
    rows = []
    for item in (cfg.get("inserts") or {}).get("items") or []:
        rel = item.get("illustration")
        if not rel:
            continue
        path = p["assets"] / rel
        row = {"file": rel, "exists": path.is_file(), "tier": "still" if rel.startswith("stills/") else "vector"}
        if path.is_file():
            try:
                with Image.open(path) as im:
                    row["size"] = list(im.size)
                    row["min_side_ok"] = min(im.size) >= 480
            except OSError as exc:
                row["error"] = str(exc)
        rows.append(row)
    return rows


def build(project: Path) -> dict:
    p = project_paths(project)
    cfg = load_config(p["config"])
    qc_rows = _read(p["work"] / "qc-report.json", {}).get("checks") or []
    qc = {c["name"]: c for c in qc_rows}
    gates = [_gate("text", qc, TEXT), _gate("audio", qc, AUDIO),
             _gate("illustration", qc, ILLUSTRATION), _gate("video", qc, VIDEO)]
    asr_ok, asr_detail = _caption_asr(project)
    gates[0]["checks"].append({"name": "caption-asr-coverage",
                               "status": "unchecked" if asr_ok is None else ("pass" if asr_ok else "fail"),
                               "detail": asr_detail})
    if asr_ok is None and gates[0]["status"] == "pass":
        gates[0]["status"] = "unchecked"
    elif asr_ok is False:
        gates[0]["status"] = "fail"

    # 声音：清理记录是证据，不是“已听审”
    clean = _read(p["work"] / "audio-clean.json")
    gates[1]["cleaning"] = clean
    if clean:
        gates[1]["checks"].append({
            "name": "audio-clean", "status": "unchecked",
            "detail": f"已静音 {len(clean.get('muted') or [])} 段非语音；喇叭/噪声是否彻底清除仍需人耳确认",
        })
        gates[1]["status"] = "unchecked"

    # Mixkit 等第三方素材：路径/许可字段可查，授权用途仍需人看
    mixkit = _read(p["work"] / "mixkit.json", {})
    mixkit_items = mixkit.get("items") or []
    if mixkit_items:
        bad_mixkit = [x for x in mixkit_items
                      if not (Path(x.get("local") or "").is_file() and x.get("license"))]
        gates[2]["checks"].append({
            "name": "mixkit-provenance",
            "status": "fail" if bad_mixkit else "unchecked",
            "detail": (f"{len(mixkit_items)} 条 Mixkit 素材；缺文件/许可 {len(bad_mixkit)}"
                       if bad_mixkit else
                       f"{len(mixkit_items)} 条 Mixkit 素材路径/许可已记录；商用范围需人确认"),
        })
        if gates[2]["status"] == "pass":
            gates[2]["status"] = "unchecked"

    # 插画：文件尺寸/来源可自动查，审美与版权仍需人看
    assets = _illustration_assets(project, cfg)
    gates[2]["assets"] = assets
    if assets:
        bad = [a for a in assets if not a.get("exists") or not a.get("min_side_ok", False)]
        gates[2]["checks"].append({
            "name": "illustration-files", "status": "fail" if bad else "pass",
            "detail": f"{len(assets)} 个插图/静帧；缺文件或最小边<480px：{len(bad)}",
        })
        gates[2]["checks"].append({
            "name": "illustration-taste", "status": "unchecked",
            "detail": "素材是否存在/够大已查；构图、清晰度、是否像截图需人眼",
        })
        if gates[2]["status"] == "pass" and "fail" not in [c.get("status") for c in gates[2]["checks"]]:
            gates[2]["status"] = "unchecked"

    # 视频：技术项可自动查；审美/包装仍需人看
    gates[3]["checks"].append({
        "name": "video-taste", "status": "unchecked",
        "detail": "技术规格/黑帧/包装 beat 已查；节奏、构图、审美需人看",
    })
    if gates[3]["status"] == "pass":
        gates[3]["status"] = "unchecked"

    statuses = [g["status"] for g in gates]
    overall = "fail" if "fail" in statuses else ("unchecked" if "unchecked" in statuses else "pass")
    result = {"version": 1, "project": str(project), "overall": overall,
              "gates": gates,
              "note": "unchecked 不等于通过；文字语义、声音噪声、插画审美、视频审美需人工签收"}
    write_json(p["work"] / "review-report.json", result)
    return result


def _md(result: dict) -> str:
    lines = ["# 产出审查", "", f"**总体：{result['overall']}**", "",
             "| 审查门 | 状态 | 自动查过 | 待人工 |", "| --- | --- | --- | --- |"]
    for gate in result["gates"]:
        checks = gate.get("checks") or []
        auto = sum(1 for c in checks if c.get("status") == "pass")
        pending = sum(1 for c in checks if c.get("status") == "unchecked")
        lines.append(f"| {gate['name']} | {gate['status']} | {auto} | {pending} |")
    lines += ["", "> unchecked 不等于通过；四道门都需要人签收。", ""]
    for gate in result["gates"]:
        lines.append(f"## {gate['name']}")
        for c in gate.get("checks") or []:
            lines.append(f"- `{c.get('name')}` {c.get('status')}: {c.get('detail', '')}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="统一产出审查：文字/声音/插画/视频")
    ap.add_argument("project")
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    result = build(Path(a.project).resolve())
    if a.md:
        print(_md(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
