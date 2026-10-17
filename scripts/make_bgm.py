#!/usr/bin/env python3
"""本地合成 BGM 床垫：零外部素材、零版权风险、逐字节可复现。

为什么还要本地合成：剪映的音乐库是云端内容，capcut-cli 没有音乐目录
（`add-audio` 只收本地文件），所以「从剪映资源里选音乐」这条路在命令行走不通。
要换曲子就把选好的音频文件放到 `work/bgm.wav` 的位置，或者直接替换这个文件。

产物 `work/bgm.wav`：48kHz / 16bit / 立体声，长度严格等于当前片长，
弱起弱收、中段最满，便于 `render.py` 的侧链让它给旁白让位。

用法：
    python scripts/make_bgm.py PROJECT [--force]
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import load_config, project_paths  # noqa: E402

FS = 48000

# 每个情绪 = 一组四小节和弦（MIDI）+ 速度 + 拨弦密度
MOODS = {
    "warm": {"chords": [(48, 52, 55, 59), (45, 48, 52, 55),
                        (41, 45, 48, 52), (43, 47, 50, 55)],
             "bpm": 88.0, "pluck": 0.20},
    "calm": {"chords": [(48, 52, 55, 59), (45, 48, 52, 57),
                        (41, 45, 48, 53), (43, 47, 50, 53)],
             "bpm": 72.0, "pluck": 0.13},
    "upbeat": {"chords": [(48, 52, 55, 60), (45, 48, 52, 57),
                          (41, 45, 48, 57), (43, 47, 50, 55)],
               "bpm": 112.0, "pluck": 0.28},
}


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def _envelope(n: int, attack: float, release: float) -> np.ndarray:
    """线性起落包络；两端都不硬切。"""
    env = np.ones(n, dtype=np.float32)
    a, r = max(1, int(attack * FS)), max(1, int(release * FS))
    env[:min(a, n)] = np.linspace(0, 1, min(a, n), dtype=np.float32)
    if r < n:
        env[-r:] *= np.linspace(1, 0, r, dtype=np.float32)
    return env


def _add(buf: np.ndarray, sig: np.ndarray, start: int) -> None:
    end = min(len(buf), start + len(sig))
    if end > start:
        buf[start:end] += sig[:end - start]


def _pad(midi: float, seconds: float, detune: float) -> np.ndarray:
    n = int(seconds * FS)
    t = np.arange(n, dtype=np.float32) / FS
    tone = (np.sin(2 * np.pi * _hz(midi) * (1 + detune) * t)
            + 0.35 * np.sin(2 * np.pi * _hz(midi) * 2 * (1 + detune) * t))
    return (tone * _envelope(n, 0.35, 0.45) * 0.05).astype(np.float32)


def _pluck(midi: float, seconds: float = 1.1) -> np.ndarray:
    n = int(seconds * FS)
    t = np.arange(n, dtype=np.float32) / FS
    tone = np.sin(2 * np.pi * _hz(midi) * t) * np.exp(-4.2 * t)
    return (tone * 0.09).astype(np.float32)


def _bass(midi: float, seconds: float) -> np.ndarray:
    n = int(seconds * FS)
    t = np.arange(n, dtype=np.float32) / FS
    tone = np.sin(2 * np.pi * _hz(midi - 12) * t) * _envelope(n, 0.02, 0.25)
    return (tone * 0.10).astype(np.float32)


def _intensity(total: float) -> np.ndarray:
    """全片强度曲线：弱起 → 中段最满 → 弱收（与收尾淡黑对齐）。"""
    t = np.linspace(0.0, 1.0, int(total * FS), dtype=np.float32)
    rise = np.clip(t / 0.12, 0, 1)
    fall = np.clip((1 - t) / 0.10, 0, 1)
    body = 0.72 + 0.28 * np.sin(np.pi * np.clip((t - 0.12) / 0.76, 0, 1))
    return (np.minimum(rise, fall) * body).astype(np.float32)


def build(cfg: dict, project: Path) -> dict:
    p = project_paths(project)
    total = float(cfg.get("duration") or 0)
    if total <= 0:
        raise SystemExit("config.duration 无效，先确定片长再生成 BGM")
    mood = str((cfg.get("audio", {}).get("bgm") or {}).get("mood", "warm"))
    if mood not in MOODS:
        raise SystemExit(f"未知 BGM 情绪 {mood!r}；可用 {sorted(MOODS)}")
    spec = MOODS[mood]
    bpm = float((cfg.get("audio", {}).get("bgm") or {}).get("bpm") or spec["bpm"])
    beat, bar = 60.0 / bpm, 60.0 / bpm * 4

    n = int(round(total * FS))
    left = np.zeros(n, dtype=np.float32)
    right = np.zeros(n, dtype=np.float32)
    bars = int(np.ceil(total / bar))
    for index in range(bars):
        start = int(round(index * bar * FS))
        chord = spec["chords"][index % len(spec["chords"])]
        for voice, midi in enumerate(chord):
            detune = (-0.0025, 0.0025, -0.0015, 0.0018)[voice % 4]
            _add(left, _pad(midi, bar, detune), start)
            _add(right, _pad(midi, bar, detune + 0.0009), start)
        _add(left, _bass(chord[0], bar * 0.9), start)
        _add(right, _bass(chord[0], bar * 0.9), start)
        if index % 2 == 0:                      # 每两小节一次弱拨弦，避免从头到尾一个质地
            _add(left, _pluck(chord[2], 1.2), start + int(bar * 0.5 * FS))
            _add(right, _pluck(chord[2], 1.2), start + int((bar * 0.5 + 0.007) * FS))

    # 一点点空间感：把信号延迟 70ms 叠回去（等价于一个单抽头梳状），比干声耐听
    delay = int(0.070 * FS)
    for channel in (left, right):
        channel[delay:] += channel[:-delay] * 0.22

    curve = _intensity(total)
    gain = spec["pluck"] / 0.20               # 用拨弦密度当「情绪强度」的代理
    left *= curve * gain
    right *= curve * gain

    peak = float(max(np.abs(left).max(), np.abs(right).max(), 1e-9))
    if peak > 0.9:                            # 只防削波，不做响度归一（响度由 render 统一）
        left *= 0.9 / peak
        right *= 0.9 / peak

    out = p["work"] / "bgm.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    interleaved = np.empty(n * 2, dtype=np.int16)
    interleaved[0::2] = np.clip(left, -1, 1) * 32767
    interleaved[1::2] = np.clip(right, -1, 1) * 32767
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(FS)
        wav.writeframes(interleaved.tobytes())
    print(f"  work/bgm.wav  {total:.2f}s  {mood} / {bpm:.0f}BPM")
    return {"file": str(out), "duration": round(total, 3), "mood": mood, "bpm": bpm}


def main() -> None:
    ap = argparse.ArgumentParser(description="本地合成 BGM 床垫")
    ap.add_argument("project")
    ap.add_argument("--force", action="store_true", help="已有 bgm.wav 也重算")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    p = project_paths(project)
    if (p["work"] / "bgm.wav").is_file() and not a.force:
        print("  work/bgm.wav 已存在；要重算加 --force")
        return
    build(load_config(p["config"]), project)


if __name__ == "__main__":
    main()
