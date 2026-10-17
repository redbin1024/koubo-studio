#!/usr/bin/env python3
"""拿参考片把「实测常量」重量一遍，和登记表比 —— 把「先量再抄」从一次性动作变成可重复命令。

**为什么需要它**：`references/measured.json` 里那些数字是照着某一版参考片量出来的，
量完就冻在那里了。参考片换了、剪映升级了、字体改了，数字会悄悄失效而没人知道。
跑一遍这个，能自动重量的当场对答案，量不了的**明确列出来**（不是假装通过）。

三档结果，和 verify 同一套：

| 档 | 含义 |
|---|---|
| `same` | 重量结果与登记表一致（容差内） |
| `moved` | **变了** —— 要么改登记表，要么改实现 |
| `unmeasurable` | 自动量不了（需人工 / 要量本地产物）—— **不是通过** |

用法：
    python scripts/recalibrate.py ~/Downloads/demo_02.mp4
    python scripts/recalibrate.py REF.mp4 --json
    python scripts/recalibrate.py REF.mp4 --apply      # 把变了的值写回登记表并刷新日期
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "references" / "measured.json"
sys.path.insert(0, str(ROOT / "scripts"))
from _common import find_ffmpeg  # noqa: E402


# ---------------------------------------------------------------- 探针

def probe_caption_ink(ref: Path, *, w: int = 360, h: int = 640, frames_n: int = 60) -> dict:
    """量参考片字幕的**墨迹下沿**（归一化 H）。

    判据是「同一行里同时有很亮的字和很暗的描边」—— 白字黑边是竖屏字幕的通用形态，
    比「亮带检测」稳得多：`analyze_reference.py` 的 `caption_band` 走的是亮带，
    会被画面底部的大片亮区带跑（实测它给 0.9873，而真值 0.71）。**别用那个反推 margin_v。**
    """
    r = subprocess.run([find_ffmpeg(), "-v", "error", "-i", str(ref),
                        "-vf", f"fps=2,scale={w}:{h}", "-frames:v", str(frames_n),
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    buf = np.frombuffer(r.stdout, dtype=np.uint8)
    if buf.size < w * h:
        return {"ok": False, "reason": "抽帧失败"}
    fr = buf[: (buf.size // (w * h)) * (w * h)].reshape(-1, h, w).astype(np.float32)

    bright, dark = fr > 205, fr < 55
    both = (bright & np.roll(dark, 2, axis=1)) | (dark & np.roll(bright, 2, axis=1))
    rows = both.sum(axis=2)
    lo = int(h * 0.55)                      # 字幕只可能在下半部分
    hits = []
    for i in range(len(fr)):
        idx = np.where(rows[i, lo:] > w * 0.02)[0]
        if len(idx) >= 3:                   # 至少 3 行才算是真有一行字幕
            hits.append((lo + idx.max()) / h)
    if not hits:
        return {"ok": False, "reason": "一帧字幕都没检出（参考片没有硬字幕？）"}
    hits = np.array(hits)
    return {"ok": True, "bottom_norm": float(np.median(hits)),
            "p90": float(np.percentile(hits, 90)), "frames": len(hits), "total": len(fr)}


def probe_palette(ref: Path, hue: str) -> dict:
    """从参考片主色里按 hue 挑强调色。"""
    out = ROOT / "work" / "recalibrate-teardown.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze_reference.py"),
                        str(ref), "--out", str(out)], capture_output=True, text=True)
    if not out.is_file():
        return {"ok": False, "reason": f"analyze_reference 没出报告：{r.stderr.strip()[-120:]}"}
    colors = json.loads(out.read_text(encoding="utf-8")).get("accent_colors") or []
    want = {"yellow": ("yellow",), "magenta": ("magenta", "red", "pink")}[hue]
    for c in colors:
        if c.get("hue") in want:
            return {"ok": True, "hex": c["hex"], "hue": c["hue"], "count": c.get("count")}
    return {"ok": False, "reason": f"主色里没有 hue={hue} 的（量到 {len(colors)} 个）"}


def run_probe(spec: str | None, ref: Path) -> dict:
    if not spec:
        return {"ok": False, "reason": "这条没有自动探针（需人工或量本地产物）"}
    if spec.startswith("local:"):
        return {"ok": False, "reason": f"要量本项目自己的产物（{spec.split(':',1)[1]}），不是参考片"}
    if spec == "caption_ink":
        return probe_caption_ink(ref)
    if spec.startswith("palette:"):
        return probe_palette(ref, spec.split(":", 1)[1])
    return {"ok": False, "reason": f"不认识的探针 {spec}"}


# ---------------------------------------------------------------- 比对

def _to_comparable(rec: dict, probe: dict):
    """把探针结果换算成与登记表 `reference_value` 同口径的数。"""
    if rec["id"] == "caption.margin_v":
        return probe["bottom_norm"], 0.71, "H"
    if rec["id"].startswith("caption.palette."):
        return probe["hex"], rec["reference_value"], "hex"
    return None, None, None


def recalibrate(ref: Path, *, tol_scale: float = 1.0) -> dict:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = []
    for r in reg["records"]:
        spec = r.get("recalibrate")
        row = {"id": r["id"], "probe": spec, "recorded": r.get("reference_value"),
               "recorded_unit": r.get("reference_unit")}
        p = run_probe(spec, ref)
        if not p.get("ok"):
            row.update({"status": "unmeasurable", "detail": p["reason"]})
            rows.append(row)
            continue
        got, want, unit = _to_comparable(r, p)
        if got is None:
            row.update({"status": "unmeasurable",
                        "detail": f"探针出了结果但没定义换算口径（{p}）"})
            rows.append(row)
            continue
        row["measured"] = got
        row["unit"] = unit
        if isinstance(got, str):
            same = str(got).lower() == str(want).lower()
        else:
            same = abs(float(got) - float(want)) <= float(r.get("tol") or 0.02) * tol_scale
        row["status"] = "same" if same else "moved"
        row["delta"] = (None if isinstance(got, str) else round(float(got) - float(want), 4))
        rows.append(row)
    n = {s: sum(1 for x in rows if x["status"] == s) for s in ("same", "moved", "unmeasurable")}
    return {"reference": str(ref), "rows": rows, "summary": {**n, "total": len(rows)}}


def apply_moves(res: dict) -> int:
    """把 moved 的值写回登记表，并刷新日期。"""
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    moved = {x["id"]: x for x in res["rows"] if x["status"] == "moved"}
    touched = 0
    for r in reg["records"]:
        m = moved.get(r["id"])
        if not m:
            continue
        # margin_v 存的是「参考片口径」，换算回 H 存；palette 直接存 hex
        r["reference_value"] = m["measured"]
        r["measured_at"] = date.today().isoformat()
        r["measured_on"] = Path(res["reference"]).name
        touched += 1
    if touched:
        REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return touched


def main() -> None:
    ap = argparse.ArgumentParser(description="拿参考片重量实测常量，和登记表比")
    ap.add_argument("reference")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true", help="把变了的值写回登记表并刷新日期")
    ap.add_argument("--tol-scale", type=float, default=1.0, help="容差放大倍数")
    a = ap.parse_args()
    ref = Path(a.reference).expanduser().resolve()
    if not ref.is_file():
        raise SystemExit(f"找不到参考片 {ref}")

    res = recalibrate(ref, tol_scale=a.tol_scale)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print(f"  参考片 {ref.name}")
    mark = {"same": "✓", "moved": "✗", "unmeasurable": "–"}
    w = max(len(x["id"]) for x in res["rows"])
    for x in res["rows"]:
        if x["status"] == "same":
            print(f"    ✓ {x['id']:<{w}}  {x['measured']} 与登记表一致")
        elif x["status"] == "moved":
            print(f"    ✗ {x['id']:<{w}}  登记表 {x['recorded']} → 重量 {x['measured']}"
                  f"（差 {x['delta']:+}）**要决定改哪个**")
        else:
            print(f"    – {x['id']:<{w}}  {x['detail']}")
    s = res["summary"]
    print(f"\n  {s['same']} 一致 / {s['moved']} 变了 / {s['unmeasurable']} 量不了（共 {s['total']} 条）")
    if s["unmeasurable"]:
        print(f"  ⚠ {s['unmeasurable']} 条自动量不了 —— **不等于通过**。")
        print(f"    其中「量不了」分两种：要人工从参考片量的（字号/描边/阴影），")
        print(f"    和要量本项目自己产物的（local:*）。后者改跑对应工程的 verify。")
    if s["moved"] and a.apply:
        n = apply_moves(res)
        print(f"\n  已把 {n} 条写回 {REGISTRY.relative_to(ROOT)}（日期刷成今天）")
    elif s["moved"]:
        print(f"\n  加 --apply 把变了的写回登记表；或先去查是参考片换了还是实现改了。")
    if s["moved"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
