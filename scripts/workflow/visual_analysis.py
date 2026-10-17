"""Reviewable visual suggestions from one small frame per planned shot."""
from __future__ import annotations

import base64
import copy
import json
import math
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from _common import find_ffmpeg, probe_media
from .edit_plan import validate_plan


ENDPOINT = "https://api.deepseek.com/chat/completions"
MAX_SHOTS = 24
BATCH_SIZE = 8
INSTRUCTIONS = (
    "你是视频镜头审片助手。每张图片只是一段镜头的代表帧，不能声称看到了完整动作、"
    "听到了对话或知道人物身份。输出严格 JSON 对象，字段 shots 为数组，"
    "每张图必须返回且只返回对应 id、description(可见事实的简短中文)、"
    "usable(画面是否可用的布尔值)、confidence(0到1)、"
    "caption_suggestion(仅描述可见画面，可为空字符串)。不得编造上下文。"
)


def api_key_from_env() -> str:
    return os.environ.get("DEEPSEEK_API_KEY", "")


def extract_frame(source: Path, at: float, output: Path) -> None:
    """Extract a low-resolution JPEG; never change the original media."""
    if not math.isfinite(at) or at < 0:
        raise ValueError("抽帧时间必须为非负有限数")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-ss", f"{at:.3f}",
                        "-i", str(source), "-frames:v", "1", "-vf", "scale=512:-2",
                        "-q:v", "4", str(output)], check=True, capture_output=True)
        if not output.is_file() or output.stat().st_size == 0:
            raise ValueError(f"无法从 {source} 抽取代表帧")
    except Exception:
        output.unlink(missing_ok=True)
        raise


def _http_transport(body: dict, key: str) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=payload, headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def _batch_result(response: dict, ids: list[str]) -> dict[str, dict]:
    try:
        payload = json.loads(response["choices"][0]["message"]["content"])
        entries = payload["shots"]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("视觉 API 未返回符合约定的 JSON") from exc
    if not isinstance(entries, list):
        raise ValueError("视觉 API 的 shots 必须是数组")
    results = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("视觉 API 镜头建议不是对象")
        ident = entry.get("id")
        confidence = entry.get("confidence")
        if ident not in ids or ident in results:
            raise ValueError("视觉 API 返回了未知或重复的镜头 ID")
        if not isinstance(entry.get("description"), str) or not entry["description"].strip():
            raise ValueError("视觉 API 镜头描述为空")
        if not isinstance(entry.get("usable"), bool):
            raise ValueError("视觉 API 可用性必须是布尔值")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("视觉 API 置信度不是数值")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("视觉 API 置信度超出 0-1")
        if not isinstance(entry.get("caption_suggestion"), str):
            raise ValueError("视觉 API 文案建议必须是字符串")
        results[ident] = {key: entry[key] for key in
                          ("description", "usable", "confidence", "caption_suggestion")}
    if set(results) != set(ids):
        raise ValueError("视觉 API 漏掉了镜头 ID")
    return results


def analyze_shots(plan: dict, *, api_key: str | None = None,
                  transport=None, model: str = "deepseek-flash") -> dict:
    """Attach suggestions to a copy of the plan, leaving source shots untouched."""
    key = api_key if api_key is not None else api_key_from_env()
    if not key:
        raise ValueError("缺少 DEEPSEEK_API_KEY；未抽帧、未上传素材")
    shots = plan.get("shots", [])
    if len(shots) > MAX_SHOTS:
        raise ValueError(f"最多分析 {MAX_SHOTS} 个镜头；请先分批缩减方案")
    sources = {str(Path(s["source"]).resolve()) for s in shots}
    durations = {s: probe_media(s)["duration"] for s in sources}
    validate_plan(plan, durations)
    result = copy.deepcopy(plan)
    send = transport or _http_transport
    with tempfile.TemporaryDirectory(prefix="thsp-vision-") as tmp:
        for offset in range(0, len(shots), BATCH_SIZE):
            content, ids = [{"type": "text", "text": "逐镜头分析代表帧，不推断不可见事实。"}], []
            for i in range(offset, min(offset + BATCH_SIZE, len(shots))):
                shot = shots[i]
                ident = f"shot_{i + 1}"
                ids.append(ident)
                image = Path(tmp) / f"{ident}.jpg"
                extract_frame(Path(shot["source"]), float(shot["in"]) +
                              float(shot["duration"]) / 2, image)
                encoded = base64.b64encode(image.read_bytes()).decode("ascii")
                content.extend([
                    {"type": "text", "text": f"{ident}，时长 {shot['duration']} 秒："},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/jpeg;base64," + encoded, "detail": "low"}},
                ])
            body = {"model": model, "temperature": 0, "max_tokens": 1200,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": INSTRUCTIONS},
                                 {"role": "user", "content": content}]}
            analyzed = _batch_result(send(body, key), ids)
            for i in range(offset, offset + len(ids)):
                result["shots"][i]["visual"] = analyzed[f"shot_{i + 1}"]
    return result
