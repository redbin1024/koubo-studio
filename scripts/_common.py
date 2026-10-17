#!/usr/bin/env python3
"""共用工具：ffmpeg/字体定位、配置与房规默认值、颜色、缓动、时间码、字幕标记解析。

「房规」写在这里，全流程共用一份真相：
  - 字幕与画面文案默认去掉标点（竖屏快读时标点是噪音）
  - 不做开头封面、不做片尾卡、不做常驻标题
用户显式在 config.json 里改，才会生效。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------- 环境与定位

APP_NAME = "koubo-studio"
ENV_PREFIX = "KOUBO"
LEGACY_ENV_PREFIX = "THSP"          # 旧版环境变量前缀，保留兼容


def env_get(name: str, default: str | None = None) -> str | None:
    """读 `KOUBO_<name>`；没设时回退到旧版 `THSP_<name>`。

    改名不能把老用户的配置一夜作废：新变量优先，旧变量仍然认。
    """
    for prefix in (ENV_PREFIX, LEGACY_ENV_PREFIX):
        value = os.environ.get(f"{prefix}_{name}")
        if value is not None:
            return value
    return default


def repo_root() -> Path:
    """本仓/本安装目录的根（`scripts/_common.py` 的上两级）。"""
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- 外部依赖定位

_FFMPEG_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
)


def find_ffmpeg() -> str:
    """优先 ffmpeg-full：Homebrew 的 full build 才带 libass 字幕烧录与完整 gblur 参数。"""
    env = env_get("FFMPEG")
    if env and Path(env).is_file():
        return env
    bundled = repo_root() / "vendor" / "bin" / "ffmpeg"
    if bundled.is_file():
        return str(bundled)
    for p in _FFMPEG_CANDIDATES:
        if Path(p).is_file():
            return p
    found = shutil.which("ffmpeg")
    if not found:
        raise SystemExit(
            "找不到 ffmpeg。macOS 建议 `brew install ffmpeg-full`，"
            "Ubuntu 用 `apt install ffmpeg`（需要带 libass 的构建）。"
        )
    return found


def find_ffprobe() -> str:
    env = env_get("FFPROBE")
    if env and Path(env).is_file():
        return env
    cand = Path(find_ffmpeg()).parent / "ffprobe"
    if cand.is_file():
        return str(cand)
    return shutil.which("ffprobe") or "ffprobe"


FONT_SEARCH_DIRS = (
    Path.home() / "Library/Fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".local/share/fonts",
)

# 中文字体候选：按「越粗越优先」排列，第一个存在的就是默认
CJK_FONT_CANDIDATES = (
    "NotoSansCJKsc-Black.otf",
    "NotoSansCJKsc-Bold.otf",
    "NotoSansSC-Black.otf",
    "SourceHanSansSC-Bold.otf",
    "SourceHanSansSC-Heavy.otf",
    "PingFang.ttc",
    "Hiragino Sans GB.ttc",
    "msyhbd.ttc",
)

FONT_SUFFIXES = (".otf", ".ttf", ".ttc")
FONT_DIRS_ENV = "KOUBO_FONT_DIRS"     # 冒号分隔，排在工程 fonts/ 与安装目录 fonts/ 之后
INSTALL_FONT_DIR = repo_root() / "fonts"


def extra_font_dirs(project: str | Path | None = None) -> list[Path]:
    """候选字体目录，按优先级：工程 `fonts/` → 安装目录 `fonts/` → `KOUBO_FONT_DIRS` → 系统目录。

    顺序是有意的：工程字体必须压过同名的系统字体，否则「把 ttf 丢进工程 fonts/
    就能换字体」会被系统里装过的同族字体悄悄顶掉 —— 而那正是用户报的
    「换了字体没反应」的成因之一。安装目录的 `fonts/` 让一键安装下载的字体
    不需要写进每个人的系统字体目录。
    """
    out: list[Path] = []
    if project is not None:
        out.append(Path(project) / "fonts")
    out.append(INSTALL_FONT_DIR)
    for p in (env_get("FONT_DIRS") or "").split(os.pathsep):
        if p.strip():
            out.append(Path(p).expanduser())
    return [d for d in out if d.is_dir()]


EMOJI_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/noto/NotoColorEmoji.ttf"),
)


def find_fonts_dir(project: str | Path | None = None) -> str:
    """给 libass 的 fontsdir。

    坑：把 fontsdir 指到 /System/Library/Fonts 会让中文字幕渲染成方框，
    必须指向真正装了 CJK 字体的目录（macOS 上是 ~/Library/Fonts）。

    工程自带 fonts/ 时优先用它 —— libass 的 fontsdir 会**加进** fontconfig 的
    应用字体集，不是替换系统字体，所以指到项目目录不会让别的字变方框。
    """
    env = env_get("FONTS_DIR")
    if env:
        return env
    extra = extra_font_dirs(project)
    if extra:
        return str(extra[0])
    home_fonts = Path.home() / "Library/Fonts"
    if home_fonts.is_dir():
        return str(home_fonts)
    if (Path("/usr/share/fonts")).is_dir():
        return "/usr/share/fonts"
    return str(home_fonts)


def _name_key(s: str | None) -> str:
    """字体名归一化：小写、去掉空格与常见分隔符，**保留中文**。

    老实现只留 `[a-z0-9]`，于是「阿里妈妈数黑体」「优设标题黑」「得意黑」全被归一化成
    空串；空串是所有名字的子串（老代码专门挡了这一点），结果就是匹配不到 →
    `find_font` 静默回落到 Noto。用户把字体丢进 `fonts/`、把中文族名写进 config，
    渲出来一模一样，观感就是「字体根本换不了」。
    """
    return re.sub(r"[\s\-_·．.,，、（）()\[\]]+", "", (s or "").lower())


# name 表里跟「这字体叫什么」有关的记录：1 族名 / 2 字重 / 4 全名 / 6 PS 名 /
# 16 排版族名 / 17 排版字重。中文名常只出现在 16（阿里妈妈数黑体）或 1（优设标题黑）。
_FONT_NAME_IDS = (1, 2, 4, 6, 16, 17)


def _font_name_records(path: Path) -> list[tuple[int, str]]:
    """读 TTF/OTF/TTC 的 name 表 → [(nameID, 字符串)]。不依赖 fontTools。

    PIL 的 `getname()` 只给英文族名/字重，而中文名只存在于 name 表里 ——
    用户脑子里记的就是中文名，不把它读出来就永远匹配不上。
    """
    try:
        d = path.read_bytes()
    except OSError:
        return []
    base = 0
    if d[:4] == b"ttcf":                              # 字体集合：取第一个字体
        if len(d) < 16:
            return []
        base = struct.unpack(">I", d[12:16])[0]
    if base + 12 > len(d):
        return []
    n_tables = struct.unpack(">H", d[base + 4:base + 6])[0]
    name_off = name_len = 0
    for i in range(n_tables):
        rec = base + 12 + 16 * i
        if rec + 16 > len(d):
            break
        if d[rec:rec + 4] == b"name":
            name_off, name_len = struct.unpack(">II", d[rec + 8:rec + 16])
            break
    if not name_off or name_off + 6 > len(d):
        return []
    count, str_off = struct.unpack(">HH", d[name_off + 2:name_off + 6])
    out: list[tuple[int, str]] = []
    for i in range(count):
        r = name_off + 6 + 12 * i
        if r + 12 > len(d):
            break
        pid, _eid, _lid, nid, ln, off = struct.unpack(">HHHHHH", d[r:r + 12])
        if nid not in _FONT_NAME_IDS:
            continue
        raw = d[name_off + str_off + off: name_off + str_off + off + ln]
        # platform 0/3 = Unicode（UTF-16BE）；platform 1 = Mac，中文记录是 GBK
        encs = ("utf-16-be",) if pid in (0, 3) else ("gbk", "latin-1")
        for enc in encs:
            try:
                out.append((nid, raw.decode(enc).strip()))
                break
            except (UnicodeDecodeError, LookupError):
                continue
    return out


@dataclass(frozen=True)
class FontEntry:
    """一个字体文件「自称」的身份 —— 全部来自文件本身，不猜文件名。"""
    path: Path
    families: frozenset[str]      # 归一化族名别名（含中文）
    styles: frozenset[str]        # 归一化字重别名
    display: str                  # 真实族名：给 ASS Fontname、给报错信息、给人看
    style_display: str            # 真实字重（Regular / Bold / Black …）
    stem: str                     # 归一化文件名，兜底匹配用

    @property
    def suggest(self) -> str:
        """config 里 `captions.font` 直接能用的写法：Regular 不必带字重。"""
        if not self.style_display or self.style_display.lower() in ("regular", "plain", "book"):
            return self.display
        return f"{self.display} {self.style_display}"


_FONT_INDEX: dict[str, list[FontEntry]] = {}

# 字重排序，用来在「没指定字重」时优先挑更粗的（字幕/卡面要粗体）
_WEIGHT_RANK = ("thin", "extralight", "ultralight", "light", "demilight", "regular",
                "normal", "book", "medium", "demibold", "semibold", "bold",
                "extrabold", "heavy", "black")


def _weight_rank(keys) -> int:
    best = -1
    for k in keys if not isinstance(keys, str) else (keys,):
        for i, w in enumerate(_WEIGHT_RANK):
            if w in k:
                best = max(best, i)
    return best


def _font_entry(path: Path) -> FontEntry:
    recs = _font_name_records(path)
    fams, styles = set(), set()
    for nid, txt in recs:
        k = _name_key(txt)
        if not k:
            continue
        (fams if nid in (1, 4, 6, 16) else styles).add(k)
    display = ""
    style_display = ""
    try:                                    # PIL 给的族名是 ASS/libass 认的那个
        from PIL import ImageFont
        fam, sty = ImageFont.truetype(str(path), 20).getname()
        display = (fam or "").strip()
        style_display = (sty or "").strip()
        if fam:
            fams.add(_name_key(fam))
        if sty:
            styles.add(_name_key(sty))
    except Exception:
        pass
    if not display:
        display = next((t for nid, t in recs if nid == 1), path.stem)
    if not style_display:
        style_display = next((t for nid, t in recs if nid in (2, 17)), "")
    # 中文名（nameID 16 排版族名 / 1 族名）也进族名别名 —— 用户记的就是这个
    for nid, txt in recs:
        if nid in (1, 16) and re.search(r"[\u4e00-\u9fff]", txt):
            fams.add(_name_key(txt))
    return FontEntry(path, frozenset(fams), frozenset(styles), display, style_display,
                     _name_key(path.stem))


def _index_dir(d: Path) -> list[FontEntry]:
    """扫一个目录并读每个字体的真实名字。**只有第一趟（文件名）失手才会走到这里**，
    所以这个「每个文件都读一遍 name 表」的成本平时不用付。"""
    key = str(d)
    hit = _FONT_INDEX.get(key)
    if hit is None:
        hit = []
        for f in sorted(d.rglob("*")):
            if f.suffix.lower() not in FONT_SUFFIXES:
                continue
            try:
                hit.append(_font_entry(f))
            except Exception:
                continue
        _FONT_INDEX[key] = hit
    return hit


def _style_score(keys, want: str) -> int:
    if not want:
        return 0
    ks = (keys,) if isinstance(keys, str) else keys
    if want in ks:
        return 30
    return 15 if any(want in k for k in ks) else 0


def match_font(family: str | None = None, weight: str | None = None,
               project: str | Path | None = None) -> Path | None:
    """在字体目录里按族名/文件名找字体，找不到返回 None。

    两趟匹配，快的那趟先走：
      1. **文件名**（不读文件，快）—— 兼容 `AlimamaShuHeiTi`、`SmileySans` 这类写法；
      2. 字体**真实的族名**（读 name 表，含中文）—— `阿里妈妈数黑体`、`优设标题黑`
         这些中文名只有这条路能匹配上。

    每一趟都按 工程 `fonts/` → 安装目录 `fonts/` → `KOUBO_FONT_DIRS` → 系统目录 的顺序，**第一个有命中的
    目录就定案**：同一族里字重不全时（阿里妈妈数黑体只有 Bold），也要用工程里那个，
    不能因为系统里有个字重更全的同族就跨目录拼字。
    """
    fam = _name_key(family)
    if len(fam) < 2:                      # 空串/单字符是所有名字的子串，必须挡掉
        return None
    want_w = _name_key(weight)
    dirs = extra_font_dirs(project) + list(FONT_SEARCH_DIRS)

    for d in dirs:                        # 第 1 趟：文件名
        if not d.is_dir():
            continue
        cands = []
        for f in sorted(d.rglob("*")):
            if f.suffix.lower() not in FONT_SUFFIXES:
                continue
            stem = _name_key(f.stem)
            if fam in stem:
                cands.append((_style_score(stem, want_w), _weight_rank(stem), str(f), f))
        if cands:
            cands.sort(key=lambda c: (-c[0], -c[1], c[2]))
            return cands[0][3]

    for d in dirs:                        # 第 2 趟：真实族名（含中文）
        if not d.is_dir():
            continue
        cands = []
        for e in _index_dir(d):
            hit = fam in e.families or any(
                (len(fam) >= 2 and len(a) >= 2) and (fam in a or a in fam)
                for a in e.families)
            if hit:
                cands.append((_style_score(e.styles, want_w), _weight_rank(e.styles),
                              str(e.path), e.path))
        if cands:
            cands.sort(key=lambda c: (-c[0], -c[1], c[2]))
            return cands[0][3]
    return None


def font_display_name(path: str | Path) -> str:
    """字体文件自称的族名 —— 写进 ASS 的 Fontname 必须是这个，不能是文件名。"""
    try:
        return _font_entry(Path(path)).display
    except Exception:
        return Path(path).stem


def has_cjk_glyphs(path: str | Path) -> bool:
    """粗判这个字体有没有汉字。

    拿一个私用区码位（U+E000，正常字体一定没有）的渲染结果当「.notdef 长什么样」，
    再和「永」比：一样就说明汉字走的是 .notdef（渲染出来是豆腐块）。
    """
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(str(path), 40)
        return bytes(f.getmask("永")) != bytes(f.getmask("\ue000"))
    except Exception:
        return True                        # 判不了就不拦


def _available_families(project: str | Path | None = None, limit: int = 14) -> list[str]:
    """给报错信息用的「你能写什么」列表。**只收带汉字的字体** —— 系统里几百个
    Latin 字体对中文字幕毫无用处，混进来只会把真正有用的那几个淹掉。"""
    out: list[str] = []
    for d in extra_font_dirs(project) + list(FONT_SEARCH_DIRS):
        if not d.is_dir():
            continue
        for e in _index_dir(d):
            if not e.display or e.display in out:
                continue
            if not has_cjk_glyphs(e.path):
                continue
            out.append(e.suggest)
            if len(out) >= limit:
                return out
    return out


def find_font(family: str | None = None, project: str | Path | None = None) -> Path:
    """按族名或文件名找字体文件。**找不到就抛错，不静默换字体。**

    族名中英文都认：`Noto Sans CJK SC Black`、`阿里妈妈数黑体`、`优设标题黑`、
    `AlimamaShuHeiTi` 都行 —— 中文名从字体的 name 表里读出来，不靠文件名猜。
    找的顺序是 工程 `fonts/` → 安装目录 `fonts/` → `KOUBO_FONT_DIRS` → 系统字体目录。

    `family` 留空才走兜底（第一个存在的中文字体候选）。写错名字会直接报错并列出
    可用的族名 —— 静默换一个字体渲出来「看着一样」，比报错难查一百倍。
    """
    if family:
        hit = match_font(family, project=project)
        if hit is not None:
            if not has_cjk_glyphs(hit):
                print(f"  ⚠ 字体 {hit.name}（{font_display_name(hit)}）没有汉字字形，"
                      f"中文字幕会渲染成方框；换一个带 CJK 的字体。", file=sys.stderr)
            return hit
        avail = _available_families(project)
        raise SystemExit(
            f"找不到字体「{family}」。\n"
            f"  · 找过的目录：{' → '.join(str(d) for d in extra_font_dirs(project) + list(FONT_SEARCH_DIRS))}\n"
            f"  · 想加自己的字体：把 ttf/otf 丢进 {Path(project) / 'fonts' if project else '工程 fonts/'}，"
            f"captions.font 写族名（中英文都认）\n"
            f"  · 当前可用的族名（前 {len(avail)} 个）：{('、'.join(avail)) or '（一个都没扫到）'}\n"
            f"  · 列出全部：python3 scripts/list_fonts.py {project or '<PROJECT_DIR>'}")
    for name in CJK_FONT_CANDIDATES:
        for d in extra_font_dirs(project) + list(FONT_SEARCH_DIRS):
            cand = d / name
            if cand.is_file():
                return cand
    raise SystemExit(
        "找不到可用的中文字体。装一个思源黑体/Noto Sans CJK 即可：\n"
        "  macOS : brew install --cask font-noto-sans-cjk-sc\n"
        "  Ubuntu: apt install fonts-noto-cjk"
    )


def find_emoji_font() -> Path | None:
    env = env_get("EMOJI_FONT")
    if env and Path(env).is_file():
        return Path(env)
    for p in EMOJI_FONT_CANDIDATES:
        if p.is_file():
            return p
    return None


# ---------------------------------------------------------------- 配置与房规

HOUSE_RULES = {
    "strip_punctuation": True,
    "opening_cover": False,
    "end_card": False,
    "sticky_title": False,
}

PUNCT_CHARS = "，。！？、；：…—·「」『』（）【】《》〈〉“”‘’,.!?;:\"'()[]<>-~　"


# 字幕主题：一组「字体 + 强调色」预设的正本。captions.theme 选一个，
# 它只当**默认值**用 —— config 里显式写的 font / palette 仍然压过它。
# 字体必须写**本机真装了的族名**（写错会直接报错并列可用族名，不会静默换字体）；
# 想用别的字体把 ttf/otf 丢进工程 fonts/ 目录即可，不必装进系统。
CAPTION_THEMES = {
    "brand-warm": {"font": "Noto Sans CJK SC Black",
                   "accent": "#F5E14A", "contrast": "#FF6284"},
    "screen-clean": {"font": "Hiragino Sans GB W6",
                     "accent": "#4DD0E1", "contrast": "#FF8A65"},
    "news-bold": {"font": "Noto Sans CJK SC Black",
                  "accent": "#FFD400", "contrast": "#FF3B30"},
}


def strip_punct(text: str) -> str:
    """去掉标点与多余人声停顿符。房规默认开启，可用 captions.strip_punctuation=false 关掉。"""
    for ch in PUNCT_CHARS:
        text = text.replace(ch, "")
    return re.sub(r"\s{2,}", " ", text).strip()


def apply_defaults(cfg: dict) -> dict:
    """补齐所有默认值。所有脚本都通过 load_config 走这里，保证房规全局一致。"""
    cfg.setdefault("name", "koubo-project")
    cv = cfg.setdefault("canvas", {})
    cv.setdefault("width", 1080)
    cv.setdefault("height", 1920)
    cv.setdefault("fps", 30)

    inp = cfg.setdefault("input", {})
    inp.setdefault("video", None)
    # 外录音轨（双轨收音）。**不是占位键**，由 run_all 的 align 步骤消费：
    #   audio      单条素材的外录，配 input.video
    #   audio_map  {" <clip 相对路径>": "<外录路径>" }，配 input.clips
    # 换轨产物记在 work/align-report.json，resolve_video / merge_cut 查表后会用它。
    inp.setdefault("audio", None)
    inp.setdefault("audio_map", {})
    inp.setdefault("align", {"enabled": True, "threshold": 0.35})
    inp.setdefault("subtitle", "captions.srt")
    inp.setdefault("clips", [])

    cap = cfg.setdefault("captions", {})
    # 主题只是一组字体 + 配色预设；写了主题时它当**默认值**用，
    # config 里显式写了的键仍然压过主题（setdefault 的语义就是这么来的）。
    theme_name = str(cap.get("theme") or "")
    if theme_name:
        if theme_name not in CAPTION_THEMES:
            raise ValueError(f"没有这个字幕主题：{theme_name!r}；"
                             f"可用：{sorted(CAPTION_THEMES)}")
    theme = CAPTION_THEMES.get(theme_name, {})
    cap.setdefault("strip_punctuation", HOUSE_RULES["strip_punctuation"])
    cap.setdefault("font", theme.get("font", "Noto Sans CJK SC Black"))
    cap.setdefault("size", 90)
    cap.setdefault("outline", 10)
    cap.setdefault("shadow", 6)
    cap.setdefault("spacing", 1.5)
    cap.setdefault("margin_lr", 66)
    cap.setdefault("margin_v", 190)
    cap.setdefault("max_width", 948)
    cap.setdefault("fade_in_ms", 110)
    cap.setdefault("fade_out_ms", 130)
    # 入场动效（pop / rise / wipe）的时长。淡入淡出仍走 fade_in_ms/fade_out_ms ——
    # 110ms 的淡入是对的，110ms 的缩放位移则快到看不见。
    cap.setdefault("anim_ms", 320)
    cap.setdefault("hook", {"enabled": True, "scale": 330, "accel": 2.6, "ms": 600})
    # 逐条样式（见 workflow/caption_plan.py）。空表 + 没指令 = 加这套东西之前的逐条行为。
    cap.setdefault("layout", "bottom")
    cap.setdefault("styles", {})
    cap.setdefault("big", {"size": 132, "outline": 14, "shadow": 8, "tracking": 2.0})
    # 字幕烧法：layer = 合成阶段用 Pillow 画（字体从工程 fonts/ 拿，任何字体都能用）；
    # ass = 交回 libass。macOS 的 libass 只带 CoreText provider，不认 fontsdir，
    # 字体没装进系统就整屏方框 —— 所以默认走 layer。
    cap.setdefault("burn", "layer")
    # 卡段那几句不烧字幕：那一屏的卡片就是放大的字幕，重复会打架
    cap.setdefault("skip", [])
    pal = cap.setdefault("palette", {})
    pal.setdefault("white", "#FFFFFF")
    pal.setdefault("accent", theme.get("accent", "#F5E14A"))
    pal.setdefault("contrast", theme.get("contrast", "#FF6284"))
    if theme_name:
        # 主题**盖过** config 里的 font / 两个强调色，而不是给它们当默认值：
        # 生成的工程总是显式写着这三个键（new_project 就写），走 setdefault 的话
        # 主题永远不生效 —— 一个「永远不生效的开关」比没有这个开关更坏。
        # 换回默认观感就把 captions.theme 删掉，而不是去改这三个键。
        cap["font"] = theme["font"]
        pal["accent"] = theme["accent"]
        pal["contrast"] = theme["contrast"]
    pal.setdefault("gold", "#F2D26A")
    pal.setdefault("outline", "#000000")

    card = cfg.setdefault("card", {})
    card.setdefault("enabled", False)
    card.setdefault("start", 0.0)
    card.setdefault("end", 0.0)
    card.setdefault("title", "")
    card.setdefault("title_at", 0.0)
    card.setdefault("rows", [])
    card.setdefault("fill", "#A2A0A1")
    card.setdefault("edge", "#FAFAFA")
    card.setdefault("radius", 36)
    card.setdefault("edge_width", 15)
    card.setdefault("box", [0.114, 0.150, 0.878, 0.855])   # 归一化，参考片实测值
    card.setdefault("wipe", 0.22)

    pip = cfg.setdefault("pip", {})
    pip.setdefault("enabled", card["enabled"])
    pip.setdefault("box", [0.5, 0.4896, 1.0, 1.0])
    pip.setdefault("radius", 56)
    pip.setdefault("at", 0.0)
    pip.setdefault("dur", 0.34)
    pip.setdefault("crop_height", 1150)
    pip.setdefault("center", [0.555, 0.432])

    gold = cfg.setdefault("gold", {})
    gold.setdefault("enabled", False)
    gold.setdefault("text", "")
    gold.setdefault("in", 0.0)
    gold.setdefault("out", 0.0)
    gold.setdefault("size", 120)

    # 插图画面：**全部由脚本自己画**（make_assets 出 PNG，build_frames 逐帧合成），
    # 不引外部图片、不联网找素材。每条必须由字幕关键词触发（触发词必须在字幕里真的
    # 存在），不做无意义装饰；框位不得压到字幕带（verify 会硬查）。
    ins = cfg.setdefault("inserts", {})
    ins.setdefault("enabled", False)
    ins.setdefault("layout", "band")        # band = 字幕带上方的横条卡；panel = 整屏图形段
    ins.setdefault("box", [0.10, 0.53, 0.90, 0.72])
    ins.setdefault("radius", 28)
    ins.setdefault("hold", 2.6)             # 单条默认停留时长（秒）
    ins.setdefault("theme", {})
    ins["theme"].setdefault("bg", "#FBF7EF")
    ins["theme"].setdefault("fg", "#241F1A")
    ins["theme"].setdefault("accent", "#E8B84B")
    ins.setdefault("items", [])

    sfx = cfg.setdefault("sfx", {})
    sfx.setdefault("events", [])

    # 剪映资源库里的特效 / 滤镜 / 转场 / 音效效果。
    # **只写进剪映草稿**：成片 mp4 是 ffmpeg 渲的，剪映不参与渲染 ——
    # 所以这一块是「最终从剪映导出」那条交付路线用的，不是 mp4 的效果。
    fx = cfg.setdefault("jianying_fx", {})
    fx.setdefault("enabled", False)
    fx.setdefault("namespace", "jianying")   # jianying = 剪映资源库；capcut = CapCut 命名空间
    fx.setdefault("effects", [])             # [{name 或 resource_id, at, dur}]
    fx.setdefault("filters", [])             # [{name, at, dur}]  dur 不写 = 覆盖全片
    fx.setdefault("transitions", [])         # [{at, name, dur}]  at = 主轨切点时间
    fx.setdefault("sfx", [])                 # [{name, at, dur, volume}]

    audio = cfg.setdefault("audio", {})
    # 本地合成 BGM（零素材零版权风险）。enabled=false 时整步跳过，行为与以前一致。
    audio.setdefault("bgm", {})
    audio["bgm"].setdefault("enabled", False)
    audio["bgm"].setdefault("mood", "warm")   # warm / calm / upbeat
    audio["bgm"].setdefault("bpm", 88)
    audio.setdefault("speech_mode", {"vlog": "narration", "talking-head": "source"}.get(
        cfg.get("mode")))
    audio.setdefault("voice_volume", 1.0)          # 现场声（input.video 的原声）
    audio.setdefault("sfx_volume", 0.80)
    # 可选的两条干轨，文件在 work/ 下，存在就自动进混音（不存在就跟以前完全一样）：
    #   work/voice.wav = 旁白；work/bgm.wav = 音乐床垫。
    # 旁白一走，现场声和 BGM 都做侧链闪避，人声才站得住。
    audio.setdefault("narration_volume", 1.0)
    audio.setdefault("bgm_volume", 0.25)
    audio.setdefault("duck", {"threshold": 0.08, "ratio": 3, "attack": 25, "release": 500})
    audio.setdefault("loudness", {"I": -14, "TP": -2.6, "LRA": 11})

    grade = cfg.setdefault("grade", {})
    grade.setdefault("enabled", True)
    grade.setdefault("eq", "eq=contrast=1.06:saturation=1.10:brightness=0.012")
    grade.setdefault("blur", "gblur=sigma=26")
    grade.setdefault("darken", 0.28)

    seg = cfg.setdefault("segments", {})
    seg.setdefault("fade_out", 0.40)

    cons = cfg.setdefault("constraints", {})
    for k, v in HOUSE_RULES.items():
        cons.setdefault(k, v)

    # 剪映草稿是每轮的固定产物之一（和 mp4 并列），所以默认值也在这里补齐
    jy = cfg.setdefault("jianying", {})
    jy.setdefault("name", cfg["name"])
    jy.setdefault("install", True)
    jy.setdefault("ratio", "9:16" if cv["height"] >= cv["width"] else "16:9")
    jy.setdefault("force_install", False)   # true = 连剪映改过的同名草稿也覆盖
    return cfg


def load_config(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"找不到配置：{p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    return apply_defaults(cfg)


def project_paths(project_dir: str | Path) -> dict:
    """项目的标准目录布局。所有脚本共用，禁止自行拼路径。"""
    a = Path(project_dir).resolve()
    return {
        "root": a,
        "input": a / "input",
        "work": a / "work",
        "assets": a / "assets",
        "captions": a / "captions",
        "output": a / "output",
        "draft_store": a / "draft-store",
        "config": a / "config.json",
    }


def ensure_dirs(project_dir: str | Path) -> dict:
    p = project_paths(project_dir)
    for k in ("input", "work", "assets", "captions", "output"):
        p[k].mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- 颜色

def hex_to_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    v = value.lstrip("#")
    if len(v) == 8:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), int(v[6:8], 16))
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), alpha)


def ass_color(value: str, alpha: int = 0) -> str:
    """#RRGGBB → ASS 的 &HAABBGGRR&（注意 ASS 是 BGR 序，且 00 = 不透明）。"""
    r, g, b, _ = hex_to_rgba(value)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}&"


