#!/usr/bin/env python3
"""SRT → ASS。字幕从「跟读工具」变成「画面设计的一部分」。

三件事：
  1. 去标点（房规，可用 captions.strip_punctuation=false 关掉）
  2. 关键词换色：SRT 里写 [[词]] 走强调色、((词)) 走反差色、| 强制换行
  3. 首句 hook：超大字砸出再缩回常规字号（复刻参考片的开场）

字号自适应：一行放不下就按最长行等比缩小，不会溢出到画面外。

用法：python scripts/make_captions.py PROJECT_DIR
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    ass_color, find_font, font_display_name, load_config, parse_caption_text, parse_srt,
    project_paths, strip_cue_directive, strip_punct, ts_ass, write_json,
)


def _paint(parts, palette, strip: bool, strip_on: bool = True) -> str:
    """把 [(片段, 角色)] 拼成一行 ASS 文本，角色决定换色。"""
    out = ""
    for text, role in parts:
        text = strip_punct(text) if (strip and strip_on) else text
        if not text:
            continue
        if role:
            out += r"{\c" + ass_color(palette[role]) + "}" + text + r"{\c" + ass_color(palette["white"]) + "}"
        else:
            out += text
    return out


def build(cfg: dict, project: Path) -> dict:
    p = project_paths(project)
    srt = p["input"] / (cfg["input"]["subtitle"] or "captions.srt")
    if not srt.is_file():
        raise SystemExit(f"找不到字幕：{srt}")

    # 全自动 Vlog 可能只有旁白、没有画面字幕；captions.mode=burned-in/none
    # 也表示源片已有字幕或明确不要字幕。空 SRT 不是错误：生成一个没有
    # Dialogue 的合法 ASS，让 captions/frames/draft 都能继续走。
    caption_mode = str((cfg.get("captions") or {}).get("mode") or "generated")
    if not parse_srt(srt) or caption_mode in ("burned-in", "none"):
        cap = cfg["captions"]
        cw, ch = cfg["canvas"]["width"], cfg["canvas"]["height"]
        out_ass = p["captions"] / "final.ass"
        out_ass.parent.mkdir(parents=True, exist_ok=True)
        out_ass.write_text(f"""[Script Info]
