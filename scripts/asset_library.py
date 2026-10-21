#!/usr/bin/env python3
"""素材库命令：登记 / 检索 / 核验 / 导出授权台账 / 召回建议 / 远程源。

```bash
koubo assets init
koubo assets add ~/Downloads/city-night.mp4 --kind broll \
  --license CC0-1.0 --source-url https://example.com/x --tags city,night
koubo assets search 城市夜景 --kind broll
koubo assets verify --strict
koubo assets audit PROJECT
koubo assets export
koubo assets suggest PROJECT --cue 7
koubo assets remote search pexels --media video --query "city night"
```

所有命令都输出可读文本；加 `--json` 给脚本/Agent 用。退出码：`0` 表示没有
`fail`（可能有 `unchecked`），`1` 表示有 `fail`。`unchecked` 不等于通过。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from workflow import asset_library as lib  # noqa: E402
from workflow import asset_licenses as lic  # noqa: E402


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _license_table() -> str:
    rows = []
    for key, info in sorted(lic.catalog().items()):
        commercial = {True: "可商用", False: "不可商用", None: "不明"}.get(
            info.get("commercial"), "不明")
        rows.append(f"{key:<28} {commercial:<8} {info.get('attribution') or '-':<9} "
                    f"{info.get('name') or ''}")
    return "\n".join(rows)


def _search_table(hits: list[dict]) -> str:
    lines = []
    for hit in hits:
        entry = hit.get("entry") or {}
        dur = entry.get("duration")
        dur_text = f"{float(dur):.2f}s" if isinstance(dur, (int, float)) else "—"
        score = f"{hit.get('score', 0):.1f}"
        lines.append(f"{entry.get('id', ''):<34} {entry.get('kind', ''):<13} "
                     f"{entry.get('license', ''):<26} {dur_text:<8} {score:<6} "
                     f"{entry.get('title', '')}")
    if not lines:
        return "（没有命中；换关键词，或先 `koubo assets scan`）"
    return "\n".join(lines)


def _do_init(a) -> int:
    got = lib.init_library(a.root, seed=not a.no_seed)
    if a.json:
        _print_json(got)
    else:
        print(f"素材库：{got['root']}")
        print(f"索引：{got['registry']}")
        seeded = got.get("seeded") or {}
        print(f"内置素材：新增 {len(seeded.get('added') or [])}，"
              f"更新 {len(seeded.get('updated') or [])}，跳过 {len(seeded.get('skipped') or [])}")
        for warning in seeded.get("warnings") or []:
            print(f"  ⚠ {warning}")
    return 0


def _do_scan(a) -> int:
    got = lib.scan_library(a.root, refresh=a.refresh, dry_run=a.dry_run,
                           fast=a.fast, kinds=a.kind)
    if a.json:
        _print_json(got)
    else:
        print(f"素材库：{got['root']}（共 {got['total']} 条）")
        print(f"新增 {len(got['added'])} / 更新 {len(got['updated'])} / "
              f"跳过 {got['skipped']}" + ("（dry-run，未写盘）" if got["dry_run"] else ""))
        for ident in got["added"][:20]:
            print(f"  + {ident}")
        for ident in got["updated"][:20]:
            print(f"  ~ {ident}")
        for warning in got["warnings"]:
            print(f"  ⚠ {warning}")
        if got["added"]:
            print("\n新文件授权是 unknown；用 `koubo assets set-license ID --license ...` 补齐。")
    return 0


def _do_add(a) -> int:
    sync = None
    if a.sync_at is not None:
        sync = {"at": float(a.sync_at), "meets": a.sync_meets or "hit"}
    meta = {
        "title": a.title,
        "provider": a.provider,
        "provider_id": a.provider_id,
        "creator": a.creator,
        "creator_url": a.creator_url,
        "source_url": a.source_url,
        "download_url": a.download_url,
        "tags": a.tag, "mood": a.mood, "scene": a.scene,
        "use_for": a.use_for, "avoid_for": a.avoid_for,
        "bpm": a.bpm, "energy": a.energy, "sync": sync,
        "notes": a.notes,
    }
    meta = {k: v for k, v in meta.items() if v not in (None, "", [], {})}
    if not a.id and a.title:
        a.id = f"{lib.normalize_kind(a.kind)}/{lib.slugify(a.title)}"
    entry = lib.ingest_file(
        a.source, kind=a.kind, license_key=a.license,
        library_root=a.root, project=a.project,
        scope="project" if a.project else "library",
        copy=not a.no_copy, ident=a.id,
        dest_rel=a.dest, allow_unknown=a.allow_unknown,
        downloaded_at=a.downloaded_at, **meta)
    if a.json:
        _print_json({"entry": entry, "path": lib._abs_for(entry, library_root=a.root,
                                                          project=a.project)})
    else:
        print(f"已登记 {entry['id']} → {entry['path']}")
        print(f"  许可：{entry['license']} / 提供方：{entry['provider']}")
        if entry.get("probe_error"):
            print(f"  ⚠ 探测失败（不影响入库）：{entry['probe_error']}")
    return 0


def _do_search(a) -> int:
    entries = lib.load_registry(a.root)
    hits = lib.search(entries, a.query, kinds=a.kind, tags=a.tag,
                      any_tags=a.any_tag, mood=a.mood, scene=a.scene,
                      providers=a.provider, license_key=a.license,
                      commercial_only=a.commercial,
                      min_duration=a.min_duration, max_duration=a.max_duration,
                      has_sync=a.has_sync, limit=a.limit, sort=a.sort,
                      library_root=a.root)
    if a.json:
        _print_json(hits)
    else:
        print(_search_table(hits))
        print(f"\n共 {len(hits)} 条；ID 可直接写进 config：`asset:<id>`。")
    return 0


def _find(a, ident: str) -> dict:
    entries = lib.load_registry(a.root)
    return lib.resolve_id(entries, ident)


def _do_show(a) -> int:
    entry = _find(a, a.id)
    path = lib._abs_for(entry, library_root=a.root)
    data = {**entry, "resolved_path": path,
            "exists": bool(path and Path(path).is_file())}
    if a.json:
        _print_json(data)
    else:
        for key in ("id", "kind", "title", "provider", "license", "path"):
            print(f"{key:<14}{entry.get(key, '')}")
        print(f"{'resolved':<14}{path or '（无法解析）'}")
        print(f"{'exists':<14}{data['exists']}")
        if entry.get("tags"):
            print(f"{'tags':<14}{', '.join(entry['tags'])}")
        if entry.get("notes"):
            print(f"{'notes':<14}{entry['notes']}")
    return 0


def _do_path(a) -> int:
    entry = _find(a, a.id)
    path = lib._abs_for(entry, library_root=a.root)
    if not path or not Path(path).is_file():
        print(f"{entry['id']} 的文件不存在：{path}", file=sys.stderr)
        return 1
    print(path)
    return 0


def _do_set_license(a) -> int:
    entries = lib.load_registry(a.root)
    entry = lib.apply_license(lib.resolve_id(entries, a.id), a.license,
                              checked_at=a.checked_at, notes=a.notes or None)
    info = lic.license_info(entry["license"])
    entries = lib.upsert_entry(entries, entry)
    lib.save_registry(entries, a.root)
    path = lib._abs_for(entry, library_root=a.root)
    if path and Path(path).is_file():
        try:
            lib.write_sidecar(path, entry)
        except OSError as exc:
            print(f"⚠ sidecar 写不进去：{exc}", file=sys.stderr)
    if a.json:
        _print_json(entry)
    else:
        print(f"{entry['id']} 许可 → {entry['license']}（{info['name']}），"
              f"核对日期 {entry['license_checked_at']}")
    return 0


def _do_verify(a) -> int:
    entries = lib.load_registry(a.root)
    got = lib.verify_entries(entries, library_root=a.root,
                             commercial=not a.non_commercial,
                             strict=a.strict, check_hash=not a.no_hash)
    if a.json:
        _print_json(got)
    else:
        c = got["counts"]
        print(f"素材库：{got['root']}（{got['entries']} 条）")
        print(f"pass {c['pass']} / unchecked {c['unchecked']} / fail {c['fail']}")
        for issue in got["issues"]:
            if issue["status"] == "pass":
                continue
            mark = "✗" if issue["status"] == "fail" else "–"
            print(f"  {mark} {issue['id']}  {issue.get('title') or ''}")
            for reason in issue["reasons"]:
                print(f"      {reason}")
        if c["unchecked"]:
            print("\n⚠ unchecked 不等于通过；补齐许可/来源或人工签收后再交付。")
    return 1 if not got["ok"] else 0


def _do_export(a) -> int:
    got = lib.export_library(a.root, out=a.out,
                             commercial=not a.non_commercial, strict=a.strict)
    if a.json:
        _print_json(got)
    else:
        c = got["counts"]
        print(f"导出 {got['entries']} 条：pass {c['pass']} / "
              f"unchecked {c['unchecked']} / fail {c['fail']}")
        print(f"  {got['csv']}")
        print(f"  {got['credits']}")
    return 1 if got["counts"]["fail"] else 0


def _do_audit(a) -> int:
    got = lib.audit_project(a.project, library_root=a.root,
                            commercial=None if not a.non_commercial else False,
                            strict=a.strict)
    if a.json:
        _print_json(got)
    else:
        s = got["summary"]
        print(f"工程：{got['project']}")
        print(f"总体：{got['overall']}（pass {s['pass']} / unchecked {s['unchecked']} / "
              f"fail {s['fail']} / 共 {s['used']} 条）")
        for item in got["items"]:
            if item["status"] == "pass":
                continue
            mark = "✗" if item["status"] == "fail" else "–"
            print(f"  {mark} {item['kind']:<6} {item['title']}  [{item['usage']}]")
            for reason in item["reasons"]:
                print(f"      {reason}")
        if got.get("export"):
            print(f"  {got['export'].get('csv')}")
            print(f"  {got['export'].get('credits')}")
        print("\nmanifest：work/asset-manifest.json")
    return 1 if got["summary"]["fail"] else 0


def _do_suggest(a) -> int:
    remote = [x.strip() for x in (a.remote or "").split(",") if x.strip()]
    got = lib.suggest(a.project, a.cue, kind=a.kind, limit=a.limit,
                      library_root=a.root, remote=remote or None)
    if a.json:
        _print_json(got)
        return 0
    print(f"cue #{a.cue}  {got['cue']['start']}–{got['cue']['end']}s")
    print(f"字幕：{got['cue']['text']}")
    print(f"召回词：{', '.join(got['tokens'][:16])}")
    print()
    if not got["suggestions"]:
        print("（素材库里没有匹配项；先入库或换 --kind）")
    for i, hit in enumerate(got["suggestions"], 1):
        entry = hit["entry"]
        print(f"{i:02d}. {entry['id']}  {entry.get('title')}  [{hit['status']}]  "
              f"score {hit['score']}")
        print(f"    {', '.join(hit['reasons'][:6])}")
        if hit.get("path"):
            print(f"    {hit['path']}")
    for item in got.get("remote") or []:
        if item.get("error"):
            print(f"\n远程：{item.get('provider')}/{item.get('media')} {item['error']}")
        else:
            print(f"\n远程 {item.get('provider')} {item.get('media')} "
                  f"{item.get('provider_id')}  {item.get('page_url')}")
    print("\n建议不自动改 config；确认后写 broll.items（source 可用 `asset:<id>`）。")
    return 0


def _do_remote_search(a) -> int:
    from workflow import asset_remote
    items = asset_remote.search(a.provider, a.media, a.query, limit=a.limit,
                                orientation=a.orientation,
                                min_duration=a.min_duration,
                                max_duration=a.max_duration,
                                quality=a.quality)
    if a.json:
        _print_json(items)
    else:
        for item in items:
            print(f"{item['provider_id']:<14} {item.get('duration') or '—':<8} "
                  f"{item.get('width')}x{item.get('height')}  {item.get('creator')}")
            print(f"  {item.get('page_url')}")
    return 0


def _do_remote_add(a) -> int:
    from workflow import asset_remote
    item = asset_remote.find(a.provider, a.media, a.id, query=a.query,
                             quality=a.quality)
    entry = asset_remote.add(item, library_root=a.root, project=a.project,
                             tags=a.tag, title=a.title)
    if a.json:
        _print_json({"entry": entry, "path": lib._abs_for(entry, library_root=a.root,
                                                          project=a.project)})
    else:
        print(f"已下载并登记 {entry['id']} → {entry['path']}")
        print(f"  来源：{entry.get('source_url')}")
        print(f"  许可：{entry['license']}")
    return 0


def _do_import_sfx_kit(a) -> int:
    from workflow import asset_remote
    categories = [x.strip() for x in (a.categories or "").split(",") if x.strip()]
    got = asset_remote.import_sfx_kit(a.path, library_root=a.root,
                                      categories=categories or None,
                                      limit=a.limit, copy=not a.link)
    if a.json:
        _print_json(got)
    else:
        print(f"sfx-kit：{got['kit']}")
        print(f"导入 {len(got['added'])} 条；跳过 {len(got['skipped'])}")
        for error in got["errors"][:20]:
            print(f"  ⚠ {error}")
    return 1 if got["errors"] else 0


def _do_licenses(a) -> int:
    if a.json:
        _print_json(lic.catalog())
    else:
        print(_license_table())
        print("\n判据：可商用 + 是否署名 + 是否需人工核验；详情见 docs/asset-library.md。")
    return 0


def _do_stats(a) -> int:
    got = lib.stats(lib.load_registry(a.root))
    if a.json:
        _print_json(got)
    else:
        print(f"共 {got['total']} 条")
        print("按类型：" + "，".join(f"{k} {v}" for k, v in got["by_kind"].items()))
        print("按来源：" + "，".join(f"{k} {v}" for k, v in got["by_provider"].items()))
        print("按许可：" + "，".join(f"{k} {v}" for k, v in got["by_license"].items()))
    return 0


def _do_seed(a) -> int:
    got = lib.seed_bundled(a.root, force=a.force)
    if a.json:
        _print_json(got)
    else:
        print(f"内置素材：新增 {len(got['added'])}，更新 {len(got['updated'])}，"
              f"跳过 {len(got['skipped'])}")
        for warning in got["warnings"]:
            print(f"  ⚠ {warning}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="素材库：登记/检索/核验/授权台账/召回")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--root", default=None, help="素材库根（默认 assets/library）")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("init", help="建目录并登记随包素材")
    common(p); p.set_defaults(func=_do_init)
    p.add_argument("--no-seed", action="store_true")

    p = sub.add_parser("scan", help="扫素材库目录，新文件登记为待核")
    common(p); p.set_defaults(func=_do_scan)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fast", action="store_true", help="跳过 ffprobe/图片探测")
    p.add_argument("--kind", action="append", default=None)

    p = sub.add_parser("add", help="把一个文件登记进素材库")
    common(p); p.set_defaults(func=_do_add)
    p.add_argument("source"); p.add_argument("--kind", required=True)
    p.add_argument("--license", required=True)
    p.add_argument("--id", default=None); p.add_argument("--title", default=None)
    p.add_argument("--provider", default="local"); p.add_argument("--provider-id")
    p.add_argument("--creator"); p.add_argument("--creator-url")
    p.add_argument("--source-url"); p.add_argument("--download-url")
    p.add_argument("--downloaded-at")
    p.add_argument("--tag", action="append", default=None); p.add_argument("--mood")
    p.add_argument("--scene"); p.add_argument("--use-for"); p.add_argument("--avoid-for")
    p.add_argument("--bpm", type=float); p.add_argument("--energy", type=int)
    p.add_argument("--sync-at", type=float); p.add_argument("--sync-meets")
    p.add_argument("--notes")
    p.add_argument("--no-copy", action="store_true",
                   help="文件已在素材库内时原地登记，不复制")
    p.add_argument("--project", default=None, help="进工程 assets/ 并写 sidecar")
    p.add_argument("--dest", default=None, help="自定义目标相对路径")
    p.add_argument("--allow-unknown", action="store_true")

    p = sub.add_parser("search", help="按元数据检索")
    common(p); p.set_defaults(func=_do_search)
    p.add_argument("query", nargs="?", default=None)
    p.add_argument("--kind", action="append", default=None)
    p.add_argument("--tag", action="append", default=None)
    p.add_argument("--any-tag", action="store_true")
    p.add_argument("--mood"); p.add_argument("--scene")
    p.add_argument("--provider", action="append", default=None)
    p.add_argument("--license"); p.add_argument("--commercial", action="store_true")
    p.add_argument("--min-duration", type=float); p.add_argument("--max-duration", type=float)
    p.add_argument("--has-sync", dest="has_sync", action="store_true", default=None)
    p.add_argument("--no-sync", dest="has_sync", action="store_false")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--sort", choices=("relevance", "title", "duration"), default="relevance")

    p = sub.add_parser("show", help="看一条记录")
    common(p); p.set_defaults(func=_do_show); p.add_argument("id")

    p = sub.add_parser("path", help="打印素材绝对路径（脚本用）")
    common(p); p.set_defaults(func=_do_path); p.add_argument("id")

    p = sub.add_parser("set-license", help="给已登记素材补/改授权")
    common(p); p.set_defaults(func=_do_set_license); p.add_argument("id")
    p.add_argument("--license", required=True)
    p.add_argument("--checked-at"); p.add_argument("--notes")

    p = sub.add_parser("verify", help="核验文件/哈希/授权")
    common(p); p.set_defaults(func=_do_verify)
    p.add_argument("--non-commercial", action="store_true")
    p.add_argument("--strict", action="store_true", help="授权未知直接判 fail")
    p.add_argument("--no-hash", action="store_true")

    p = sub.add_parser("export", help="导出素材库授权台账")
    common(p); p.set_defaults(func=_do_export)
    p.add_argument("--out", default=None)
    p.add_argument("--non-commercial", action="store_true")
    p.add_argument("--strict", action="store_true")

    p = sub.add_parser("audit", help="导出某工程实际用量的授权台账")
    common(p); p.set_defaults(func=_do_audit)
    p.add_argument("project"); p.add_argument("--non-commercial", action="store_true")
    p.add_argument("--strict", action="store_true")

    p = sub.add_parser("suggest", help="按字幕召回候选素材（不改 config）")
    common(p); p.set_defaults(func=_do_suggest)
    p.add_argument("project"); p.add_argument("--cue", type=int, required=True)
    p.add_argument("--kind", default="broll"); p.add_argument("--limit", type=int, default=8)
    p.add_argument("--remote", default=None, help="逗号分隔：pexels,pixabay")

    p = sub.add_parser("stats", help="素材库统计")
    common(p); p.set_defaults(func=_do_stats)

    p = sub.add_parser("seed", help="重新登记随包素材")
    common(p); p.set_defaults(func=_do_seed); p.add_argument("--force", action="store_true")

    p = sub.add_parser("licenses", help="列出许可目录")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=_do_licenses)

    remote = sub.add_parser("remote", help="远程源：Pexels/Pixabay")
    rsub = remote.add_subparsers(dest="remote_cmd", required=True)
    p = rsub.add_parser("search")
    common(p); p.set_defaults(func=_do_remote_search)
    p.add_argument("provider", choices=("pexels", "pixabay"))
    p.add_argument("--media", choices=("video", "photo"), default="video")
    p.add_argument("--query", required=True); p.add_argument("--limit", type=int, default=12)
    p.add_argument("--orientation", choices=("landscape", "portrait", "square"))
    p.add_argument("--quality", type=int, default=1080)
    p.add_argument("--min-duration", type=float); p.add_argument("--max-duration", type=float)
    p = rsub.add_parser("add")
    common(p); p.set_defaults(func=_do_remote_add)
    p.add_argument("provider", choices=("pexels", "pixabay"))
    p.add_argument("--media", choices=("video", "photo"), default="video")
    p.add_argument("--id", required=True); p.add_argument("--query", required=True)
    p.add_argument("--quality", type=int, default=1080)
    p.add_argument("--project", default=None)
    p.add_argument("--tag", action="append", default=None); p.add_argument("--title")

    p = sub.add_parser("import-sfx-kit", help="导入本地 sfx-kit（CC0）")
    common(p); p.set_defaults(func=_do_import_sfx_kit)
    p.add_argument("path"); p.add_argument("--categories", default=None)
    p.add_argument("--limit", type=int); p.add_argument("--link", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    try:
        return int(a.func(a))
    except lib.AssetError as exc:
        print(f"素材库错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        from workflow.asset_remote import RemoteError
        if isinstance(exc, RemoteError):
            print(f"远程素材错误：{exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
