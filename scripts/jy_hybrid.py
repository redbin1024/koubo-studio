#!/usr/bin/env python3
"""混合后端：**jy1 写内容 + 本项目补样式 + capcut-cli 补交付层**。

为什么是三家分工（每一步都在剪映 11.5 上实测过）：

| 谁 | 负责 | 证据 |
|---|---|---|
| **pyJianYingDraft (jy1)** | 草稿内容：轨道/片段/文字/转场/动画 | 剪映打开保存后**顶层键 28→28，一个都没加** —— schema 原生完整 |
| **本模块** | jy1 不做的那两件：**关键词变色**（styles 拆 range）、**交付层**（draft_info.json / platform 印记 / meta 四个键） | capcut-cli 那条素材的 styles 字段名与本模块产出的**完全一致** |
| **capcut-cli** | 装机：`register --materials --apply`（staging + local_material_id）、`lint --fix`（补引用） | 补完 `capcut lint` 从 4 warning 6 info 变成 **OK 零问题** |

**为什么不直接用 capcut-cli 一家**：jy1 的资源目录是 4548 条**带 resource_id/effect_id/md5** 的枚举，
其中转场 453 条、滤镜 1052 条、字体 798 条 —— 而 capcut-cli 的剪映命名空间转场**一条都用不了**
（`transition` 只收 slug，362 条全没 slug），滤镜只有 468、字体只有 335。

**为什么不直接用 jy1 一家**：它不注册草稿箱（全库零引用 `root_meta_info.json`）、不 staging 素材
（绝对路径 → 剪映可能报「无访问权限」，见它自己的 issue #198）、没有 lint。

依赖：`pip install pymediainfo`（+ 系统 `brew install mediainfo`）。
库位置用环境变量 `KOUBO_JY1` 指定（旧名 `THSP_JY1` 仍可用），默认找 `/tmp/jy1`。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import env_get, find_ffmpeg, find_ffprobe, probe_media, write_json  # noqa: E402

# 与 make_jianying_draft.py 保持同一套视觉常量 —— 两条后端出来的片子要长得一样。
# **引用不复制**：这里曾经把四个常量抄了一份，注释写着「要保持一致」；
# 注释不是机制，所以改成直接 import（registry.md 的正本规则）。
from make_jianying_draft import JY_FONT_SIZE, JY_MAX_CHARS, JY_TEXT_Y  # noqa: E402
from workflow.caption_plan import ANIM_PLAN  # noqa: E402

# 参考稿里一条字幕的材质级样式（剪映接受过的形状），本模块照抄
REF_MATERIAL_STYLE = {
    "alignment": 1, "typesetting": 0, "letter_spacing": 0, "line_spacing": 0.02,
    "line_feed": 1, "line_max_width": 0.82, "force_apply_line_max_width": False,
    "check_flag": 7, "fixed_width": -1, "fixed_height": -1,
    "has_shadow": True, "border_width": 0.08, "border_color": "#000000", "border_alpha": 1.0,
}


# ---------------------------------------------------------------- 库定位

def locate_lib() -> Path | None:
    """找 pyJianYingDraft。KOUBO_JY1（旧 THSP_JY1）优先，其次常见位置。"""
    for c in (env_get("JY1"), "/tmp/jy1",
              str(Path.home() / "Documents/trae_projects/film_editing/pyJianYingDraft")):
        if c and (Path(c) / "pyJianYingDraft/__init__.py").is_file():
            return Path(c)
    return None


def load_lib():
    lib = locate_lib()
    if not lib:
        raise SystemExit(
            "找不到 pyJianYingDraft。\n"
            "  git clone https://github.com/GuanYixuan/pyJianYingDraft\n"
            "  pip install pymediainfo && brew install mediainfo\n"
            "  然后 export KOUBO_JY1=<克隆目录>")
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    try:
        import pyJianYingDraft as jy
    except ModuleNotFoundError as e:
        raise SystemExit(f"pyJianYingDraft 导入失败：{e}\n  pip install pymediainfo（还需要系统 mediainfo）")
    return jy


# ---------------------------------------------------------------- ★ 关键词变色

def hex_to_rgb(h: str) -> list[float]:
    h = h.lstrip("#")
    return [round(int(h[i:i + 2], 16) / 255, 6) for i in (0, 2, 4)]


def split_keyword_ranges(text: str, ranges: list[dict], base: str) -> list[tuple[int, int, str]]:
    """把整段文字切成「同色的连续区间」。

    jy1 只发一条 `range=[0, len]`；剪映要的是**分段**的 styles，每段自己带颜色。
    实测参考稿就是这么存的：

        车里提前消杀好
          [0,4] #FFFFFF   [4,6] #F0E098   [6,7] #FFFFFF

    区间按**字符**计（和 capcut-cli 的 text-ranges 同一口径）。
    """
    colors = [base] * len(text)
    for r in ranges or []:
        for i in range(max(0, int(r["start"])), min(len(text), int(r["end"]))):
            colors[i] = r.get("font_color") or base
    out, i = [], 0
    while i < len(text):
        j = i
        while j + 1 < len(text) and colors[j + 1] == colors[i]:
            j += 1
        out.append((i, j + 1, colors[i]))
        i = j + 1
    return out


def apply_text_style(content: dict, cap_meta: list[dict], *, font_size: int = JY_FONT_SIZE,
                     base_color: str = "#FFFFFF") -> dict:
    """按 cap_meta 重写所有文字材质：多段 styles（关键词变色）+ 材质级样式。"""
    by_text: dict[str, dict] = {}
    for m in cap_meta:
        by_text[m["text"]] = m
    n_split = n_kw = 0
    for mat in content.get("materials", {}).get("texts", []):
        c = json.loads(mat["content"]) if isinstance(mat.get("content"), str) else mat.get("content")
        if not c:
            continue
        meta = by_text.get(c.get("text", ""))
        # 用 jy1 发的那条当模板（它带 strokes/字体等我们不想丢的字段）
        proto = (c.get("styles") or [{}])[0]
        pieces = split_keyword_ranges(c.get("text", ""), (meta or {}).get("ranges"), base_color)
        styles = []
        for a, b, col in pieces:
            s = json.loads(json.dumps(proto))          # 深拷贝，别共享嵌套 dict
            s["range"] = [a, b]
            s["size"] = font_size
            s.setdefault("fill", {}).setdefault("content", {}).setdefault("solid", {})["color"] = hex_to_rgb(col)
            styles.append(s)
            n_split += 1
        c["styles"] = styles
        n_kw += sum(1 for _, _, col in pieces if col != base_color)
        mat["content"] = json.dumps(c, ensure_ascii=False)
        mat["font_size"] = font_size
        mat["text_color"] = base_color
        mat["alignment"] = REF_MATERIAL_STYLE["alignment"]
        for k, v in REF_MATERIAL_STYLE.items():
            mat.setdefault(k, v)
    return {"styles": n_split, "keywords": n_kw, "texts": len(by_text)}


# ---------------------------------------------------------------- 交付层

def finalize(content: dict, *, name: str, draft_dir: Path, draft_box: Path,
             fps: int = 30) -> dict:
    """补 jy1 不做的交付层：platform 印记、身份字段、draft_info.json 副本。

    剪映 11.5 **读**明文 JSON 没问题，但它自己保存时会把 `draft_info.json` 与
    `draft_meta_info.json` **加密**（实测 21/24 个草稿如此）。所以 `draft_content.json`
    是第三方唯一能可靠读回的文件 —— 它**必须**一直写，而索引指向它。
    """
    now = int(time.time() * 1_000_000)
    did = str(uuid.uuid4())
    # jy1 模板硬编码 os=windows / app_version=5.9.0，我们是 mac + 11.5
    content["platform"] = {"app_source": "lv", "os": "mac"}
    content["id"] = did
    content["name"] = name
    content["fps"] = fps
    content["create_time"] = now
    content["update_time"] = now

    for key in ("draft_content.json", "draft_info.json"):
        (draft_dir / key).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    meta_f = draft_dir / "draft_meta_info.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.is_file() else {}
    assets = draft_dir / "assets"
    meta.update({
        "draft_id": did, "draft_name": name,
        "draft_fold_path": str(draft_box / name), "draft_root_path": str(draft_box),
        "draft_json_file": str(draft_box / name / "draft_content.json"),
        "tm_draft_create": now, "tm_draft_modified": now,
        "draft_timeline_materials_size": sum(f.stat().st_size for f in assets.rglob("*") if f.is_file())
        if assets.is_dir() else 0,
    })
    meta_f.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"id": did, "files": ["draft_content.json", "draft_info.json", "draft_meta_info.json"]}


# ---------------------------------------------------------------- 装机

def _capcut(*args: str) -> tuple[int, str]:
    r = subprocess.run(["capcut", *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def install(draft_dir: Path, *, draft_box: Path) -> dict:
    """交给 capcut-cli：staging 素材 + 补 local_material_id + 修引用。

    jy1 用绝对路径、不把素材复制进草稿、不写 `local_material_id` —— 这三条剪映
    都会记账（`media-outside-draft` / `media-unlinked` / `media-unregistered`），
    在 macOS 上 `~/Documents` 还是权限保护目录，可能直接报「无访问权限」。
    """
    out = {"steps": []}
    rc, txt = _capcut("register", str(draft_dir), "--materials", "--apply")
    out["steps"].append({"cmd": "register --materials --apply", "exit": rc})
    rc, txt = _capcut("lint", str(draft_dir), "--fix")
    out["steps"].append({"cmd": "lint --fix", "exit": rc})
    rc, txt = _capcut("lint", str(draft_dir))
    out["lint_ok"] = (rc == 0)
    out["lint_tail"] = txt.strip().splitlines()[-1][:160] if txt.strip() else ""
    return out


def register_in_store(draft_dir: Path, *, draft_box: Path, name: str) -> dict:
    """把草稿登记进剪映草稿箱索引（照抄一条剪映接受过的条目的 38 个字段）。

    ⚠️ 剪映运行时可能用内存里的列表回写 `root_meta_info.json` 把新条目冲掉 ——
    装之前先退出剪映。
    """
    root_f = draft_box / "root_meta_info.json"
    if not root_f.is_file():
        return {"registered": False, "reason": "找不到 root_meta_info.json"}
    root = json.loads(root_f.read_text(encoding="utf-8"))
    store = root.setdefault("all_draft_store", [])
    store[:] = [e for e in store if e.get("draft_name") != name]
    sample = next((e for e in store if e.get("draft_id")), None)
    if sample is None:
        return {"registered": False, "reason": "索引里没有可照抄的条目形状"}

    meta = json.loads((draft_dir / "draft_meta_info.json").read_text(encoding="utf-8"))
    entry = dict(sample)
    entry.update({
        "draft_id": meta["draft_id"], "draft_name": name,
        "draft_fold_path": str(draft_dir), "draft_root_path": str(draft_box),
        "draft_json_file": str(draft_dir / "draft_content.json"),
        "draft_cover": str(draft_dir / "draft_cover.jpg"),
        "draft_timeline_materials_size": meta.get("draft_timeline_materials_size", 0),
        "tm_draft_create": meta["tm_draft_create"], "tm_draft_modified": meta["tm_draft_modified"],
        "tm_duration": int(json.loads((draft_dir / "draft_content.json").read_text())["duration"]),
    })
    store.append(entry)
    root_f.write_text(json.dumps(root, ensure_ascii=False), encoding="utf-8")
    return {"registered": True, "entries": len(store)}


# ---------------------------------------------------------------- 驱动

def build(cfg: dict, project: Path, name: str, *, draft_box: Path, stage: Path,
          force: bool = False, do_install: bool = True, register: bool = True) -> dict:
    """把工程建成剪映草稿，走混合后端。轨道布局与 make_jianying_draft.py 一致。"""
    from _common import project_paths, resolve_duration, resolve_video
    from make_jianying_draft import build_captions, main_video_segments, overlay_windows

    jy = load_lib()
    p = project_paths(project)
    graded = p["work"] / "graded.mp4"
    overlay = p["work"] / "body-anim-silent.mp4"
    if not graded.is_file():
        raise SystemExit(f"缺 {graded}，先跑 run_all.py（frames/render）")
    src = resolve_video(cfg, project)
    total = resolve_duration(cfg, project)
    w = int(cfg["canvas"]["width"]); h = int(cfg["canvas"]["height"]); fps = int(cfg["canvas"]["fps"])

    # 字幕（复用现有实现：它已经算好了关键词字符区间）
    _srt, cap_meta, _ = build_captions(cfg, project, total)

    stage.mkdir(parents=True, exist_ok=True)
    target = stage / name
    if target.exists():
        if not force:
            raise SystemExit(f"{target} 已存在，加 --force 或换 --name")
        shutil.rmtree(target)

    # ── 1) jy1 写内容
    folder = jy.DraftFolder(str(stage))
    script = folder.create_draft(name, w, h, fps, allow_replace=True)
    script.append_tracks([
        jy.TrackSpec(jy.TrackType.video, "video"),
        jy.TrackSpec(jy.TrackType.video, "包装层"),
        jy.TrackSpec(jy.TrackType.audio, "人声"),
        jy.TrackSpec(jy.TrackType.audio, "音效"),
        jy.TrackSpec(jy.TrackType.audio, "旁白"),
        jy.TrackSpec(jy.TrackType.audio, "BGM"),
        jy.TrackSpec(jy.TrackType.text, "字幕"),
    ])

    pos = 0.0
    for dur in main_video_segments(cfg, project, total):
        script.add_segment(jy.VideoSegment(
            str(graded), jy.trange_seconds(pos, duration=dur),
            source_timerange=jy.trange_seconds(pos, duration=dur)), "video")
        pos += dur

    wins = overlay_windows(cfg, total)
    if overlay.is_file():
        for _label, a, b in wins:
            script.add_segment(jy.VideoSegment(
                str(overlay), jy.trange_seconds(a, duration=b - a),
                source_timerange=jy.trange_seconds(a, duration=b - a)), "包装层")

    # 人声：从成片里剥出来的那条（已归一过电平）
    voice = stage / "voice.wav"
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-vn",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(voice)], check=True)
    script.add_segment(jy.AudioSegment(str(voice), jy.trange_seconds(0, duration=total),
                                       volume=1.0), "人声")
    aud = ["人声"]
    for track, f, key in (("音效", p["work"] / "sfx-track.wav", "sfx_volume"),
                          ("旁白", p["work"] / "voice.wav", "narration_volume"),
                          ("BGM", p["work"] / "bgm.wav", "bgm_volume")):
        if not f.is_file():
            continue
        seg = jy.AudioSegment(str(f), jy.trange_seconds(0, duration=total),
                              volume=float(cfg["audio"][key]))
        if track == "BGM":
            seg.add_fade("1.6s", "2.4s")     # 与 tools/make_bgm.py 的包络对齐
        script.add_segment(seg, track)
        aud.append(track)

    for i, m in enumerate(cap_meta):
        seg = jy.TextSegment(
            m["text"], jy.trange_seconds(m["start"], duration=m["end"] - m["start"]),
            style=jy.TextStyle(size=JY_FONT_SIZE, color=(1.0, 1.0, 1.0), align=1,
                               line_spacing=0.02, max_line_width=0.82),
            border=jy.TextBorder(color=(0.0, 0.0, 0.0), width=0.08),
            shadow=jy.TextShadow(),
            clip_settings=jy.ClipSettings(transform_y=JY_TEXT_Y))
        anim = m.get("jy_anim") or ANIM_PLAN[i % len(ANIM_PLAN)]
        seg.add_animation(getattr(jy.TextIntro, anim), duration=jy.tim("0.30s"))
        seg.add_animation(jy.TextOutro.渐隐, duration=jy.tim("0.20s"))
        script.add_segment(seg, "字幕")
    script.save()

    naive = target / "draft_content.json"
    content = json.loads(naive.read_text(encoding="utf-8"))
    content["duration"] = int(round(total * 1_000_000))   # jy1 只按最后片段算，回正到片长

    # ── 2) 本模块：关键词变色 + 交付层
    st = apply_text_style(content, cap_meta)
    fin = finalize(content, name=name, draft_dir=target, draft_box=draft_box, fps=fps)

    report = {"backend": "jy1+capcut", "draft": str(target), "name": name,
              "duration": total, "texts": st["texts"], "styles": st["styles"],
              "keywords": st["keywords"],
              "main_segments": len(main_video_segments(cfg, project, total)),
              "overlay": [w_[0] for w_ in wins], "audio": aud,
              "id": fin["id"], "installed_to": None, "lint_ok": None}

    # ── 3) capcut-cli：装机
    dest = draft_box / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(target, dest)
    if do_install:
        ins = install(dest, draft_box=draft_box)
        report["installed_to"] = str(dest)
        report["lint_ok"] = ins["lint_ok"]
        report["install_steps"] = ins["steps"]
    if register:
        report["register"] = register_in_store(dest, draft_box=draft_box, name=name)
    write_json(p["work"] / "jianying-draft-jy1.json", report)
    return report


def main() -> None:
    import argparse
    from _common import load_config

    ap = argparse.ArgumentParser(description="混合后端建剪映草稿（jy1 内容 + capcut 交付）")
    ap.add_argument("project")
    ap.add_argument("--name", default=None, help="草稿名（默认取 config 的 jianying.name + _jy1）")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-install", action="store_true", help="只生成，不复制进草稿箱")
    ap.add_argument("--no-register", action="store_true", help="不写索引（剪映在跑时用）")
    ap.add_argument("--out", default=None, help="草稿箱路径")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    cfg = load_config(project / "config.json")
    name = a.name or f"{cfg['jianying']['name']}_jy1"
    box = Path(a.out).expanduser() if a.out else Path(
        os.path.expanduser(cfg["jianying"].get("store") or
                           "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft"))
    stage = project / "work" / "jy1-stage"
    r = build(cfg, project, name, draft_box=box, stage=stage, force=a.force,
              do_install=not a.no_install, register=not a.no_register)
    print(f"  草稿 {r['draft']}")
    print(f"  字幕 {r['texts']} 条 / 样式段 {r['styles']} / 关键词上色 {r['keywords']} 处")
    print(f"  主轨 {r['main_segments']} 段 / 包装层 {r['overlay'] or '无'} / 音频 {'+'.join(r['audio'])}")
    if r["installed_to"]:
        print(f"  已装机 → {r['installed_to']}   lint {'干净' if r['lint_ok'] else '有问题'}")
    if r.get("register"):
        print(f"  登记 {r['register']}")


if __name__ == "__main__":
    main()