Title: {cfg['name']}
ScriptType: v4.00+
PlayResX: {cw}
PlayResY: {ch}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Noto Sans CJK SC,{cap['size']},{ass_color(cap['palette']['white'])},{ass_color(cap['palette']['white'])},{ass_color(cap['palette']['outline'])},&H7A000000,0,0,0,0,100,100,{cap['spacing']},0,1,{cap['outline']},{cap['shadow']},2,{cap['margin_lr']},{cap['margin_lr']},{cap['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""", encoding="utf-8")
        write_json(p["work"] / "captions.json",
                   {"strip_punctuation": bool(cap["strip_punctuation"]), "cues": []})
        print(f"  画面字幕模式 {caption_mode}：生成空 ASS，不叠加字幕")
        return {"count": 0}

    from workflow.caption_timing import overlap_status
    timing_ok, timing_detail = overlap_status(
        srt, int(cfg["canvas"]["fps"]),
        {int(i) for i in (cfg["captions"].get("skip") or [])})
    if timing_ok is not True:
        raise SystemExit(f"字幕预检未通过：{timing_detail}")

    cap = cfg["captions"]
    cw, ch = cfg["canvas"]["width"], cfg["canvas"]["height"]
    strip_on = bool(cap["strip_punctuation"])
    out_ass = p["captions"] / "final.ass"

    # ASS 的 Fontname 必须是**字体自称的族名**，不能是 config 里写的文件名关键词：
    # libass 拿 Fontname 去 fontsdir 里查族名，写 `AlimamaShuHeiTi` 它一个都认不出来，
    # 中文就整屏方框（captions.burn="ass" 这条路上踩过的坑）。
    ass_font = font_display_name(find_font(cap["font"], project))

    head = f"""[Script Info]
Title: {cfg['name']}
ScriptType: v4.00+
PlayResX: {cw}
PlayResY: {ch}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{ass_font},{cap['size']},{ass_color(cap['palette']['white'])},{ass_color(cap['palette']['white'])},{ass_color(cap['palette']['outline'])},&H7A000000,0,0,0,0,100,100,{cap['spacing']},0,1,{cap['outline']},{cap['shadow']},2,{cap['margin_lr']},{cap['margin_lr']},{cap['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    hook = cap["hook"]
    skip = {int(i) for i in (cap.get("skip") or [])}
    # 字幕这一步顺手把逐条样式计划落盘（captions 步在 frames/draft 之前跑），
    # 后面 build_frames 与 make_jianying_draft 都读这一份，不各自推导。
    from workflow.caption_plan import load as load_caption_plan
    load_caption_plan(cfg, project)
    rows, meta = [], []
    for cue in parse_srt(srt):
        if cue["index"] in skip:
            continue
        # 逐条指令 `{@...}` 是控制语法，不能画进画面：layer 那条路在 caption_layer
        # 里消费它，ass 这条路至少要先把它脱掉（样式本身仍以 layer 为正本）。
        lines = [strip_cue_directive(ln) for ln in cue["lines"] if ln.strip()]
        lines = [ln for ln in lines if ln.strip()]
        if not lines:
            continue
        rendered = [_paint(parse_caption_text(ln), cap["palette"], strip_on) for ln in lines]
        plain = [strip_punct("".join(t for t, _ in parse_caption_text(ln)))
                 for ln in lines] if strip_on else lines
        longest = max(len(x) for x in plain)
        size = min(cap["size"], int(cap["max_width"] / longest)) if longest else cap["size"]
        override = "" if size == cap["size"] else f"{{\\fs{size}}}"
        body = r"\N".join(rendered)

        is_hook = hook["enabled"] and not meta
        if is_hook:
            # 参考片就是「砸下来再缩」：起手 330%，accel 2.6 表示前段几乎不动、末尾快速收回。
            # 别用 0.35 这类小 accel —— 那会在开头 0.15s 就把缩放走完，大字根本看不见。
            body = (f"{{\\fad(50,0)\\fscx{hook['scale']}\\fscy{hook['scale']}"
                    f"\\bord{max(1, round(cap['outline'] * 0.25))}"
                    f"\\t(0,{hook['ms']},{hook['accel']},\\fscx100\\fscy100\\bord{cap['outline']})}}"
                    f"{body}")
        else:
            body = (f"{{\\fad({cap['fade_in_ms']},{cap['fade_out_ms']})}}") + body

        rows.append(f"Dialogue: 0,{ts_ass(cue['start'])},{ts_ass(cue['end'])},Cap,,0,0,0,,"
                    f"{override}{body}")
        meta.append({"index": cue["index"], "start": round(cue["start"], 3),
                     "end": round(cue["end"], 3), "plain": "".join(plain),
                     "lines": plain, "size": size, "hook": is_hook})

    out_ass.parent.mkdir(parents=True, exist_ok=True)
    out_ass.write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    write_json(p["work"] / "captions.json", {"strip_punctuation": strip_on, "cues": meta})
    print(f"  captions/final.ass  {len(rows)} 条"
          f"（{sum(1 for m in meta if m['size'] < cap['size'])} 条缩字号，"
          f"跳过 {len(skip)} 条，标点{'已去除' if strip_on else '保留'}）")
    if strip_on:
        bad = [m["plain"] for m in meta if any(c in m["plain"] for c in "，。！？、；：")]
        if bad:
            print(f"  ⚠ 仍有标点残留：{bad[:3]}")
    return {"count": len(rows)}


def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    build(load_config(project_paths(project)["config"]), project)


if __name__ == "__main__":
    main()