def ass_override(value: str, alpha: int = 0) -> str:
    """ASS 行内换色：{\\c&H...&}"""
    return r"{\c" + ass_color(value, alpha) + "}"


def rgb_to_hex(rgb) -> str:
    r, g, b = (int(v) for v in rgb[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------- 缓动与时间码

def clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def ease(x: float) -> float:
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out(x: float) -> float:
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ts_ass(seconds: float) -> str:
    """ASS 时间码 H:MM:SS.cc"""
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def ts_srt(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_time(value: str) -> float:
    h, m, rest = value.strip().replace(".", ",").split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


# ---------------------------------------------------------------- 字幕标记

# 房规：字幕文本用轻量标记表达强调，避免在 config 里再维护一份行号映射表。
#   [[词]] → 正向强调色（palette.accent）
#   ((词)) → 反差强调色（palette.contrast）
#   |      → 强制换行
MARK_OPEN = {"[[": "accent", "((": "contrast"}
MARK_CLOSE = {"]]": "accent", "))": "contrast"}

# 逐条字幕指令 `{@样式 键=值}` 的**语法正本**（完整解析与报错在
# workflow/caption_plan.py）。这里只留一条「去掉行首指令」的轻量实现，
# 给 QC 扫标点、caption_plain 这类**不该看到指令**的地方用 ——
# 否则 `{@hero}` 会被当成字幕内容，误报「字幕里还有标点」。
CUE_DIRECTIVE_RE = re.compile(r"^\{@([^{}]*)\}")


def strip_cue_directive(text: str) -> str:
    """去掉行首的字幕指令，返回正文（含 `[[ ]]` 标记）。"""
    return CUE_DIRECTIVE_RE.sub("", text.lstrip(), count=1).lstrip()


def parse_caption_text(raw: str) -> list[tuple[str, str]]:
    """把带标记的字幕文本切成 [(片段, 角色)]，角色 ∈ {"", "accent", "contrast"}。"""
    out: list[tuple[str, str]] = []
    buf, role, i = "", "", 0
    while i < len(raw):
        two = raw[i:i + 2]
        if not role and two in MARK_OPEN:
            if buf:
                out.append((buf, role))
            buf, role, i = "", MARK_OPEN[two], i + 2
            continue
        if role and MARK_CLOSE.get(two) == role:
            if buf:
                out.append((buf, role))
            buf, role, i = "", "", i + 2
            continue
        buf += raw[i]
        i += 1
    if buf:
        out.append((buf, role))
    return out


def caption_plain(raw: str, strip: bool = True) -> str:
    """去掉标记与（可选的）标点，得到纯文本 —— 用于 QC 与卡片文案。"""
    text = "".join(seg for seg, _ in parse_caption_text(strip_cue_directive(raw)))
    text = text.replace("|", "")
    return strip_punct(text) if strip else text


def parse_srt(path: str | Path) -> list[dict]:
    """读 SRT。返回 [{index, start, end, raw, lines}]，lines 已按 | 与自然换行切开。"""
    text = Path(path).read_text(encoding="utf-8-sig")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = [r for r in block.strip().splitlines() if r.strip()]
        if len(rows) < 2:
            continue
        idx = int(rows[0].strip())
        start, _, end = rows[1].partition(" --> ")
        body = "|".join(rows[2:])
        cues.append({
            "index": idx,
            "start": parse_srt_time(start),
            "end": parse_srt_time(end),
            "raw": body,
            "lines": [ln for ln in body.replace("\n", "|").split("|") if ln != ""],
        })
    return cues


# ---------------------------------------------------------------- 进程

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """跑一条命令；失败时把 stderr 尾部带出来，不要静默吞掉。"""
    verbose = env_get("VERBOSE") == "1"
    if verbose:
        print("  $ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-12:])
        raise SystemExit(f"命令失败（exit {p.returncode}）：\n  {' '.join(str(c) for c in cmd)}\n{tail}")
    return p


def probe_media(path: str | Path) -> dict:
    """ffprobe。显式返回流顺序 —— HEVC 竖屏片常把音频排在 index 0，逐帧取像素必须 -map 0:v。"""
    out = run([
        find_ffprobe(), "-v", "error", "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate,duration,channels,sample_rate",
        "-show_entries", "format=duration,bit_rate", "-of", "json", str(path),
    ]).stdout
    data = json.loads(out or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    num, _, den = (video.get("r_frame_rate") or "0/1").partition("/")
    fps = (float(num) / float(den)) if float(den or 1) else 0.0
    return {
        "path": str(path),
        "duration": float(data.get("format", {}).get("duration") or video.get("duration") or 0.0),
        "width": video.get("width"), "height": video.get("height"),
        "fps": round(fps, 3), "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "video_index": video.get("index"), "audio_index": audio.get("index"),
        "has_audio": bool(audio),
        "sample_rate": audio.get("sample_rate"), "channels": audio.get("channels"),
        "note": "逐帧解码一律显式 -map 0:v，别依赖默认流选择。",
    }


def write_json(path: str | Path, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_bytes(cmd: list[str], **kw) -> bytes:
    """跑一条输出为二进制（rawvideo）的命令。"""
    verbose = env_get("VERBOSE") == "1"
    if verbose:
        print("  $ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    p = subprocess.run([str(c) for c in cmd], capture_output=True, **kw)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.decode("utf-8", "replace").strip().splitlines()[-12:])
        raise SystemExit(f"命令失败（exit {p.returncode}）：\n  {' '.join(str(c) for c in cmd)}\n{tail}")
    return p.stdout


def input_path(project_dir: str | Path, value: str) -> Path:
    """输入文件解析：绝对路径直接用（避免把大素材复制进项目），相对路径按 input/ 解。"""
    v = Path(value).expanduser()
    return v if v.is_absolute() else Path(project_dir).resolve() / "input" / v


ALIGN_REPORT = "align-report.json"


def load_align_report(project_dir: str | Path) -> dict:
    """读 work/align-report.json。没有就返回空表（= 没配外录，全走单轨）。"""
    f = Path(project_dir).resolve() / "work" / ALIGN_REPORT
    if not f.is_file():
        return {"swaps": {}}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"swaps": {}}
    d.setdefault("swaps", {})
    return d


def swapped_for(path: str | Path, project_dir: str | Path) -> Path:
    """若这条素材已经换过轨，返回换轨产物；否则原样返回。

    查表而不是改 config：原始素材永远留着（内录保底轨），换轨只是「这一轮用哪个」。
    """
    p = Path(path)
    hit = load_align_report(project_dir)["swaps"].get(str(p.resolve()))
    if hit and Path(hit).is_file():
        return Path(hit)
    return p


def resolve_video(cfg: dict, project_dir: str | Path) -> Path:
    """当前该处理哪条视频：优先 input.video，否则用粗剪产物 input/clean-cut.mp4。"""
    v = cfg["input"].get("video")
    if v:
        p = input_path(project_dir, v)
        if p.is_file():
            return swapped_for(p, project_dir)
    fallback = Path(project_dir).resolve() / "input" / "clean-cut.mp4"
    if fallback.is_file():
        return fallback
    raise SystemExit("找不到输入视频：input.video 未指定，且 input/clean-cut.mp4 也不存在")


def resolve_duration(cfg: dict, project_dir: str | Path) -> float:
    """Finished length follows the actual cut; config.duration is a cached result."""
    try:
        source = resolve_video(cfg, project_dir)
    except SystemExit:
        # Planning/voice preparation can precede the first rough-cut render.
        if cfg.get("duration"):
            return float(cfg["duration"])
        raise
    return float(probe_media(source)["duration"])


# ---------------------------------------------------------------- 信息卡版式
# 这几个比例是从参考片逐帧量出来的（卡高 1354px 时，三行中心落在 +271/+542/+813），
# make_assets 与 build_frames 必须共用同一份，否则图标和文字会各画各的、错位。
CARD_ROW_PITCH = 0.20      # 行距 = 卡高 × 0.20
CARD_TITLE_OFF = 0.083     # 标题中心 = 卡顶 + 卡高 × 0.083
# glass 卡面把标题改成了左对齐 + 金色短条，行也重新配平过：flat 的 0.20 行距是照
# 参考片量的，三行只占了卡高的 60%，下面空出一大块，单看像没画完。glass 把标题和
# 三行铺开，上下留白才对称。
CARD_ROW_PITCH_GLASS = 0.25
CARD_TITLE_OFF_GLASS = 0.10
CARD_NUM_X = 0.154         # 序号右对齐位置（相对卡宽）
CARD_TEXT_X = 0.181        # 正文左边界（相对卡宽）
CARD_ICON_X = 0.857        # 图标中心（相对卡宽）
CARD_INNER_X = 0.093       # 卡内容左边界（相对卡宽），和 CARD_WIPE_X[0] 同一条线
CARD_WIPE_X = (0.093, 0.917)   # 条目擦出的横向范围（相对卡宽）


def card_layout(cfg: dict) -> dict:
    """卡内所有元素的归一化坐标（相对整幅画布），供素材与合成共用。"""
    x0, y0, x1, y1 = cfg["card"]["box"]
    cw, ch = x1 - x0, y1 - y0
    n = len(cfg["card"]["rows"])
    # glass 卡面把标题改成了左对齐（前面挂一条金色短条），放大动画就得绕标题自己
    # 的左上角转，不能再用画布中心——否则标题会在缩放里横向漂移。
    glass = (cfg["card"].get("theme") or {}).get("skin") == "glass"
    pitch = CARD_ROW_PITCH_GLASS if glass else CARD_ROW_PITCH
    title_off = CARD_TITLE_OFF_GLASS if glass else CARD_TITLE_OFF
    return {
        "title_y": y0 + ch * title_off,
        "title_x": x0 + cw * CARD_INNER_X,
        "title_cx": (x0 + cw * CARD_INNER_X + 3) if glass else (x0 + x1) / 2,
        "row_y": [y0 + ch * pitch * (i + 1) for i in range(n)],
        "pitch": pitch,
        "num_x": x0 + cw * CARD_NUM_X,
        "text_x": x0 + cw * CARD_TEXT_X,
        "icon_x": x0 + cw * CARD_ICON_X,
        "wipe_x": (x0 + cw * CARD_WIPE_X[0], x0 + cw * CARD_WIPE_X[1]),
    }
