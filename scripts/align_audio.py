#!/usr/bin/env python3
"""外录对轨：测偏移 + 置信度，高置信自动换轨，低置信产对齐草稿交人工。

真实口播几乎都是**双轨收音**：相机内录只是参考声，领夹麦/录音笔的外录才是成片要用的。
粗剪链吃的是视频文件里的音轨 ⇒ **先把外录换进去**，后面转写和成片才都是外录声。

## 为什么不是「假设已对齐」

**测出 0 比假设 0 更稳。** 已对齐的素材跑一遍会测出接近 0 的偏移与高置信；
而万一素材其实没对齐，「假设 0」会**静默错轨** —— 成片人声与口型错位，而且谁也不报错。
所以默认永远先测。

## 怎么测

内录和外录**音色差很远**（近讲 vs 远场、频响完全不同），直接相关原始波形不稳。
所以分两段：

1. **粗测**：把两路都压成 50Hz 的**能量包络**（20ms 一帧）再互相关 —— 包络对音色不敏感，
   对「同时响/同时静」敏感，这正是对轨需要的。分辨率 20ms。
2. **精修**：在粗测峰值附近 ±40ms 内，用原始波形（16kHz）再相关一次，落到 1/16 ms。

置信度取包络互相关的**峰旁比**（峰值 ÷ 旁瓣 RMS）。同源两路实测能到 20 以上，
无关音频在 3~5 徘徊 —— 这个区间足够分开。

## 低置信时怎么办（不猜、不硬上）

置信度不足时**不自动换轨**，改产一份**剪映对齐草稿**（画面一条轨 + 外录一条轨）：
让用户在时间线上拖着对齐 —— 有波形有预览，比任何抽听都直观。保存后：

    python scripts/align_audio.py --resume <那份草稿>

读回人工确认的偏移，完成换轨。

## 三条纪律

- **换轨产物是新文件，且是后续工程的素材** —— 删了工程就素材脱机。原毛片**原地不动**就是保底轨。
- **内录不丢弃**：外录出问题（爆音/断录）随时回退重跑。
- **闭环**：对轨效果（唇音同步）最终以你在剪辑软件里看到的为准，不以本脚本的置信度为准。

用法：
    python scripts/align_audio.py VIDEO AUDIO [--out F] [--json]
    python scripts/align_audio.py --resume <对齐草稿目录>
    python scripts/align_audio.py VIDEO AUDIO --force-offset 1.25    # 确知偏移时跳过检测
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import find_ffmpeg, find_ffprobe, probe_media, write_json  # noqa: E402

SR = 16000          # 精修用的采样率
ENV_HOP = 0.020     # 包络帧长（秒）→ 粗测分辨率 20ms
DEFAULT_THRESHOLD = 0.35


# ---------------------------------------------------------------- 音频读取

def _mono_pcm(path: Path, sr: int = SR) -> np.ndarray:
    """任意音视频 → 单声道 float32（−1..1）。大文件只取前 20 分钟，够测了。"""
    r = subprocess.run([find_ffmpeg(), "-v", "error", "-i", str(path),
                        "-vn", "-t", "1200", "-ac", "1", "-ar", str(sr),
                        "-f", "s16le", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        tail = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
        raise SystemExit(f"读不出 {path.name} 的音轨：\n  " + "\n  ".join(tail))
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768.0


def _envelope(x: np.ndarray, hop: int) -> np.ndarray:
    """能量包络：每 hop 个采样一个数。音频「同时响」这件事对音色不敏感，对包络敏感。"""
    n = len(x) // hop
    if n < 4:
        return np.zeros(0, dtype=np.float32)
    e = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    e = e - e.mean()
    s = e.std()
    return (e / s).astype(np.float32) if s > 1e-9 else np.zeros(n, dtype=np.float32)


# ---------------------------------------------------------------- 互相关

def _xcorr_peak(a: np.ndarray, b: np.ndarray, max_lag: int) -> tuple[int, float, float]:
    """a、b 的互相关峰。返回 (lag, 峰值, 峰旁比)。

    约定：返回的 lag 满足 `a[n] ≈ b[n − lag]`。
    lag > 0 ⇒ b 的内容出现在 a 的**后面**，即 b 的 t=0 落在 a 的 lag 处。

    ⚠️ lag 轴要按循环相关的真实排布取：`irfft(FFT(a)·conj(FFT(b)))[k] = Σ a[n]·b[n−k]`，
    所以 **k = 0..len(b)−1 是正 lag**，而**负 lag 在数组末尾**（`nfft−len(a)+1 .. nfft−1`）。
    曾经在开头取 `c[len(b)−1::-1]` 当负 lag —— 那是正 lag 的倒序，符号会整个反过来
    （实测：真值 −0.400s 被报成 +0.403s，量级对、方向反，而峰旁比也被搅成噪声）。
    """
    na, nb = len(a), len(b)
    nfft = 1 << (na + nb - 2).bit_length()
    c = np.fft.irfft(np.fft.rfft(a, nfft) * np.conj(np.fft.rfft(b, nfft)), nfft)

    neg = c[nfft - (na - 1):] if na > 1 else np.empty(0)   # lag −(na−1) .. −1
    pos = c[:nb]                                           # lag 0 .. nb−1
    cc = np.concatenate([neg, pos])
    zero = len(neg)                                        # lag 0 的下标

    lo, hi = max(0, zero - max_lag), min(len(cc), zero + max_lag + 1)
    win = cc[lo:hi]
    if win.size == 0:
        return 0, 0.0, 0.0
    k = int(np.argmax(np.abs(win)))
    peak = float(win[k])
    # 峰旁比：去掉峰附近 ±3 帧再看旁瓣 RMS —— 同源两路会有一根很尖的峰
    m = np.ones(win.size, dtype=bool)
    m[max(0, k - 3): k + 4] = False
    side = np.abs(win[m])
    # 底噪取旁瓣**中位数**而不是 RMS：旁瓣里也有真相关带来的起伏，RMS 会被它抬起来
    floor = float(np.median(side)) if side.size else 0.0
    psr = abs(peak) / (floor + 1e-12) if floor > 1e-12 else 0.0
    return k + lo - zero, peak, psr


def measure_offset(video: Path, audio: Path, max_shift: float = 60.0) -> dict:
    """测「外录音轨 t=0 对应视频时间轴上的第几秒」。

    offset > 0：外录比视频**晚**开始，换轨时要把它延后
    offset < 0：外录比视频**早**开始，换轨时要把前面裁掉

    约定：记 `_xcorr_peak(a, b)` 返回 lag 使 `a[n] ≈ b[n − lag]`。
    """
    v = _mono_pcm(video)
    a = _mono_pcm(audio)
    if len(v) < SR or len(a) < SR:
        return {"ok": False, "reason": "音轨太短（<1s），测不了", "offset": 0.0, "psr": 0.0}
    hop = int(SR * ENV_HOP)
    ev, ea = _envelope(v, hop), _envelope(a, hop)
    if ev.size < 4 or ea.size < 4:
        return {"ok": False, "reason": "音轨太短，包络不足 4 帧", "offset": 0.0, "psr": 0.0}

    # ---- 粗测（包络，20ms 分辨率）
    # ev[n] ≈ ea[n − lag]  ⇒  视频 n·hop 处 ↔ 外录 (n−lag)·hop 处
    # ⇒ 外录 t=0 落在视频 lag·hop 秒处
    lag, _peak, psr = _xcorr_peak(ev, ea, int(max_shift / ENV_HOP))
    coarse = lag * ENV_HOP

    # ---- 精修：取视频中段 20s 作锚，在粗测附近 ±40ms 用原始波形相关
    # 段内 seg[m] ≈ seg_a[m − lag2]，seg 的采样索引是 v0+m，seg_a 的是 a_start+m
    # ⇒ 外录 t=0 时 m = lag2 − a_start ⇒ 视频秒数 = (v0 + lag2 − a_start) / SR
    fine, fine_ok = coarse, False
    d = 20 * SR
    v0 = int(min(max(len(v) * 0.25, 0), max(0, len(v) - d)))
    a0 = int(round(v0 - coarse * SR))
    a_start = max(0, a0)
    seg = v[v0: v0 + d]
    seg_a = a[a_start: a_start + d]
    if min(len(seg), len(seg_a)) > 3 * SR:          # 至少 3s 重叠才有意义
        lag2, _p2, _psr2 = _xcorr_peak(seg, seg_a, int(0.04 * SR))
        cand = (v0 + lag2 - a_start) / SR
        if abs(cand - coarse) <= 0.05:              # 精修不该跑出粗测太远
            fine, fine_ok = cand, True

    return {"ok": True, "offset": float(fine), "coarse": float(coarse),
            "refined": fine_ok, "psr": float(psr),
            "video_sec": len(v) / SR, "audio_sec": len(a) / SR}


def confidence(m: dict) -> float:
    """把峰旁比折成 0–1 的置信度。同源两路实测 psr 常在 20 以上，无关音频 3~5。"""
    if not m.get("ok"):
        return 0.0
    return float(min(1.0, max(0.0, (m["psr"] - 4.0) / 16.0)))


# ---------------------------------------------------------------- 换轨

def swap(video: Path, audio: Path, offset: float, out: Path) -> Path:
    """把外录按 offset 换进视频。offset>0 延后（补静音），offset<0 前裁。"""
    ff = find_ffmpeg()
    lead = max(0.0, offset)
    trim = max(0.0, -offset)
    ms = int(round(lead * 1000))
    af = (f"atrim=start={trim:.4f},asetpts=PTS-STARTPTS,aresample=48000,"
          f"aformat=channel_layouts=stereo")
    if ms:
        af += f",adelay={ms}|{ms}"
    subprocess.run([ff, "-v", "error", "-y", "-i", str(video), "-i", str(audio),
                    "-map", "0:v", "-map", "1:a", "-af", af,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-movflags", "+faststart", str(out)], check=True)
    return out


def make_align_draft(video: Path, audio: Path, outdir: Path, capcut_bin: str) -> Path | None:
    """低置信时产一份剪映对齐草稿：画面一条轨 + 外录一条轨，用户拖着对齐。"""
    name = f"{video.stem}_对齐"
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / name
    if target.exists():
        import shutil
        shutil.rmtree(target)
    ratio = "9:16" if probe_media(video)["height"] >= probe_media(video)["width"] else "16:9"

    def cap(*args: str) -> dict:
        p = subprocess.run([capcut_bin, *args], capture_output=True, text=True)
        if p.returncode != 0:
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-6:]
            raise SystemExit(f"capcut {' '.join(args)} 失败\n" + "\n".join(tail))
        try:
            return json.loads(p.stdout or "{}")
        except json.JSONDecodeError:
            return {}

    cap("init", name, "--drafts", str(outdir), "--ratio", ratio)
    proj = outdir / name
    vd = probe_media(video)["duration"]
    ad = probe_media(audio)["duration"]
    cap("add-video", str(proj), str(video), "0s", f"{vd:.3f}s", "--track-name", "画面")
    cap("add-audio", str(proj), str(audio), "0s", f"{ad:.3f}s", "--track-name", "外录")
    return proj


def read_draft_offset(draft: Path) -> float:
    """从对齐草稿里读回用户拖好的外录起点。"""
    from make_jianying_draft import Capcut
    cap = Capcut()
    segs = cap.run("segments", str(draft), "--track", "audio")
    rows = segs.get("segments") or segs.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("segments", [])
    if not rows:
        raise SystemExit(f"{draft} 里没找到音频轨 —— 确认草稿里有「外录」那条轨，且已保存")
    starts = sorted(float(s.get("start_us", s.get("start", 0))) for s in rows)
    return starts[0] / 1_000_000.0


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="外录对轨：测偏移、换轨、或产对齐草稿")
    ap.add_argument("video", nargs="?", help="视频（毛片）")
    ap.add_argument("audio", nargs="?", help="外录音频（wav/mp3/m4a/flac）")
    ap.add_argument("--out", default=None, help="换轨产物路径（默认 <视频名>_extaudio.mp4）")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"置信度阈值，低于它不自动换轨（默认 {DEFAULT_THRESHOLD}）")
    ap.add_argument("--force-offset", type=float, default=None,
                    help="确知偏移时跳过检测（秒；正 = 外录晚开始）")
    ap.add_argument("--draft-dir", default=None, help="低置信时把对齐草稿放哪")
    ap.add_argument("--resume", default=None, metavar="DRAFT",
                    help="读回人工在草稿里拖好的偏移，完成换轨")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.resume:
        draft = Path(a.resume).resolve()
        off = read_draft_offset(draft)
        r = {"ok": True, "source": "draft", "draft": str(draft), "offset": off,
             "confidence": 1.0, "note": "偏移来自人工在草稿里拖好的位置"}
        # 草稿目录名的形如 <视频名>_对齐；视频与外录从草稿的 materials 里取
        print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else
              f"  从草稿读回偏移 {off:+.3f}s\n"
              f"  下一步：把这个偏移填进 config 的 input.audio_offset，或重跑对齐换轨")
        return

    if not (a.video and a.audio):
        ap.error("要么给 VIDEO 和 AUDIO，要么给 --resume DRAFT")
    video, audio = Path(a.video).resolve(), Path(a.audio).resolve()
    for f in (video, audio):
        if not f.is_file():
            raise SystemExit(f"找不到 {f}")

    if a.force_offset is None:
        m = measure_offset(video, audio)
        conf = confidence(m)
    else:
        m = {"ok": True, "offset": float(a.force_offset), "coarse": float(a.force_offset),
             "psr": float("nan"), "video_sec": probe_media(video)["duration"],
             "audio_sec": probe_media(audio)["duration"]}
        conf = 1.0
    r = {**m, "video": str(video), "audio": str(audio), "confidence": conf,
         "threshold": a.threshold,
         "verdict": ("强" if conf >= a.threshold else "弱"),
         "forced": a.force_offset is not None}

    if not m.get("ok"):
        r["verdict"] = "测不了"
        emit(r, a.json, video, audio, m, conf, forced=a.force_offset is not None)
        raise SystemExit(1)

    va, aa = m["video_sec"], m["audio_sec"]
    r["warn"] = []
    if abs(m["offset"]) > max(va, aa):
        r["warn"].append("偏移比素材还长，多半是配错了文件")
    if aa < va * 0.5:
        r["warn"].append(f"外录只有 {aa:.1f}s，视频 {va:.1f}s —— 外录可能中途断了")

    # ---- 定动作。**所有分支都在这里定完，最后统一打印一次**（原来各分支各打一次，
    #      低置信时会打两遍 JSON，调用方解析直接炸）。
    if conf < a.threshold:
        # 不猜、不硬上：产对齐草稿让用户在时间线上拖
        from make_jianying_draft import find_capcut
        capcut_bin = find_capcut()
        if not capcut_bin:
            r.update({"action": "manual-required", "verdict": "弱"})
            r["warn"].append("置信度不足且没有 capcut CLI，产不了对齐草稿；"
                             "装：npm install -g capcut-cli")
            emit(r, a.json, video, audio, m, conf, forced=a.force_offset is not None)
            raise SystemExit(2)
        outdir = Path(a.draft_dir).resolve() if a.draft_dir else video.parent / "align-draft"
        proj = make_align_draft(video, audio, outdir, capcut_bin)
        r.update({"action": "produced-align-draft", "draft": str(proj), "verdict": "弱"})
        emit(r, a.json, video, audio, m, conf, forced=a.force_offset is not None)
        return

    out = Path(a.out).resolve() if a.out else video.with_name(f"{video.stem}_extaudio.mp4")
    swap(video, audio, m["offset"], out)
    r.update({"action": "swapped", "output": str(out),
              "note": "换轨产物是后续工程的素材，别删；原毛片原地不动就是内录保底轨"})
    emit(r, a.json, video, audio, m, conf, forced=a.force_offset is not None)


def emit(r: dict, as_json: bool, video: Path, audio: Path, m: dict, conf: float,
         forced: bool = False) -> None:
    """唯一的输出口：`--json` 打一行/一份 JSON，否则打人读的表。"""
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    if r.get("verdict") == "测不了":
        print(f"  ✗ {m.get('reason', '测不了')}")
        return
    print(f"  视频 {video.name}  {m['video_sec']:.2f}s")
    print(f"  外录 {audio.name}  {m['audio_sec']:.2f}s")
    if forced:
        print(f"  偏移 {m['offset']:+.3f}s（--force-offset，未检测）")
    else:
        extra = "（已精修到 1/16ms）" if m.get("refined") else "（只有 20ms 粗测）"
        print(f"  偏移 {m['offset']:+.3f}s{extra}  峰旁比 {m['psr']:.1f}  置信度 {conf:.2f}")
    for w in r.get("warn", []):
        print(f"  ⚠ {w}")

    act = r.get("action")
    if act == "produced-align-draft":
        print(f"\n  置信度 {conf:.2f} < 阈值 {r['threshold']} —— **不自动换轨**")
        print(f"  原因多半是：两路不同源、外录起止对不上、或外录其实是环境声/BGM")
        print(f"\n  → 对齐草稿 {r['draft']}")
        print(f"    打开剪映，把「外录」轨拖到与画面口型对上，保存；然后：")
        print(f"    python scripts/align_audio.py --resume \"{r['draft']}\"")
    elif act == "manual-required":
        print(f"\n  置信度 {conf:.2f} < 阈值 {r['threshold']}，且产不了对齐草稿")
    elif act == "swapped":
        print(f"\n  → 已换轨 {r['output']}")
        print(f"    换轨产物是后续工程的素材，**别删**；原毛片原地不动就是内录保底轨")
        print(f"    对轨效果以你在剪辑软件里看到的为准，不以这个置信度为准")


if __name__ == "__main__":
    main()
