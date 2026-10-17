"""Identify exactly which finished video belongs to the current project state."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


RECEIPT = "render-receipt.json"


def receipt_digest(project: Path) -> str | None:
    """Identity of one render run, shared by the draft writer and QC reader."""
    try:
        return hashlib.sha256((Path(project) / "work" / RECEIPT).read_bytes()).hexdigest()
    except OSError:
        return None


def draft_matches_receipt(project: Path, draft: Path, report: dict) -> bool:
    """A pre-existing draft only counts when it was built for this render."""
    identity = receipt_digest(project)
    return bool(identity and (draft / "draft_info.json").is_file() and
                (draft / "draft_content.json").is_file() and
                report.get("draft") == str(draft) and
                report.get("render_receipt_sha256") == identity)


def _fingerprint(project: Path, cfg: dict) -> str:
    digest = hashlib.sha256(json.dumps(cfg, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8"))
    # Bind the receipt to files that render.build actually consumes. The edit plan
    # alone cannot identify a cut: --apply-plan can rewrite clean-cut.mp4 in place.
    from _common import resolve_video
    inputs = [project / "work/edit-plan.json", project / "work/body-anim-silent.mp4",
              project / "work/sfx-track.wav", project / "work/voice.wav",
              project / "work/bgm.wav",
              # 逐条字幕样式与插图素材都是烘进 body-anim-silent.mp4 的输入，
              # 但它们**不改变**上面任何一个文件的字节：只改样式不重渲，
              # 旧凭据仍会匹配，verify 就会放行一条不含新样式的成片。
              project / "work/style-plan.json",
              # 解说稿改了就必须重配音、重渲染：它是 voice.wav 的来源，本身不是产物。
              project / "work/narration-lines.json",
              project / "input" / (cfg["input"].get("subtitle") or "captions.srt")]
    # 插图由 assets 步生成，文件名按序号，取全量并排序保证指纹可复现。
    for picture in sorted((project / "assets").glob("insert-*.png")):
        inputs.append(picture)
    voice_subtitle = cfg["audio"].get("voice_subtitle")
    if voice_subtitle:
        inputs.append(project / "input" / voice_subtitle)
    voice_cues = cfg["audio"].get("voice_cues")
    if voice_cues:
        inputs.append(project / "work" / voice_cues)
    try:
        inputs.append(resolve_video(cfg, project))
    except (OSError, ValueError, SystemExit):
        # An absent source must invalidate the receipt, not crash the QC report.
        inputs.append(project / "input" / "<missing-source>")
    for path in inputs:
        path = Path(path).resolve()
        digest.update(str(path).encode("utf-8"))
        if path.is_file():
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def record_render(project: Path, movie: Path, cfg: dict) -> dict:
    project, movie = Path(project).resolve(), Path(movie).resolve()
    stat = movie.stat()
    receipt = {"output": str(movie), "size": stat.st_size,
               "mtime_ns": stat.st_mtime_ns, "inputs_sha256": _fingerprint(project, cfg)}
    work = project / "work"
    work.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".render-receipt-", suffix=".json", dir=work)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, work / RECEIPT)
    finally:
        Path(name).unlink(missing_ok=True)
    return receipt


def current_output(project: Path, cfg: dict) -> tuple[Path | None, str]:
    project = Path(project).resolve()
    path = project / "work" / RECEIPT
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        movie = Path(receipt["output"]).resolve()
        stat = movie.stat()
        if (movie.parent != project / "output" or
                not movie.name.startswith("final-") or movie.suffix != ".mp4" or
                receipt["size"] != stat.st_size or receipt["mtime_ns"] != stat.st_mtime_ns or
                receipt["inputs_sha256"] != _fingerprint(project, cfg)):
            raise ValueError("成片或配置已变化")
    except (OSError, ValueError, KeyError, TypeError):
        return None, "找不到与当前配置匹配的本轮渲染凭据；旧成片不能作为本轮交付"
    return movie, f"本轮成片 {movie}"
