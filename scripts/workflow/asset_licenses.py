"""素材授权目录：把「许可文本」变成程序能判断的三态，而不是一句备注。

这个模块是素材库的唯一许可正本。它做三件事：

1. `LICENSES` 定义常见许可的边界（可商用 / 是否要署名 / 能否再分发 / 是否需人工核验）；
2. `normalize_license()` 把各平台、各字体页面上五花八门的写法收敛到稳定 key；
3. `check()` 把「素材 + 用途 + 是否已导出署名」判成 `pass / unchecked / fail`。

三态和 `verify.py` 的规矩一致：判不了就写 `unchecked` 并说明原因，绝不把
「没查」说成「通过」；非商用许可在商业项目里是 `fail`，不是 `unchecked`。

字体许可是个特例：OFL 允许把字体嵌进成片，成片不需要署名；但**再分发字体文件**
必须附 OFL 文本和版权声明。所以这里把「成片署名」(`attribution`) 与
「再分发通知」(`notice_required`) 分开记录。字体二进制不进仓库，记录放
`fonts/licenses/*.json`，由 `font_license_for()` 读取。
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

# ------------------------------------------------------------------ 许可目录

LICENSES: dict[str, dict] = {
    "CC0-1.0": {
        "name": "CC0 1.0（公共领域贡献）",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "commercial": True, "attribution": "none", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用、免署名；不得用于侵犯他人肖像/商标/名誉的用途。",
    },
    "CC-BY-4.0": {
        "name": "CC BY 4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "commercial": True, "attribution": "required", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用，必须署名并给出许可链接；改编需注明。",
    },
    "CC-BY-SA-4.0": {
        "name": "CC BY-SA 4.0",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "commercial": True, "attribution": "required", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": True, "no_derivatives": False,
        "notes": "可商用，必须署名；改编作品需以相同许可共享。",
    },
    "CC-BY-ND-4.0": {
        "name": "CC BY-ND 4.0",
        "url": "https://creativecommons.org/licenses/by-nd/4.0/",
        "commercial": True, "attribution": "required", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": True,
        "notes": "可商用，必须署名；不得发布改编作品（剪辑/变速/合成前先核对）。",
    },
    "CC-BY-NC-4.0": {
        "name": "CC BY-NC 4.0",
        "url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "commercial": False, "attribution": "required", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "禁止商业使用；商业项目里直接判红。",
    },
    "CC-BY-NC-SA-4.0": {
        "name": "CC BY-NC-SA 4.0",
        "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "commercial": False, "attribution": "required", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": True, "no_derivatives": False,
        "notes": "禁止商业使用；必须署名；改编需同许可共享。",
    },
    "CC-BY-NC-ND-4.0": {
        "name": "CC BY-NC-ND 4.0",
        "url": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
        "commercial": False, "attribution": "required", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": True,
        "notes": "禁止商业使用、禁止改编；商业交付不可用。",
    },
    "OFL-1.1": {
        "name": "SIL Open Font License 1.1",
        "url": "https://openfontlicense.org/",
        "commercial": True, "attribution": "none", "redistribute": True,
        "review_required": False, "notice_required": True,
        "share_alike": False, "no_derivatives": False,
        "notes": "成片使用无需署名；再分发字体文件需附 OFL 文本与版权声明；"
                 "保留字体名不得用于修改版。",
    },
    "Apache-2.0": {
        "name": "Apache License 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0",
        "commercial": True, "attribution": "none", "redistribute": True,
        "review_required": False, "notice_required": True,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用；再分发代码/文件时保留许可与 NOTICE。",
    },
    "MIT": {
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
        "commercial": True, "attribution": "optional", "redistribute": True,
        "review_required": False, "notice_required": True,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用；再分发时保留版权与许可声明。",
    },
    "BSD-3-Clause": {
        "name": "BSD 3-Clause",
        "url": "https://opensource.org/licenses/BSD-3-Clause",
        "commercial": True, "attribution": "optional", "redistribute": True,
        "review_required": False, "notice_required": True,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用；再分发时保留版权与许可声明。",
    },
    "Pixabay-Content-License": {
        "name": "Pixabay Content License",
        "url": "https://pixabay.com/service/license-summary/",
        "commercial": True, "attribution": "none", "redistribute": False,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用、免署名；不可原样转售或再分发素材本身；"
                 "可识别人物/品牌/地点需自行确认肖像与商标风险。",
    },
    "Mixkit-Free-License": {
        "name": "Mixkit Free License",
        "url": "https://mixkit.co/license/",
        "commercial": True, "attribution": "none", "redistribute": False,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用、免署名；不可单独转售/再分发素材本身；"
                 "不得把素材当成自己的素材库发布。",
    },
    "Pexels-License": {
        "name": "Pexels License",
        "url": "https://www.pexels.com/license/",
        "commercial": True, "attribution": "optional", "redistribute": False,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "可商用、署名非必需（可选）；不可原样转售/再分发；"
                 "不可暗示人物/品牌为产品背书；可识别人物需注意肖像权。",
    },
    "Alibaba-PuHuiTi": {
        "name": "阿里巴巴普惠体（官方免费商用条款）",
        "url": "https://fonts.alibabagroup.com/",
        "commercial": True, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "官方声明免费商用；不可转售字体本身；具体限制以官方条款为准，"
                 "商用交付前人工核对一次。",
    },
    "Alimama-Free": {
        "name": "阿里妈妈字体（官方免费商用条款）",
        "url": "https://fonts.alibabagroup.com/",
        "commercial": True, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "官方声明免费商用；不可转售字体本身；具体限制以官方条款为准。",
    },
    "ZCOOL-Free": {
        "name": "站酷字体（官方免费商用条款）",
        "url": "https://www.zcool.com.cn/special/zcoolfonts/",
        "commercial": True, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "站酷官方免费商用字体；不可转售字体本身；以官方页面为准。",
    },
    "MonuTitl-OFL": {
        "name": "典迹题幕 Monu Titl（OFL 1.1）",
        "url": "https://github.com/MY1L/Monu/releases/tag/Titl",
        "commercial": True, "attribution": "none", "redistribute": True,
        "review_required": True, "notice_required": True,
        "share_alike": False, "no_derivatives": False,
        "notes": "作者仓库声明多为 OFL 1.1；发布页与字体内许可证描述需再核对一次；"
                 "再分发字体文件需附 OFL 文本。",
    },
    "custom-free": {
        "name": "自定义免费商用（条款未核验）",
        "url": "",
        "commercial": True, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "来源自称免费商用，但条款未入库核验；商用交付前必须人工确认。",
    },
    "Jianying-Cloud": {
        "name": "剪映云端音乐（平台授权）",
        "url": "https://www.jianying.com/",
        "commercial": None, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "授权随剪映/音乐平台条款与账号类型变化；发布前按平台规则核对；"
                 "下载文件只放本机工作区，不随项目分发。",
    },
    "project-owned": {
        "name": "项目自有",
        "url": "",
        "commercial": True, "attribution": "none", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "本项目自绘/自制；如包含第三方元素，需另行核对。",
    },
    "project-generated": {
        "name": "项目生成",
        "url": "",
        "commercial": True, "attribution": "none", "redistribute": True,
        "review_required": False, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "脚本/模型在本项目内生成；输入素材的权利仍以输入为准。",
    },
    "project-input": {
        "name": "用户提供素材",
        "url": "",
        "commercial": None, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "用户提供的原始素材；商用权利、肖像权与场地/品牌授权由用户确认，"
                 "工具不能代替判断。",
    },
    "system-font": {
        "name": "系统字体",
        "url": "",
        "commercial": None, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "可用于本机渲染；不可随包再分发；成片商用需核对系统字体条款。",
    },
    "unknown": {
        "name": "授权未知",
        "url": "",
        "commercial": None, "attribution": "none", "redistribute": False,
        "review_required": True, "notice_required": False,
        "share_alike": False, "no_derivatives": False,
        "notes": "没有可核验的授权记录；商用交付前必须补齐，不能默认可用。",
    },
}

# 平台/字体页面上的常见写法 → 稳定 key。顺序重要：NC/ND/SA 先于普通 BY。
_ALIASES: tuple[tuple[str, str], ...] = (
    ("cc0", "CC0-1.0"), ("cc-0", "CC0-1.0"), ("cc zero", "CC0-1.0"),
    ("public domain", "CC0-1.0"), ("公有领域", "CC0-1.0"), ("公共领域", "CC0-1.0"),
    ("cc by-nc-nd", "CC-BY-NC-ND-4.0"), ("by-nc-nd", "CC-BY-NC-ND-4.0"),
    ("cc by-nc-sa", "CC-BY-NC-SA-4.0"), ("by-nc-sa", "CC-BY-NC-SA-4.0"),
    ("cc by-nc", "CC-BY-NC-4.0"), ("by-nc", "CC-BY-NC-4.0"),
    ("cc by-sa", "CC-BY-SA-4.0"), ("by-sa", "CC-BY-SA-4.0"),
    ("cc by-nd", "CC-BY-ND-4.0"), ("by-nd", "CC-BY-ND-4.0"),
    ("cc by", "CC-BY-4.0"), ("cc-by", "CC-BY-4.0"),
    ("非商业", "CC-BY-NC-4.0"), ("非商業", "CC-BY-NC-4.0"),
    ("non-commercial", "CC-BY-NC-4.0"), ("noncommercial", "CC-BY-NC-4.0"),
    ("ofl", "OFL-1.1"), ("sil open font", "OFL-1.1"), ("open font license", "OFL-1.1"),
    ("apache", "Apache-2.0"),
    ("bsd-3", "BSD-3-Clause"), ("bsd 3", "BSD-3-Clause"),
    ("mit license", "MIT"),
    ("pixabay", "Pixabay-Content-License"),
    ("mixkit", "Mixkit-Free-License"),
    ("pexels", "Pexels-License"),
    ("剪映", "Jianying-Cloud"), ("jianying", "Jianying-Cloud"),
    ("阿里妈妈", "Alimama-Free"),
    ("阿里巴巴普惠体", "Alibaba-PuHuiTi"), ("puhuiti", "Alibaba-PuHuiTi"),
    ("站酷", "ZCOOL-Free"), ("zcool", "ZCOOL-Free"),
    ("典迹题幕", "MonuTitl-OFL"), ("monu titl", "MonuTitl-OFL"),
    ("system font", "system-font"), ("系统字体", "system-font"),
    ("项目自有", "project-owned"), ("project-owned", "project-owned"),
    ("项目生成", "project-generated"), ("project-generated", "project-generated"),
    ("用户提供", "project-input"), ("project-input", "project-input"),
    ("免费商用", "custom-free"), ("free commercial", "custom-free"),
    ("未知", "unknown"), ("不明", "unknown"), ("unknown", "unknown"),
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_license(value) -> str:
    """把任意许可文本收敛成 `LICENSES` 的 key；认不出来就回 `unknown`。

    已带 key 原样返回；不区分大小写；中文/英文别名都收。这里宁可把
    「看不懂」判成 unknown，也不靠关键字猜一个更宽松的许可。
    """
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    if raw in LICENSES:
        return raw
    low = raw.casefold()
    for key, target in _ALIASES:
        if key in low:
            return target
    # 「CC BY 4.0」「CC-BY-4.0」等带版本号的写法
    m = re.search(r"cc[\s-]*by([\s-]*(?:nc|sa|nd)[\s-]*(?:nc|sa|nd)?)?", low)
    if m:
        tags = re.sub(r"[\s-]+", "-", m.group(1) or "").strip("-")
        if "nc" in tags:
            if "nd" in tags:
                return "CC-BY-NC-ND-4.0"
            if "sa" in tags:
                return "CC-BY-NC-SA-4.0"
            return "CC-BY-NC-4.0"
        if "nd" in tags:
            return "CC-BY-ND-4.0"
        if "sa" in tags:
            return "CC-BY-SA-4.0"
        return "CC-BY-4.0"
    return "unknown"


def load_catalog(root: str | Path | None = None) -> dict[str, dict]:
    """内置许可 + 可选 `licenses.local.json`（项目/素材库自定义许可）。"""
    catalog = {key: dict(value) for key, value in LICENSES.items()}
    if root:
        for path in (Path(root) / "licenses.local.json", Path(root) / "licenses.json"):
            if not path.is_file():
                continue
            try:
                extra = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for key, value in (extra or {}).items():
                if not isinstance(value, dict):
                    continue
                base = dict(catalog.get(key) or catalog["unknown"])
                base.update(value)
                base["id"] = key
                catalog[key] = base
    for key, value in catalog.items():
        value.setdefault("id", key)
    return catalog


_CATALOG: dict[str, dict] | None = None


def catalog() -> dict[str, dict]:
    """默认内置目录（进程级只读）。自定义许可请显式传 `catalog=load_catalog(...)`。"""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_catalog(None)
    return _CATALOG


def license_info(key, catalog_override: dict | None = None) -> dict:
    cat = catalog_override or catalog()
    norm = normalize_license(key)
    info = dict(cat.get(norm) or cat["unknown"])
    info["id"] = norm
    info["requested"] = str(key or "")
    return info


def license_tier(text) -> str:
    """字体筛选用的粗分层：permissive / restricted / system / unknown。

    与 `font_picker.license_tier` 保持同一判据（这里唯一正本，那边只做再导出）。
    """
    info = license_info(text)
    key = info["id"]
    if key == "system-font":
        return "system"
    if info.get("commercial") is False:
        return "restricted"
    if info.get("commercial") is True:
        return "permissive"
    return "unknown"


def attribution_required(info: dict) -> bool:
    return str(info.get("attribution") or "none") == "required"


def attribution_line(title: str, creator: str, info: dict, source_url: str = "") -> str:
    """一行可粘贴到片尾/说明区的署名。缺作者时明确写 Unknown，而不是留空。"""
    who = str(creator or "").strip() or "Unknown creator"
    lic = str(info.get("name") or info.get("id") or "Unknown license")
    url = str(info.get("url") or "").strip()
    src = str(source_url or "").strip()
    bits = [f"「{title or 'Untitled'}」— {who}（{lic}"]
    if url:
        bits.append(f"，{url}")
    bits.append("）")
    if src and src != url:
        bits.append(f"；来源：{src}")
    return "".join(bits)


def _age_days(value, now: date | None = None) -> int | None:
    raw = str(value or "").strip()
    if not _DATE_RE.match(raw):
        return None
    try:
        then = date.fromisoformat(raw)
    except ValueError:
        return None
    return ((now or date.today()) - then).days


def check(license_key, *, commercial: bool = True,
          attribution_exported: bool = False,
          snapshot: dict | None = None,
          catalog_override: dict | None = None,
          strict: bool = False,
          stale_days: int = 365,
          checked_at: str | None = None,
          now: date | None = None) -> dict:
    """判一个素材的授权是否够用。返回 `{status, reasons, info}`。

    - `fail`：明确不可用（NC 用于商业项目 / 严格模式下的 unknown）；
    - `unchecked`：判不了或需人工确认（unknown、平台条款需复核、要署名但没导出、
      授权核验过期）；
    - `pass`：当前用途下没有已知障碍。

    `snapshot` 是入库时记录的许可快照。如果快照写的「可商用」与当前目录不一致，
    说明条款可能变过，降级为 `unchecked`，提示重新核对。
    """
    info = license_info(license_key, catalog_override)
    key = info["id"]
    reasons: list[str] = []
    status = "pass"

    def lower(new: str, why: str) -> None:
        nonlocal status
        reasons.append(why)
        rank = {"pass": 0, "unchecked": 1, "fail": 2}
        if rank[new] > rank[status]:
            status = new

    if key == "unknown":
        if strict:
            lower("fail", "授权未知；严格模式下不能进入交付")
        else:
            lower("unchecked", "授权未知；商用交付前必须补齐许可与来源")

    if info.get("commercial") is False and commercial:
        lower("fail", f"许可 {info['name']} 不允许商业使用")
    if info.get("commercial") is None:
        lower("unchecked", f"许可 {info['name']} 的商用范围不明确，需人工确认")

    if info.get("review_required"):
        lower("unchecked", f"许可 {info['name']} 需人工核验官方条款")

    if snapshot:
        snap_commercial = snapshot.get("commercial") if isinstance(snapshot, dict) else None
        if snap_commercial is not None and info.get("commercial") is not None \
                and bool(snap_commercial) != bool(info.get("commercial")):
            lower("unchecked", "入库时的许可快照与当前许可目录不一致；条款可能已变，需重新核对")
        age = _age_days(snapshot.get("checked_at"), now) if isinstance(snapshot, dict) else None
        if age is not None and age > stale_days:
            lower("unchecked", f"授权核验已 {age} 天（> {stale_days} 天），需重新核对")

    if attribution_required(info) and not attribution_exported:
        lower("unchecked", f"许可 {info['name']} 要求署名；导出前必须写入 CREDITS")

    if checked_at:
        age = _age_days(checked_at, now)
        if age is None:
            lower("unchecked", "授权核验日期缺失或格式不对（应为 YYYY-MM-DD）")
        elif age > stale_days:
            lower("unchecked", f"授权核验已 {age} 天（> {stale_days} 天），需重新核对")

    if not reasons:
        reasons.append(f"许可 {info['name']}：当前用途下未发现障碍")
    return {"status": status, "reasons": reasons, "info": info}


# ------------------------------------------------------------------ 字体许可

_FONT_ALIAS_SEPARATORS = re.compile(r"[\s\-_·．.,，、（）()\[\]]+")


def _name_key(value) -> str:
    return _FONT_ALIAS_SEPARATORS.sub("", str(value or "").casefold())


def _font_record_dirs(project: str | Path | None = None) -> list[Path]:
    dirs = []
    if project:
        dirs.append(Path(project) / "fonts" / "licenses")
    dirs.append(repo_root() / "fonts" / "licenses")
    env = os.environ.get("KOUBO_FONT_LICENSES")
    if env:
        dirs.extend(Path(x).expanduser() for x in env.split(os.pathsep) if x.strip())
    seen, out = set(), []
    for d in dirs:
        key = str(d.resolve())
        if key in seen or not d.is_dir():
            continue
        seen.add(key)
        out.append(d)
    return out


_FONT_RECORDS: dict[str, list[dict]] = {}


def load_font_records(project: str | Path | None = None) -> list[dict]:
    """读 `fonts/licenses/*.json`（工程优先，其次安装目录，再 `KOUBO_FONT_LICENSES`）。"""
    out: list[dict] = []
    for directory in _font_record_dirs(project):
        key = str(directory)
        records = _FONT_RECORDS.get(key)
        if records is None:
            records = []
            for path in sorted(directory.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict):
                    data.setdefault("record_file", str(path))
                    records.append(data)
            _FONT_RECORDS[key] = records
        out.extend(records)
    return out


def match_font_record(family: str, path: str | Path | None = None,
                      project: str | Path | None = None) -> dict | None:
    fam = _name_key(family)
    filename = Path(path).name.casefold() if path else ""
    for record in load_font_records(project):
        aliases = [str(x) for x in (record.get("family_aliases") or [])]
        for alias in aliases:
            key = _name_key(alias)
            if key and (key in fam or fam in key):
                return record
        for pattern in record.get("file_globs") or []:
            if filename and fnmatch.fnmatch(filename, str(pattern).casefold()):
                return record
    return None


def font_license_for(family: str, path: str | Path | None = None,
                     project: str | Path | None = None) -> dict:
    """字体 → 许可记录。先查 `fonts/licenses/`，再退回按名字/目录的保守推断。

    退回推断只是「已知开源字体家族」的兜底，不是法律判断；返回里的
    `matched` 会写 `record` 或 `heuristic`，UI 应把后者当低置信。
    """
    record = match_font_record(family, path, project)
    if record:
        info = license_info(record.get("license"))
        for field in ("commercial", "attribution", "redistribute", "review_required",
                      "notice_required", "url", "name", "notes"):
            if field in record:
                info[field] = record[field]
        info["id"] = normalize_license(record.get("license"))
        info["matched"] = "record"
        info["record"] = record
        return info

    name = f"{family} {Path(path).name if path else ''}".casefold()
    if any(k in name for k in ("noto", "source han", "思源", "smiley", "得意黑",
                               "douyin", "抖音美好体")):
        key = "OFL-1.1"
    elif any(k in name for k in ("阿里巴巴普惠体", "puhuiti")):
        key = "Alibaba-PuHuiTi"
    elif any(k in name for k in ("阿里妈妈", "alimama")):
        key = "Alimama-Free"
    elif any(k in name for k in ("站酷", "zcool")):
        key = "ZCOOL-Free"
    elif any(k in name for k in ("典迹题幕", "monu titl", "monutitl")):
        key = "MonuTitl-OFL"
    elif path and any(str(Path(path).resolve()).startswith(str(d))
                      for d in _SYSTEM_FONT_DIRS):
        key = "system-font"
    elif "system" in name or "系统字体" in name:
        key = "system-font"
    else:
        key = "unknown"
    info = license_info(key)
    info["matched"] = "heuristic"
    return info


_SYSTEM_FONT_DIRS = (
    "/System/Library/Fonts",
    "/Library/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
)


def font_attribution_line(family: str, info: dict, path: str | Path | None = None) -> str:
    record = info.get("record") or {}
    creator = record.get("copyright") or record.get("creator") or ""
    source = info.get("url") or ""
    return attribution_line(family, creator, info, source)
