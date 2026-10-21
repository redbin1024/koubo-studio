"""固定口播风格：稳定 ID、版本、配方快照与项目锁。

灵感来自 talking-head-motion 的 style-lock：风格不是一堆会漂移的 config 值，
而是带 ID/版本/哈希/就绪范围的资产。这里不复制其 30 款内容，只实现锁定机制。

项目锁在 work/style-lock.json；风格库在 references/styles/catalog.json。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "references" / "styles" / "catalog.json"


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _snapshot_digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _pick(source: dict, keys: list[str]) -> dict:
    return {k: source[k] for k in keys if k in source}


def projection(cfg: dict) -> dict:
    """只取风格参数，排除文案/时间/素材等内容字段。"""
    cap = cfg.get("captions") or {}
    cap_style = _pick(cap, ["font", "size", "outline", "shadow", "spacing",
                            "margin_lr", "margin_v", "max_width", "fade_in_ms",
                            "fade_out_ms", "anim_ms", "layout", "burn",
                            "big", "hook", "palette", "jianying_font"])
    card = cfg.get("card") or {}
    card_style = _pick(card, ["fill", "edge", "radius", "edge_width", "wipe",
                              "box_dur", "row_enter", "box", "stack", "stack_offset"])
    theme = dict(card.get("theme") or {})
    theme.pop("footnote", None)
    if theme:
        card_style["theme"] = theme
    inserts = cfg.get("inserts") or {}
    ins_style = _pick(inserts, ["layout", "box", "radius"])
    if inserts.get("theme"):
        ins_style["theme"] = inserts["theme"]
    fx = cfg.get("jianying_fx") or {}
    fx_style = {
        "effects": [{"name": x.get("name"), "intensity": x.get("intensity")}
                    for x in (fx.get("effects") or []) if x.get("name")],
        "filters": [{"name": x.get("name"), "intensity": x.get("intensity")}
                    for x in (fx.get("filters") or []) if x.get("name")],
        "transitions": [{"name": x.get("name"), "dur": x.get("dur")}
                        for x in (fx.get("transitions") or []) if x.get("name")],
    }
    return {
        "canvas": _pick(cfg.get("canvas") or {}, ["width", "height", "fps"]),
        "captions": cap_style,
        "card": card_style,
        "inserts": ins_style,
        "gold": _pick(cfg.get("gold") or {}, ["size"]),
        "grade": _pick(cfg.get("grade") or {}, ["eq", "blur", "darken"]),
        "jianying_fx": fx_style,
        "overlay_fx": _pick(cfg.get("overlay_fx") or {}, ["enabled", "items"]),
    }


def _diff(expected: dict, actual: dict, prefix: str = "") -> list[str]:
    issues = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in expected:
                issues.append(f"{path} 多出未锁定参数")
            elif key not in actual:
                issues.append(f"{path} 缺失")
            else:
                issues += _diff(expected[key], actual[key], path)
    elif expected != actual:
        issues.append(f"{prefix}: 锁定 {expected!r} / 当前 {actual!r}")
    return issues


def library(path: Path = CATALOG) -> dict:
    data = _read(path)
    seen = set()
    for row in data.get("styles") or []:
        sid = str(row.get("id") or "")
        if not re.fullmatch(r"KB-TH-\d{2}", sid) or sid in seen:
            raise ValueError(f"非法或重复的风格 ID：{sid!r}")
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(row.get("version") or "")):
            raise ValueError(f"{sid} 缺语义版本")
        seen.add(sid)
        base = path.parent.resolve()
        recipe_path = (base / row["recipe"]).resolve()
        if not recipe_path.is_relative_to(base):
            raise ValueError(f"{sid} 配方路径越界")
        if not recipe_path.is_file() or _digest(recipe_path) != row.get("recipe_sha256"):
            raise ValueError(f"{sid} 配方文件缺失或哈希不符")
        recipe = _read(recipe_path)
        for key in ("id", "name", "version"):
            if recipe.get(key) != row.get(key):
                raise ValueError(f"{sid} 目录与配方 {key} 不一致")
    return data


def resolve(query: str, path: Path = CATALOG) -> dict:
    data = library(path)
    needle = query.strip().casefold()
    if re.fullmatch(r"\d+", needle):
        raise ValueError("请用完整稳定 ID（如 KB-TH-01）或完整风格名；裸数字有歧义")
    hits = [r for r in data["styles"]
            if needle in {str(v).strip().casefold() for v in
                          [r.get("id"), r.get("name"), *(r.get("aliases") or [])]}]
    if len(hits) != 1:
        raise ValueError("风格不存在或有歧义；请提供目录里的完整 ID/名称")
    return hits[0]


def bind(project: Path, query: str, choice_source: str, path: Path = CATALOG) -> dict:
    if not choice_source.strip():
        raise ValueError("必须记录真实的风格选择来源")
    row = resolve(query, path)
    recipe_path = (Path(path).parent / row["recipe"]).resolve()
    recipe = _read(recipe_path)
    lock_path = Path(project) / "work" / "style-lock.json"
    old = _read(lock_path) if lock_path.is_file() else None
    if (old and old.get("id") == row["id"] and old.get("version") == row["version"]
            and old.get("recipe_sha256") != row["recipe_sha256"]):
        raise ValueError("同版本配方被改动了；请发布新版本或保留原锁")
    lock = {
        "version": 1,
        "id": row["id"], "name": row["name"], "version": row["version"],
        "recipe_sha256": row["recipe_sha256"],
        "recipe": recipe,
        "recipe_snapshot_sha256": _snapshot_digest(recipe),
        "choice_source": choice_source.strip(),
        "readiness": row.get("readiness") or {},
        "bound_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return lock


def validate(project: Path, cfg: dict, path: Path = CATALOG) -> dict:
    lock_path = Path(project) / "work" / "style-lock.json"
    if not lock_path.is_file():
        return {"ok": None, "issues": ["没有 work/style-lock.json，本项没查"], "style": None}
    lock = _read(lock_path)
    issues = []
    try:
        row = resolve(lock.get("id", ""), path)
    except ValueError as exc:
        row = None
        issues.append(str(exc))
    if row and row["recipe_sha256"] != lock.get("recipe_sha256"):
        issues.append("风格库同版本配方已变化；请发布新版本并重新绑定")
    recipe = lock.get("recipe") or {}
    if _snapshot_digest(recipe) != lock.get("recipe_snapshot_sha256"):
        issues.append("锁内配方快照被改动")
    for key in ("id", "name", "version"):
        if recipe.get(key) != lock.get(key):
            issues.append(f"锁内配方 {key} 不一致")
    if recipe.get("id") != lock.get("id") or recipe.get("version") != lock.get("version"):
        issues.append("锁内配方身份不一致")
    expected = recipe.get("style") or {}
    issues += _diff(expected, projection(cfg))
    return {"ok": not issues, "issues": issues, "style": lock}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="口播固定风格：列出 / 解析 / 绑定 / 校验")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    r = sub.add_parser("resolve"); r.add_argument("style")
    b = sub.add_parser("bind"); b.add_argument("project")
    b.add_argument("--style", required=True); b.add_argument("--choice-source", required=True)
    c = sub.add_parser("check"); c.add_argument("project")
    a = ap.parse_args()
    try:
        if a.command == "list":
            data = library()
            for row in data["styles"]:
                print(f"{row['id']}  v{row['version']}  {row['name']}  "
                      f"{row['readiness'].get('status', '')}")
        elif a.command == "resolve":
            print(json.dumps(resolve(a.style), ensure_ascii=False, indent=2))
        elif a.command == "bind":
            print(json.dumps(bind(Path(a.project).resolve(), a.style, a.choice_source),
                             ensure_ascii=False, indent=2))
        else:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from _common import load_config, project_paths
            project = Path(a.project).resolve()
            cfg = load_config(project_paths(project)["config"])
            print(json.dumps(validate(project, cfg), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
