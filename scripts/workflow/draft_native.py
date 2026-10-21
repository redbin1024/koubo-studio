"""剪映原生草稿适配层：把「剪映自己保存过的草稿」接进本项目的流水线。

背景（实测，见 references/lessons.md #30）：

- 剪映 11.6 在 macOS 上把活动时间线写进 `draft_info.json`，**保存后是密文**；
  `draft_content.json` 只是第三方可读的明文副本，剪映不保证跟着更新。
- 本项目原来的草稿层只认 `draft_content.json`：一旦草稿被剪映打开并保存，
  我们既读不回真实内容，也不敢覆盖（`install_draft` 的 cover 保护）。
- [jianying-tool](https://pypi.org/project/jianying-tool/) 能用本机
  `libvideoeditor.dylib` / `videoeditor.dll` 解/加密原生草稿。它要求 Python 3.10+，
  而本仓库的运行环境可能是 3.9，所以这里做成**可选的子进程桥**，不是硬依赖。

这个模块只做四件事，不碰剪辑决策：

1. `active_path` / `read_draft`：读出剪映真正在用的那份草稿（必要时走桥解密）。
2. `sync_twin`：把活动文件镜像到另一份明文副本，让本项目的 audit/verify 能看；
   剪映下次打开仍然读活动文件，两边不会各说各话。
3. `doctor`：装了 jianying-tool 就做深度诊断，没装就做基础结构检查（如实标 source）。
4. `export`：转给 jianying-tool 驱动剪映自己的导出对话框（可选，GUI 操作）。

**三态原则不变**：桥不可用时返回 `source: "unavailable"` 或明确报错，
不能把「没检查」说成「通过」。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from _common import env_get, repo_root

# 与 PyPI 上实测过的版本对齐；升级前先重跑 tests/test_draft_native.py 与真草稿验证。
JYTOOL_VERSION = "0.5.0"
PYPI_EXTRAS = "jianying-tool==0.5.0"

DRAFT_FILES = ("draft_info.json", "draft_content.json")
BACKUP_DIR = ".koubo-backups"
BRIDGE = Path(__file__).resolve().parents[1] / "jytool_bridge.py"


class DraftNativeError(RuntimeError):
    """适配层所有可预期失败的基类。"""


class DraftNotFound(DraftNativeError):
    pass


class DraftEncrypted(DraftNativeError):
    """草稿是原生加密封装，而当前环境没有可用的 jianying-tool。"""


class BridgeUnavailable(DraftNativeError):
    pass


class BridgeError(DraftNativeError):
    pass


# ---------------------------------------------------------------- 文件定位

def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def file_order() -> tuple[str, str]:
    """活动文件优先序：macOS 是 draft_info，Windows 是 draft_content。"""
    if sys.platform == "darwin":
        return ("draft_info.json", "draft_content.json")
    return ("draft_content.json", "draft_info.json")


def active_path(draft: str | Path) -> Path:
    """剪映当前真正读取的那份时间线文件；都不存在时返回首选路径。"""
    draft = Path(draft)
    for name in file_order():
        candidate = draft / name
        if candidate.is_file():
            return candidate
    return draft / file_order()[0]


def twin_path(draft: str | Path) -> Path:
    """与活动文件配对的另一份（通常是明文副本）。"""
    draft = Path(draft)
    active = active_path(draft)
    first, second = (draft / name for name in file_order())
    return second if active == first else first


def _decode_plain(raw: bytes) -> Optional[dict]:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- 桥（jianying-tool）

_PROBE: Optional[dict] = None


def _candidate_pythons() -> list[Path]:
    out: list[Path] = []
    env = env_get("JYTOOL_PYTHON")
    if env:
        out.append(Path(env).expanduser())
    for rel in ("vendor/jytool-venv", "vendor/jytool/venv", ".venv-jytool"):
        out.append(_venv_python(repo_root() / rel))
    # 当前解释器自己装了也能用；3.9 装不了 jianying-tool，试一下不亏（很快失败）。
    if sys.version_info >= (3, 10):
        out.append(Path(sys.executable))
    seen, unique = set(), []
    for path in out:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _run_bridge(python: Path, args: list[str], *, timeout: int = 60) -> dict:
    if not BRIDGE.is_file():
        raise BridgeUnavailable(f"缺桥脚本：{BRIDGE}")
    try:
        proc = subprocess.run(
            [str(python), str(BRIDGE), *args],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(repo_root()),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeError(f"{python} 跑桥失败：{exc}") from exc
    payload: dict = {}
    text = (proc.stdout or "").strip()
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}
    if proc.returncode != 0 or payload.get("ok") is False:
        detail = payload.get("error") or (proc.stderr or "").strip()[-600:]
        raise BridgeError(f"jianying-tool 桥失败（exit {proc.returncode}）：{detail or '无输出'}")
    return payload


def probe(*, refresh: bool = False) -> dict:
    """探测可用的 jianying-tool 桥；结果在进程内缓存。"""
    global _PROBE
    if _PROBE is not None and not refresh:
        return _PROBE
    result: dict[str, Any] = {
        "available": False,
        "python": None,
        "version": None,
        "python_version": None,
        "error": None,
        "hint": (f"python scripts/draft_native.py setup（装 {PYPI_EXTRAS}，需要 uv）"),
    }
    errors: list[str] = []
    for python in _candidate_pythons():
        if not python.is_file():
            continue
        try:
            payload = _run_bridge(python, ["info"], timeout=30)
        except BridgeError as exc:
            errors.append(f"{python}: {exc}")
            continue
        result.update(
            available=True,
            python=str(python),
            version=payload.get("version"),
            python_version=payload.get("python"),
        )
        break
    if not result["available"] and errors:
        result["error"] = errors[-1]
    _PROBE = result
    return result


def bridge_python() -> Optional[Path]:
    info = probe()
    return Path(info["python"]) if info.get("available") and info.get("python") else None


# ---------------------------------------------------------------- 读 / 写

def read_draft(draft: str | Path, *, allow_bridge: bool = True) -> tuple[dict, dict]:
    """读活动草稿。

    返回 `(content, meta)`；meta 里记清读的是哪份文件、什么格式、是不是走了桥，
    这样 audit / verify 能把「读的是剪映那份」写进报告，而不是含糊地说「读到了」。
    """
    draft = Path(draft).resolve()
    path = active_path(draft)
    if not path.is_file():
        raise DraftNotFound(f"草稿里没有 {file_order()[0]} 或 {file_order()[1]}：{draft}")
    raw = path.read_bytes()
    data = _decode_plain(raw)
    if data is not None:
        return data, {"path": str(path), "file": path.name, "format": "json",
                      "bytes": len(raw), "codec": False}
    if not allow_bridge:
        raise DraftEncrypted(
            f"{path.name} 是剪映原生加密格式；读它需要 jianying-tool。"
            f"装：python scripts/draft_native.py setup")
    info = probe()
    if not info.get("available"):
        raise DraftEncrypted(
            f"{path.name} 是剪映原生加密格式；当前没有可用的 jianying-tool。"
            f"{info.get('hint') or ''}")
    payload = _run_bridge(Path(info["python"]), ["read", "--draft", str(draft)], timeout=120)
    content = payload.get("content")
    if not isinstance(content, dict):
        raise BridgeError("桥返回的草稿内容不是对象")
    return content, {"path": payload.get("path") or str(path), "file": path.name,
                     "format": payload.get("format") or "jianying-native",
                     "bytes": len(raw), "codec": True,
                     "tool": info.get("version")}


def _write_atomic(path: Path, data: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return len(payload)


def _backup(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.parent / BACKUP_DIR / stamp / path.name
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = path.parent / BACKUP_DIR / f"{stamp}-{suffix}" / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest


def write_all(draft: str | Path, data: dict) -> list[dict]:
    """把同一份内容写进草稿里所有**明文**文件；加密文件不盲改。

    执行层在最后几步（字体、行距）直接改 JSON 时用它，避免只更新
    `draft_content.json`、而剪映实际读取的 `draft_info.json` 还停在旧版本。
    """
    draft = Path(draft)
    results: list[dict] = []
    for name in DRAFT_FILES:
        path = draft / name
        if path.exists():
            if _decode_plain(path.read_bytes()) is None:
                results.append({"path": str(path), "written": False,
                                "skipped": "原生加密，交给剪映/jianying-tool 改写"})
                continue
        results.append({"path": str(path), "written": True, "bytes": _write_atomic(path, data)})
    if results and not any(item["written"] for item in results):
        raise DraftEncrypted(
            f"{draft} 的两份草稿都是加密格式；本函数只写明文，不盲改加密文件")
    return results


def twin_status(draft: str | Path, *, active_data: Optional[dict] = None) -> dict:
    """两份文件的对账信息：谁更新、是否同内容、能不能读。

    有一份是密文时，`equal` 只有在对端能解出来时才是 True/False，否则是 None
    （「不知道」不能写成「不一致」，更不能写成「一致」）。
    """
    draft = Path(draft)
    active, twin = active_path(draft), twin_path(draft)
    status: dict[str, Any] = {
        "active": str(active), "twin": str(twin),
        "active_exists": active.is_file(), "twin_exists": twin.is_file(),
    }
    if not (active.is_file() and twin.is_file()):
        return status
    a_raw, t_raw = active.read_bytes(), twin.read_bytes()
    a_data, t_data = _decode_plain(a_raw), _decode_plain(t_raw)
    if a_data is None and active_data is not None:
        a_data = active_data
    if a_data is None or t_data is None:
        # 有一份是剪映密文：能走桥就解出来再比，不能就诚实记 None。
        try:
            a_data = read_draft(draft)[0]
        except DraftNativeError:
            pass
    equal: Optional[bool] = None
    if a_data is not None and t_data is not None:
        equal = a_data == t_data
    status.update(
        active_mtime=active.stat().st_mtime, twin_mtime=twin.stat().st_mtime,
        active_plaintext=(_decode_plain(a_raw) is not None),
        twin_plaintext=(t_data is not None),
        equal=equal,
        newer=("twin" if twin.stat().st_mtime > active.stat().st_mtime + 1.0
               else "active" if active.stat().st_mtime > twin.stat().st_mtime + 1.0
               else None),
    )
    return status


def sync_twin(draft: str | Path, *, force: bool = False, source: str = "auto") -> dict:
    """把两份草稿文件对齐成同一内容，带备份与方向保护。

    方向：
    - `source="auto"`（默认）：**较新的那份是正本**。剪映/jianying-tool 保存后活动文件
      更新，就自动活动 → 副本；本项目只改了明文副本时，就是副本 → 活动文件。
      两边时间几乎相同（≤1s）时拒绝猜，要求显式指定或 `--force`（以活动文件为准）。
    - `source="active"`：活动文件 → 副本。
    - `source="twin"`：副本 → 活动文件。

    加密的**目标**文件默认不覆盖（会把它变成明文），确认后加 `force`。
    """
    if source not in {"auto", "active", "twin"}:
        raise ValueError("source 只能是 auto / active / twin")
    draft = Path(draft).resolve()
    status = twin_status(draft)
    active, twin = Path(status["active"]), Path(status["twin"])
    a_ok, t_ok = status.get("active_exists"), status.get("twin_exists")
    if not a_ok and not t_ok:
        raise DraftNotFound(f"草稿里没有 {file_order()[0]} 或 {file_order()[1]}：{draft}")

    # 只有一份：补齐另一份，不涉及方向选择。
    if a_ok != t_ok:
        if a_ok:
            data, meta = read_draft(draft)
            src_path, dst = active, twin
            source_format = meta["format"]
        else:
            data = _decode_plain(twin.read_bytes())
            if data is None:
                raise DraftEncrypted(
                    f"{twin.name} 是加密的非活动文件；桥只解活动文件，无法补齐")
            src_path, dst = twin, active
            source_format = "json"
        backup = _backup(dst) if dst.is_file() else None
        size = _write_atomic(dst, data)
        return {"draft": str(draft), "active": str(active), "twin": str(twin),
                "active_format": source_format, "written": True,
                "from": src_path.name, "to": dst.name, "bytes": size,
                "backup": str(backup) if backup else None,
                "reason": "补齐缺失的一份"}

    if status.get("equal") is True:
        return {"draft": str(draft), "active": str(active), "twin": str(twin),
                "active_format": ("jianying-native" if not status.get("active_plaintext")
                                  else "json"),
                "written": False, "reason": "already-in-sync", "backup": None}

    if source == "active":
        src, dst = active, twin
    elif source == "twin":
        src, dst = twin, active
    else:
        delta = active.stat().st_mtime - twin.stat().st_mtime
        if abs(delta) <= 1.0 and not force:
            raise DraftNativeError(
                "两份文件时间几乎相同，无法判断哪份是正本；"
                "用 --from active / --from twin 指定，或 --force 以活动文件为准")
        src, dst = (active, twin) if delta >= 0 else (twin, active)

    if src == active:
        data, meta = read_draft(draft)
        source_format = meta["format"]
    else:
        data = _decode_plain(src.read_bytes())
        if data is None:
            raise DraftEncrypted(
                f"{src.name} 是加密的非活动文件；桥只解活动文件，请用 --from active")
        source_format = "json"

    dst_data = _decode_plain(dst.read_bytes()) if dst.is_file() else None
    if dst.is_file() and dst_data is None and not force:
        raise DraftNativeError(
            f"{dst.name} 是加密格式；同步会把它改写成明文，确认后加 --force")
    backup = _backup(dst) if dst.is_file() else None
    size = _write_atomic(dst, data)
    return {"draft": str(draft), "active": str(active), "twin": str(twin),
            "active_format": source_format, "written": True,
            "from": src.name, "to": dst.name, "bytes": size,
            "backup": str(backup) if backup else None,
            "reason": "两份内容不一致，以较新的为准" if source == "auto"
            else f"按指定方向 {source} 覆盖"}


def ensure_twin(draft: str | Path) -> dict:
    """构建流程里的尽力对齐：谁新谁就是正本；失败只回报，不打断草稿生成。"""
    try:
        return sync_twin(draft, source="auto")
    except (DraftNativeError, OSError) as exc:
        return {"draft": str(draft), "written": False, "reason": str(exc)}


# ---------------------------------------------------------------- 诊断

def _basic_doctor(draft: Path, data: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    tracks = [t for t in data.get("tracks") or [] if isinstance(t, dict)]
    segments = [s for track in tracks for s in track.get("segments") or [] if isinstance(s, dict)]
    materials = data.get("materials") or {}
    pools = {k: v for k, v in materials.items() if isinstance(v, list)}
    known = {item.get("id") for pool in pools.values() for item in pool
             if isinstance(item, dict) and item.get("id")}
    if not tracks:
        errors.append("没有 tracks")
    if not segments:
        errors.append("所有轨道都没有片段")
    end = 0
    for index, segment in enumerate(segments, 1):
        tr = segment.get("target_timerange")
        if not isinstance(tr, dict) or float(tr.get("duration") or 0) <= 0:
            errors.append(f"片段 #{index} 没有有效的 target_timerange")
            continue
        end = max(end, int(tr.get("start") or 0) + int(tr.get("duration") or 0))
        material_id = segment.get("material_id")
        if material_id and material_id not in known:
            errors.append(f"片段 #{index} 引用了不存在的素材 {material_id}")
        for ref in segment.get("extra_material_refs") or []:
            if ref not in known:
                errors.append(f"片段 #{index} 的附加素材引用失效：{ref}")
    duration = float(data.get("duration") or 0) / 1_000_000
    if duration <= 0:
        errors.append("顶层 duration 为 0")
    elif abs(duration - end / 1_000_000) > 0.5:
        warnings.append(f"顶层 duration {duration:.3f}s 与轨道结尾 {end / 1e6:.3f}s 不一致")
    missing = []
    for group in ("videos", "audios"):
        for material in pools.get(group) or []:
            path = material.get("path") if isinstance(material, dict) else None
            if path and not Path(path).exists():
                missing.append(Path(path).name)
    if missing:
        warnings.append(f"素材文件缺失 {len(missing)} 个：{'、'.join(missing[:3])}")
    twin = twin_path(draft)
    if not twin.is_file():
        warnings.append(f"缺明文副本 {twin.name}；本项目的 audit/verify 会读不到这份草稿")
    return {"ok": not errors, "source": "basic", "errors": errors, "warnings": warnings,
            "counts": {"tracks": len(tracks), "segments": len(segments),
                       "materials": len(known)}}


def doctor(draft: str | Path) -> dict:
    """完整诊断：有 jianying-tool 用它的 doctor，没有就退到基础结构检查。"""
    draft = Path(draft).resolve()
    if not draft.is_dir():
        return {"ok": False, "source": "none", "errors": [f"草稿目录不存在：{draft}"],
                "warnings": [], "counts": {}}
    info = probe()
    if info.get("available"):
        payload = _run_bridge(Path(info["python"]), ["doctor", "--draft", str(draft)], timeout=120)
        report = dict(payload.get("report") or {})
        report["source"] = "jianying-tool"
        report["tool"] = info.get("version")
        return report
    try:
        data, meta = read_draft(draft, allow_bridge=False)
    except DraftEncrypted as exc:
        return {"ok": None, "source": "unavailable", "errors": [],
                "warnings": [str(exc)], "counts": {},
                "hint": info.get("hint")}
    except DraftNotFound as exc:
        return {"ok": False, "source": "none", "errors": [str(exc)],
                "warnings": [], "counts": {}}
    report = _basic_doctor(draft, data)
    report["file"] = meta["path"]
    return report


# ---------------------------------------------------------------- 导出

def export(*, draft: str, title: str, output_dir: str | Path,
           root: str | Path | None = None, resolution: Optional[str] = None,
           framerate: Optional[str] = None, close: bool = False,
           timeout: int = 900) -> dict:
    """驱动剪映自己的导出对话框（GUI 自动化，只在用户明确要求时调用）。"""
    info = probe()
    if not info.get("available"):
        raise BridgeUnavailable(
            f"导出需要 jianying-tool：{info.get('hint') or ''}")
    env = os.environ.copy()
    if root:
        env["JIANYING_DRAFT_ROOT"] = str(Path(root).expanduser().resolve())
    cmd = [str(info["python"]), "-m", "jianying_tool.cli", "export",
           "--draft", draft, "--title", title, "--output-dir", str(output_dir)]
    if resolution:
        cmd += ["--resolution", str(resolution)]
    if framerate:
        cmd += ["--framerate", str(framerate)]
    if close:
        cmd.append("--close")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        raise BridgeError("剪映导出失败（exit %d）：\n%s" % (proc.returncode, "\n".join(tail)))
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"raw": (proc.stdout or "").strip()}


# ---------------------------------------------------------------- 安装（本地 venv）

def setup(*, python_version: str = "3.12", force: bool = False) -> dict:
    """在仓库 `vendor/jytool-venv` 里装一个独立的 3.10+ 环境。

    不碰项目 `.venv`（它可能是 3.9，装不了 jianying-tool），也不碰系统 Python。
    需要 `uv`：`brew install uv` / `pip install uv`。
    """
    uv = shutil.which("uv")
    if not uv:
        raise DraftNativeError("找不到 uv；先装：brew install uv（或 pip install uv）")
    root = repo_root()
    venv = root / "vendor" / "jytool-venv"
    python = _venv_python(venv)
    if python.is_file() and not force:
        info = probe(refresh=True)
        if info.get("available") and info.get("python") == str(python):
            return {"created": False, "python": str(python), "probe": info}
    if venv.exists() and (force or not python.is_file()):
        # 坏 venv（解释器被清理工具带走）或用户要求重建：先删干净，
        # 否则 uv 会复用一个指向空路径的环境。
        shutil.rmtree(venv)
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", str(root / ".cache" / "uv"))
    # 解释器放在 vendor 里，和 venv 一起被清掉/保留；放 .cache 会被清理工具带走，
    # 留下一个 bin/python 指向空路径的坏 venv。
    env.setdefault("UV_PYTHON_INSTALL_DIR", str(root / "vendor" / "jytool-python"))
    venv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([uv, "venv", "--python", python_version, str(venv)],
                   check=True, capture_output=True, text=True, env=env)
    install = subprocess.run(
        [uv, "pip", "install", "--python", str(python), PYPI_EXTRAS],
        capture_output=True, text=True, env=env,
    )
    if install.returncode != 0:
        tail = (install.stderr or install.stdout or "").strip().splitlines()[-8:]
        raise DraftNativeError("安装 jianying-tool 失败：\n" + "\n".join(tail))
    info = probe(refresh=True)
    if not info.get("available"):
        raise DraftNativeError(f"装完仍探测不到：{info.get('error') or info.get('hint')}")
    return {"created": True, "python": str(python), "probe": info}


# ---------------------------------------------------------------- 汇总信息

def info(draft: str | Path | None = None) -> dict:
    data: dict[str, Any] = {"bridge": probe()}
    if draft is not None:
        draft = Path(draft).resolve()
        try:
            content, meta = read_draft(draft)
            data["draft"] = {
                "path": str(draft), "file": meta["path"], "format": meta["format"],
                "codec": meta["codec"], "readable": True,
                "tracks": [{"name": t.get("name"), "type": t.get("type"),
                            "segments": len(t.get("segments") or [])}
                           for t in content.get("tracks") or [] if isinstance(t, dict)],
                "duration": float(content.get("duration") or 0) / 1_000_000,
                "twin": twin_status(draft),
            }
        except (DraftNativeError, OSError) as exc:
            data["draft"] = {"path": str(draft), "readable": False, "error": str(exc)}
    return data
