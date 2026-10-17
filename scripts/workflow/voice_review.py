"""Human narration decisions bound to the exact rendered review movies."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .delivery import current_output, receipt_digest
from .speech_policy import _declared_lines


REVIEW_VERSION = 2
CRITERIA = {"semantics": "声画语义", "voice": "声音自然度", "subtitles": "字幕遮挡"}
STATUS_LABELS = {"pending": "待人工验收", "failed": "需要修改", "passed": "人工验收通过",
                 "stale": "验收材料已失效", "not_required": "未声明逐句旁白验收"}


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def review_required(cfg: dict) -> bool:
    """有逐句旁白就要**逐句听审** —— 判据是「声明了 voice_cues」而不是某个模式名。

    现场人声 + 解说（mixed）同样有逐句旁白要审，把判据绑在模式名上会漏掉它。
    """
    audio = cfg.get("audio", {})
    return bool(audio.get("voice_cues")) and audio.get("speech_mode") in (
        "narration", "mixed")


def review_directory(project: Path, identity: str) -> Path:
    return Path(project) / "work/voice-review" / f"v{REVIEW_VERSION}-{identity[:16]}"


def load_review(cfg: dict, project: Path) -> tuple[Path, dict, str]:
    """Reject an old render, edited manifest, missing line, or replaced clip."""
    movie, detail = current_output(project, cfg)
    if movie is None:
        raise ValueError(detail)
    identity = receipt_digest(project)
    if not identity:
        raise ValueError("渲染凭据已变化，请重新检查成片")
    directory = review_directory(project, identity)
    manifest = directory / "manifest.json"
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
        windows, _, _, problem = _declared_lines(cfg, project)
        rows = record["lines"]
        if (problem or not windows or record.get("version") != REVIEW_VERSION or
                record.get("render_receipt_sha256") != identity or
                record.get("source_video") != str(movie) or not isinstance(rows, list) or
                len(rows) != len(windows)):
            raise ValueError("清单与当前成片或逐句声明不符")
        for number, (row, window) in enumerate(zip(rows, windows), 1):
            start, end, text = window
            if (row["index"] != number or row["text"] != text or
                    row["start"] != start or row["end"] != end or
                    row["clip"] != f"line-{number:02d}.mp4" or
                    not isinstance(row["shots"], list) or
                    any(type(shot["index"]) is not int for shot in row["shots"]) or
                    file_digest(directory / row["clip"]) != row["clip_sha256"]):
                raise ValueError(f"第 {number} 句样张或清单已变化")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"听审样张缺失、过期或已变化：{exc}；请保留旧记录，"
                         f"移走 {directory} 后重新导出听审样张") from exc
    return directory, record, file_digest(manifest)


def _valid_checks(checks: dict, reviewer: str, note: str) -> None:
    if (not isinstance(checks, dict) or set(checks) != set(CRITERIA) or
            any(value not in ("pass", "fail") for value in checks.values())):
        raise ValueError("每句须明确填写声画语义、声音自然度、字幕遮挡三项 pass/fail")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("须填写实际审核人")
    if not isinstance(note, str) or ("fail" in checks.values() and not note.strip()):
        raise ValueError("有未通过项时须填写问题说明")


def _read_decisions(directory: Path, record: dict, manifest_digest: str) -> dict:
    path = directory / "decisions.json"
    if not path.exists():
        return {"version": 1, "render_receipt_sha256": record["render_receipt_sha256"],
                "manifest_sha256": manifest_digest, "events": []}
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
        if (audit.get("version") != 1 or
                audit.get("render_receipt_sha256") != record["render_receipt_sha256"] or
                audit.get("manifest_sha256") != manifest_digest or
                not isinstance(audit.get("events"), list)):
            raise ValueError("审核记录与当前样张不匹配")
        for number, event in enumerate(audit["events"], 1):
            index = event["line"]
            if (type(index) is not int or not 1 <= index <= len(record["lines"]) or
                    event["sequence"] != number or
                    event["clip_sha256"] != record["lines"][index - 1]["clip_sha256"] or
                    datetime.fromisoformat(event["reviewed_at"]).tzinfo is None):
                raise ValueError("审核记录的句号、样张或时间无效")
            _valid_checks(event["checks"], event["reviewer"], event["note"])
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"审核记录无法复用：{exc}") from exc
    return audit


def _summarize(record: dict, audit: dict) -> dict:
    latest = {event["line"]: event for event in audit["events"]}
    rows = []
    for row in record["lines"]:
        event = latest.get(row["index"])
        state = ("failed" if "fail" in event["checks"].values() else "passed") if event else "pending"
        rows.append({"index": row["index"], "text": row["text"], "status": state,
                     "decision": event})
    counts = {state: sum(row["status"] == state for row in rows)
              for state in ("pending", "failed", "passed")}
    state = "failed" if counts["failed"] else "pending" if counts["pending"] else "passed"
    return {"status": state, "label": STATUS_LABELS[state], "summary": counts,
            "lines": rows, "render_receipt_sha256": record["render_receipt_sha256"],
            "events": len(audit["events"])}


def review_status(cfg: dict, project: Path) -> dict:
    if not review_required(cfg):
        return {"status": "not_required", "label": STATUS_LABELS["not_required"]}
    try:
        directory, record, digest = load_review(cfg, project)
        audit = _read_decisions(directory, record, digest)
    except ValueError as exc:
        identity = receipt_digest(project)
        state = "stale" if identity and (current_output(project, cfg)[0] is None or
                    review_directory(project, identity).exists()) else "pending"
        return {"status": state, "label": STATUS_LABELS[state], "detail": str(exc)}
    return {**_summarize(record, audit), "directory": str(directory),
            "manifest_sha256": digest}


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", "<br>").replace("\r", "")


def write_checklist(directory: Path, record: dict, status: dict) -> None:
    decisions = {row["index"]: row for row in status.get("lines", [])}
    table = ["# 旁白逐句听审", "", f"状态：**{status['label']}**", "",
             "逐句播放，核对声画语义、声音自然度、字幕遮挡。审核记录由 review_voice.py 登记；"
             "勾选本文不会改变验收状态。", "",
             "| 句 | 时窗 | 旁白文案 | 画面镜头 | 样张 | 验收 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in record["lines"]:
        decision = decisions.get(row["index"], {})
        event = decision.get("decision")
        label = STATUS_LABELS[decision.get("status", "pending")]
        if event:
            details = "、".join(f"{CRITERIA[key]}{'通过' if value == 'pass' else '未通过'}"
                              for key, value in event["checks"].items())
            label += f"：{details}；{event['reviewer']} / {event['reviewed_at']}"
            if event["note"]:
                label += f"；{event['note']}"
        shots = "、".join(str(shot["index"]) for shot in row["shots"]) or "无镜头表"
        table.append(f"| {row['index']} | {row['start']:.2f}–{row['end']:.2f}s | "
                     f"{_cell(row['text'])} | {shots} | [播放]({row['clip']}) | {_cell(label)} |")
    command = ("python3 " + shlex.quote(str(Path(__file__).resolve().parents[1] / "review_voice.py")) +
               " " + shlex.quote(str(directory.resolve().parents[2])))
    table.extend(["", "登记示例（每次记录一句，三个 pass 表示三项均经人工确认）：", "", "```bash",
                  command + ' --line 1 --reviewer "实际审核人" '
                  '--semantics pass --voice pass --subtitles pass',
                  "```", "", "未通过项填写 fail，并用 --note 写明问题。复审会追加记录，保留历史。",
                  "`manifest.json` 记录镜头与原素材时间映射；`decisions.json` 保存审核历史。"])
    (directory / "听审清单.md").write_text("\n".join(table) + "\n", encoding="utf-8")


def pipeline_review_state(status: str) -> str:
    if status in ("passed", "not_required"):
        return "complete"
    return "changes_requested" if status == "failed" else "awaiting_review"


def refresh_review(cfg: dict, project: Path) -> dict:
    """Write derived status; only update a matching, fully generated pipeline."""
    status = review_status(cfg, project)
    if "directory" in status:
        directory = Path(status["directory"])
        record = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        write_checklist(directory, record, status)
    atomic_json(Path(project) / "work/human-review.json", status)
    path = Path(project) / "work/pipeline.json"
    if path.is_file():
        try:
            pipeline = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pipeline = {}
        if (pipeline.get("automation_complete") is True and
                pipeline.get("render_receipt_sha256") == receipt_digest(project)):
            if current_output(project, cfg)[0] is None:
                pipeline.update(status="stale", automation_complete=False, human_review="stale")
            else:
                pipeline["human_review"] = status["status"]
                pipeline["status"] = pipeline_review_state(status["status"])
            atomic_json(path, pipeline)
    return status


def record_decision(cfg: dict, project: Path, line: int, checks: dict,
                    reviewer: str, note: str = "") -> dict:
    _valid_checks(checks, reviewer, note)
    directory, record, digest = load_review(cfg, project)
    if type(line) is not int or not 1 <= line <= len(record["lines"]):
        raise ValueError(f"句号须在 1–{len(record['lines'])} 之间")
    with (directory / ".decisions.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        audit = _read_decisions(directory, record, digest)
        # Check again inside the lock: never register a vote against a replaced render.
        if load_review(cfg, project)[2] != digest:
            raise ValueError("登记期间成片或样张发生变化，请重新听审")
        audit["events"].append({"sequence": len(audit["events"]) + 1, "line": line,
                                "checks": checks.copy(), "reviewer": reviewer.strip(),
                                "note": note.strip(), "reviewed_at": datetime.now(timezone.utc).isoformat(),
                                "clip_sha256": record["lines"][line - 1]["clip_sha256"]})
        atomic_json(directory / "decisions.json", audit)
        return refresh_review(cfg, project)
