#!/usr/bin/env python3
"""校验实测常量登记表：`home` 指向的值，还和登记表里记的一致吗？

**这不是「常量有没有被改」的检查，是「改了之后有没有人知道」的检查。**
这些数字是「先量再抄」量出来的，量完就该有保质期。剪映升级、换参考片、换字体，
任何一个变了它们都可能失效 —— 但如果值改了而登记表没改，下一次没人知道该重量什么。

三态，和 verify.py 同一套：

| 状态 | 含义 |
|---|---|
| `ok` | home 指向的值与登记表一致 |
| `drift` | **值变了但登记表没跟着改** —— 要么同步登记表，要么这是误改 |
| `unchecked` | 读不到 home（工程不存在 / 模块没这个属性 / 条目本来就只记出处）|

⚠️ `unchecked` **不等于通过**。`references/measured.json` 里 `provenance: null` 的条目
是**出处待补**，不是「没问题」。

用法：
    python scripts/check_measured.py                 # 人读
    python scripts/check_measured.py --json
    python scripts/check_measured.py --only caption  # 只看某一类
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "references" / "measured.json"


def _py_literal(mod_name: str, attr: str):
    """用 AST 读源码里的字面量，**不 import**。

    为什么不 import：`import` 走 `__pycache__`，而缓存按 **(源码 mtime 的秒数, 文件大小)**
    判定有效性。`DESCENT_EM = 1.34` → `1.10` 这种**同尺寸**改动，如果和上一次编译落在同一秒内，
    缓存会被误判为有效 —— 校验器于是读到**旧值并报 ok**。

    那是**假阴性**，方向最坏：一个专门抓漂移的工具，在值真的变了的时候说「没问题」。
    实测踩到过（改完用 `cp` 还原，同秒同尺寸，校验器一直读 1.1）。

    AST 解析不碰缓存、不执行模块、也没有 import 副作用。
    """
    src = (ROOT / "scripts" / f"{mod_name}.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:                     # 只看模块顶层
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == attr:
                    return ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == attr and node.value is not None:
            return ast.literal_eval(node.value)
    raise AttributeError(f"{mod_name}.{attr} 不是模块顶层的字面量")


def _resolve(home: str, project: str | None) -> tuple[object, str]:
    """读 home 指向的当前值。返回 (值, 说明)。读不到就抛。"""
    kind, _, rest = home.partition(":")
    if kind == "py":
        mod_name, _, attr = rest.partition(":")
        return _py_literal(mod_name, attr), f"{mod_name}.{attr}"
    if kind == "json":
        path_s, _, dotted = rest.partition(":")
        # 工程路径可以换成别的工程：json:*/config.json:captions.size
        p = Path(path_s.replace("*", project or ""))
        if not p.is_absolute():
            p = ROOT / p
        cur = json.loads(p.read_text(encoding="utf-8"))
        for k in dotted.split("."):
            cur = cur[k]
        return cur, f"{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p} → {dotted}"
    raise ValueError(f"不认识的 home 写法：{home}")


def _same(a, b, tol: float) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a).lower() == str(b).lower()
    if a is None or b is None:
        return a is b
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    return abs(fa - fb) <= (abs(fb) * tol if tol else 0)


def check(*, project: str | None = None, only: str | None = None) -> dict:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = []
    for r in reg["records"]:
        rid = r["id"]
        if only and not rid.startswith(only):
            continue
        row = {"id": rid, "label": r.get("label"), "home": r.get("home"),
               "measured_at": r.get("measured_at"), "provenance": r.get("provenance")}
        if r.get("home") is None:
            row.update({"status": "unchecked",
                        "detail": "本条目只记出处，值另有正本（" + str(r.get("canonical", "?")) + "）"})
            rows.append(row)
            continue
        try:
            cur, where = _resolve(r["home"], project)
        except Exception as e:                                    # noqa: BLE001
            row.update({"status": "unchecked",
                        "detail": f"读不到 {r['home']}：{type(e).__name__}: {str(e)[:60]}"})
            rows.append(row)
            continue
        row["where"] = where
        row["recorded"] = r.get("value")
        row["actual"] = cur
        if _same(cur, r.get("value"), float(r.get("tol") or 0)):
            row["status"] = "ok"
            row["detail"] = f"{cur}"
        else:
            row["status"] = "drift"
            row["detail"] = (f"登记表记的是 {r.get('value')}，现在是 {cur} —— "
                             f"要么同步登记表，要么这是误改")
        if r.get("provenance") is None:
            row["provenance_missing"] = True
        rows.append(row)

    n = {s: sum(1 for x in rows if x["status"] == s) for s in ("ok", "drift", "unchecked")}
    gaps = [x["id"] for x in rows if x.get("provenance_missing")]
    return {"registry": str(REGISTRY.relative_to(ROOT)), "version": reg["version"],
            "rows": rows, "summary": {**n, "total": len(rows)},
            "provenance_missing": gaps}


def main() -> None:
    ap = argparse.ArgumentParser(description="校验实测常量登记表")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", default=None, help="只查某一类（按 id 前缀，如 caption / card）")
    ap.add_argument("--project", default="examples/baseline",
                    help="工程目录名（替换 home 里的 *；默认 examples/baseline）")
    a = ap.parse_args()
    r = check(project=a.project, only=a.only)

    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"  {r['registry']}  {r['summary']['total']} 条")
        w = max((len(x["id"]) for x in r["rows"]), default=10)
        mark = {"ok": "✓", "drift": "✗", "unchecked": "–"}
        for x in r["rows"]:
            extra = f"  （{x['detail']}）" if x["status"] != "ok" else ""
            print(f"    {mark[x['status']]} {x['id']:<{w}}  {x.get('where') or x['home'] or '-'}{extra}")
        s = r["summary"]
        print(f"\n  {s['ok']} 一致 / {s['drift']} 漂移 / {s['unchecked']} 没查（共 {s['total']} 条）")
        if r["provenance_missing"]:
            print(f"  ⚠ 出处待补 {len(r['provenance_missing'])} 条："
                  f"{'、'.join(r['provenance_missing'])}")
            print(f"    这些常量是真的在用，只是没人记得它们当初是对着什么量的。")
    if r["summary"]["drift"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
