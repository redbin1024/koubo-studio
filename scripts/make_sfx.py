#!/usr/bin/env python3
"""音效轨：全部真实采样（assets/sfx，Pixabay 免署名可商用），按峰值对齐画面点。

三条硬规则：
  1. **按素材自身峰值对齐**。真实采样有 25-420ms 起音，把「素材起点」放在画面点上会晚一截。
  2. **riser 类的长铺垫对齐尾巴**（峰值在结尾），起点 = 落点 − 时长。
  3. **低频撞击做 60Hz 一阶高通**，否则手机小喇叭放不出来，糊成一团。

强调音默认用 impact-bass-2（带预示性 swell，落点更靠前）+ whoosh-cinematic。
不要用 impact-bass-1：那是「干砸」，连用几次整条片子会一直在响，观感很廉价。

用法：python scripts/make_sfx.py PROJECT_DIR
"""
from __future__ import annotations

import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import find_ffmpeg, load_config, project_paths, write_json, resolve_duration  # noqa: E402

SR = 48000
SKILL_ROOT = Path(__file__).resolve().parent.parent
LIB = SKILL_ROOT / "assets/sfx"

# cue → 音效。结构重音统一用 impact-bass-2 + whoosh-cinematic 叠层。
CUES = {
    "hook":   [("impact-bass-2", -14)],
    "cut":    [("impact-bass-2", -15), ("whoosh-cinematic", -17)],
    "return": [("impact-bass-2", -16)],
    "wipe":   [("whoosh-short", -22)],
    "row":    [("pop", -19)],
    "tick":   [("click-soft", -24)],
    "reveal": [("chime", -19)],
    "ping":   [("ping", -21)],
    "shine":  [("sparkle", -20), ("whoosh-cinematic", -18)],
    "end":    [("click-soft", -26)],
}
# 峰值在结尾的长铺垫：起点按「落点 − 时长」对齐
TAIL_ALIGNED = {"riser", "whoosh-cinematic"}
SAMPLE_LIBS = (LIB, Path(__file__).resolve().parent.parent / "assets/sfx")


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        d = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
        return d.reshape(-1, w.getnchannels())


def cache_wav(name: str, cache_dir: Path, project: Path | None = None) -> Path:
    """音效名 → 本地 wav。支持三种引用：

    - `asset:sfx/xxx`：走素材库 ID（推荐，路径可变、ID 不变）；
    - 绝对/工程相对路径：直接把用户自己的音效文件转成 wav；
    - 名字：从随包 `assets/sfx/` 找 `<name>.mp3`。
    """
    text = str(name)
    src: Path | None = None
    key = text
    if text.startswith(("asset:", "library:")):
        try:
            from workflow import asset_library
            got = asset_library.resolve_ref(text, project=project)
            src = Path(got["path"])
            key = "asset-" + got["id"].replace("/", "-")
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"音效 {text} 解析失败：{exc}") from exc
    else:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute() and project is not None:
            candidate = Path(project) / candidate
        if candidate.is_file():
            src = candidate
            key = candidate.stem
        else:
            src = next((lib / f"{text}.mp3" for lib in SAMPLE_LIBS
                        if (lib / f"{text}.mp3").is_file()), None)
    if src is None or not src.is_file():
        raise SystemExit(f"音效库缺少 {name}（找过 {[str(p) for p in SAMPLE_LIBS]}；"
                         "也支持绝对路径与 asset:<id>）")
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", key).strip("-") or "sfx"
    wav = cache_dir / f"{safe}.wav"
    if not wav.exists() or wav.stat().st_mtime < src.stat().st_mtime:
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(src),
                        "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
    return wav


def highpass_60(sig: np.ndarray) -> np.ndarray:
    """60Hz 一阶高通：收掉手机放不出的超低频，保留拳感。"""
    b = (0.9954, -1.9908, 0.9954)
    a = (1.0, -1.9907, 0.9909)
    out = np.empty_like(sig)
    for ch in range(sig.shape[1]):
        x = sig[:, ch]
        y = np.zeros_like(x)
        for i in range(2, len(x)):
            y[i] = (b[0] * x[i] + b[1] * x[i - 1] + b[2] * x[i - 2]
                    - a[1] * y[i - 1] - a[2] * y[i - 2])
        out[:, ch] = y
    return out


def resolve(cfg: dict) -> list[tuple[float, str, float]]:
    """配置 → [(落点秒, 素材名, 峰值 dBFS)]。支持直接写 clip，或写 cue 走预设。"""
    out: list[tuple[float, str, float]] = []
    for ev in cfg["sfx"].get("events", []):
        t = float(ev["t"])
        if ev.get("clip"):
            out.append((t, ev["clip"], float(ev.get("peak_db", -18))))
            continue
        for clip, peak in CUES.get(ev.get("cue", ""), []):
            out.append((t, clip, float(ev.get("peak_db", peak))))
    return sorted(out)


def build(cfg: dict, project: Path, total: float | None = None) -> dict:
    p = project_paths(project)
    events = resolve(cfg)
    if not events:
        print("  sfx.events 为空，跳过音效轨")
        return {"events": 0}
    total = float(total if total is not None else resolve_duration(cfg, project))
    if total <= 0:
        raise SystemExit("需要总时长：在 config.json 里给 duration，或让上游写入 work/duration.txt")

    n = int(total * SR)
    track = np.zeros((n, 2))
    loaded: dict[str, tuple[np.ndarray, float]] = {}
    for t, name, peak_db in events:
        if name not in loaded:
            sig = read_wav(cache_wav(name, p["work"] / "sfx-lib", project))
            loaded[name] = (sig, float(np.argmax(np.abs(sig).max(axis=1))) / SR)
        sig, attack = loaded[name]
        s = sig * (10 ** (peak_db / 20) / (np.max(np.abs(sig)) or 1.0))
        # asset:sfx/riser / 自定义路径也要按「素材本身」判高低通与尾巴对齐，
        # 不能因为前缀是 asset: 就退化成按起音对齐。
        base_name = Path(name).stem if not name.startswith(("asset:", "library:")) \
            else name.split(":", 1)[1].split("/", 1)[-1]
        if base_name.startswith("impact-bass"):
            s = highpass_60(s)
        start = t - len(sig) / SR if base_name in TAIL_ALIGNED else t - attack
        i = max(int(round(start * SR)), 0)
        end = min(n, i + len(s))
        track[i:end] += s[: end - i]
        print(f"  {t:7.2f}s  {name:18s} {peak_db:>4}dBFS  实际起点 {start:7.3f}s")

    peak = float(np.max(np.abs(track)))
    if peak > 0.5:                       # 全轨峰值压在语音之下，别抢人声
        track *= 0.5 / peak
    out = p["work"] / "sfx-track.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype("<i2").tobytes())
    write_json(p["work"] / "sfx-events.json",
               {"total": total, "events": [{"t": t, "clip": c, "peak_db": d} for t, c, d in events]})
    print(f"  work/sfx-track.wav  {total:.3f}s  peak {20 * np.log10(peak):.1f}dB  ({len(events)} 事件)")
    return {"events": len(events)}


def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    total = float(sys.argv[2]) if len(sys.argv) > 2 else None
    build(load_config(project_paths(project)["config"]), project, total)


if __name__ == "__main__":
    main()
