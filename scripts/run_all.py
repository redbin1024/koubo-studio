#!/usr/bin/env python3
"""一条命令跑完整条流水线：可选粗剪 → 字幕 → 素材 → 音效 → 逐帧合成 → 成片 → 剪映草稿 → 质检 → 逐句听审样张。

**剪映草稿是默认产物，不是可选项。** 成片（mp4）是交付件，草稿是能继续改的工程；
两条都要出，缺一条这一轮就不算跑完。

每一步都会重新读 config，所以中途改配置可以单独重跑某一步：
    python scripts/make_captions.py DIR
    python scripts/build_frames.py DIR

用法：python scripts/run_all.py PROJECT_DIR [--skip MERGE,CAPTIONS,...]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    ensure_dirs, load_config, project_paths, resolve_duration, resolve_video, write_json,
)
import build_frames, make_assets, make_captions, make_jianying_draft, make_sfx, render, verify  # noqa: E402

# draft 排在 verify 之前：草稿没出（或被覆盖保护挡下）时，verify 的 jianying-draft 一项会红，
# 这样「每轮必出剪映草稿」是被质检卡住的，而不是靠人记得。
# narrate / voice 排在 captions 之前：跨字幕集的重叠预检要用到 input/voice-captions.srt，
# 而旁白字幕只有配音那一步才写得出来。
STEPS = ("align", "merge", "narrate", "voice", "captions", "assets", "sfx", "music",
         "beats", "preflight", "frames", "render", "draft", "asset-audit",
         "visual-review", "verify", "review-outputs", "review")


def wants_narration(cfg: dict) -> bool:
    """这条片子要不要解说旁白：声明了 speech_mode=mixed 或逐句时窗就算要。"""
    audio = cfg.get("audio") or {}
    return audio.get("speech_mode") == "mixed" or bool(audio.get("voice_cues"))


def do_align(cfg: dict, project: Path) -> dict:
    """外录对轨换声（双轨收音）。**跑在粗剪之前** —— 先把外录换进去，
    后面的转写/粗剪/成片才都是外录声。

    没配 `input.audio` / `input.audio_map` 就是**单轨**，整步零动作。
    高置信自动换轨并把产物记进 `work/align-report.json`；低置信**不硬上**，
    产一份剪映对齐草稿并如实登记，等人工拖完再跑 `align_audio.py --resume`。
    """
    from _common import ALIGN_REPORT, input_path, write_json
    import align_audio

    a = cfg["input"]
    mapping: list[tuple[Path, Path]] = []
    if a.get("video") and a.get("audio"):
        mapping.append((input_path(project, a["video"]), input_path(project, a["audio"])))
    for clip, ext in (a.get("audio_map") or {}).items():
        mapping.append((input_path(project, clip), input_path(project, ext)))
    mapping = [(v, x) for v, x in mapping if v.is_file() and x.is_file()]
    if not mapping:
        cfg_a = a.get("align") or {}
        have = bool(a.get("audio") or a.get("audio_map"))
        why = ("配了外录但文件找不到" if have else "没配外录 → **走单轨**（视频自带声音）")
        print(f"  {why}")
        return {"swaps": 0, "skipped": why}

    thr = float((a.get("align") or {}).get("threshold", 0.35))
    swaps, manual = {}, []
    for video, ext in mapping:
        m = align_audio.measure_offset(video, ext)
        conf = align_audio.confidence(m)
        print(f"  {video.name} ← {ext.name}  偏移 {m.get('offset', 0):+.3f}s  "
              f"置信度 {conf:.2f}（阈值 {thr}）")
        if not m.get("ok"):
            manual.append({"video": str(video), "audio": str(ext), "reason": m.get("reason")})
            print(f"    ⚠ {m.get('reason')} —— 这一条保持单轨")
            continue
        if conf < thr:
            # 不猜、不硬上：产对齐草稿，登记进报告，让用户拖
            outdir = project / "work" / "align-draft"
            from make_jianying_draft import find_capcut
            bin_ = find_capcut()
            proj = align_audio.make_align_draft(video, ext, outdir, bin_) if bin_ else None
            manual.append({"video": str(video), "audio": str(ext),
                           "confidence": round(conf, 3), "offset_sec": round(m["offset"], 3),
                           "draft": str(proj) if proj else None,
                           "reason": f"置信度 {conf:.2f} 低于阈值 {thr}，未自动换轨"})
            print(f"    ⚠ 置信度不足，**未换轨**；"
                  + (f"已产对齐草稿 {proj.name}，拖齐后跑 align_audio.py --resume" if proj
                     else "且没有 capcut CLI，产不了对齐草稿"))
            continue
        out = video.with_name(f"{video.stem}_extaudio.mp4")
        align_audio.swap(video, ext, m["offset"], out)
        swaps[str(video.resolve())] = str(out)
        print(f"    → {out.name}（画面原样，只换声）")

    report = {"version": 1, "threshold": thr, "swaps": swaps, "needs_manual": manual,
              "note": "swaps 是「原素材 → 换轨产物」；原始素材全部保留，是内录保底轨"}
    write_json(project / "work" / ALIGN_REPORT, report)
    if manual:
        print(f"  ⚠ {len(manual)} 条没自动换轨（见 work/align-report.json 的 needs_manual）"
              f" —— **没换 ≠ 换好了**")
    return {"swaps": len(swaps), "needs_manual": len(manual)}


def main() -> None:
    ap = argparse.ArgumentParser(description="跑完整条口播工坊流水线")
    ap.add_argument("project")
    ap.add_argument("--skip", default="", help="跳过的步骤，逗号分隔")
    ap.add_argument("--only", default="", help="只跑的步骤，逗号分隔")
    ap.add_argument("--auto", action="store_true",
                    help="全自动模式：跳过人工听审，pipeline 记为 automated")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    if a.auto:
        # 全自动交付不要求人工听审；需要复核时仍可单独跑 export_voice_review.py。
        skip.add("review")
    if any(s not in skip and (not only or s in only) for s in ("render", "draft")):
        from workflow.speech_policy import require_speech_ready
        initial = load_config(project / "config.json")
        # A new clip-based source-voice project has no merged video yet; check it
        # again at render/draft time after the merge stage has produced its input.
        mode = initial["audio"]["speech_mode"]
        if not (mode in ("source", "mixed")
                and initial["input"]["clips"] and not initial["input"]["video"]):
            if mode in ("source", "mixed"):
                # mixed 也要原声证据：现场人声那半一样要过检。
                from workflow.source_speech import prepare_source_evidence
                prepare_source_evidence(initial, project)
            # 这一趟就要生成旁白时，先别拦 —— 拦了就会出现「缺旁白 → 报错，
            # 而生成旁白的那一步永远轮不到」的死结。render / draft 前还会再检一次。
            voice_runs = (not only or "voice" in only) and "voice" not in skip
            waiting = (mode in ("narration", "mixed") and voice_runs
                       and not (project / "work" / "voice.wav").is_file())
            if not waiting:
                require_speech_ready(initial, project)
    p = ensure_dirs(project)
    log: dict = {"project": str(project), "steps": []}
    t_all = time.time()

    for step in STEPS:
        if step in skip or (only and step not in only):
            print(f"[{step}] 跳过")
            continue
        cfg = load_config(p["config"])
        t0 = time.time()
        print(f"[{step}]")
        try:
            if step == "align":
                result = do_align(cfg, project)
            elif step == "merge":
                if not cfg["input"].get("clips"):
                    print("  没有 input.clips，跳过粗剪")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                import merge_cut
                result = merge_cut.build(cfg, project, -34.0, 0.30, 0.10, 0.45, 0.40)
            elif step == "narrate":
                if not wants_narration(cfg):
                    print("  没有声明解说旁白，跳过装槽")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                lines = p["work"] / "narration-lines.json"
                if not lines.is_file():
                    # 不拦：真正的门禁在 render 前的 require_speech_ready，
                    # 这里只把话说清楚，免得卡在一句环境报错上。
                    print(f"  没有 {lines.name}，跳过（缺旁白会在出片前报错）")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                import tts
                result = tts.build(cfg, project, probe_only=True)
            elif step == "voice":
                if not wants_narration(cfg):
                    print("  没有声明解说旁白，跳过配音")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                lines = p["work"] / "narration-lines.json"
                voice = p["work"] / "voice.wav"
                if not lines.is_file():
                    print(f"  没有 {lines.name}，跳过配音（缺旁白会在出片前报错）")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                # 判「要不要重配」不能只看文件时间戳：槽的位置由镜头表**和算位置的那段
                # 代码**共同决定，代码改了而文件没动，时间戳是看不出来的。所以这里
                # 按现在的规则重新解一遍，和现有配音当时的解逐条比对，不一致才重配。
                import tts
                probe = tts.build(cfg, project, probe_only=True)
                recorded = {}
                try:
                    recorded = json.loads((p["work"] / "narration-resolved.json")
                                          .read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
                if voice.is_file() and recorded.get("lines") == probe["lines"]:
                    print(f"  旁白 {len(probe['lines'])} 句的位置与现有配音一致，不重配")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                result = tts.build(cfg, project, replace=True)
            elif step == "captions":
                result = make_captions.build(cfg, project)
            elif step == "assets":
                import render_illustrations
                rendered = render_illustrations.render_all(project)
                if rendered.get("rendered"):
                    print(f"  SVG 插图 {rendered['rendered']} 张 → assets/illustrations")
                result = make_assets.build(cfg, project)
            elif step == "sfx":
                total = resolve_duration(cfg, project)
                result = make_sfx.build(cfg, project, total)
            elif step == "music":
                bgm_cfg = (cfg.get("audio") or {}).get("bgm") or {}
                out = p["work"] / "bgm.wav"
                if not bgm_cfg.get("enabled"):
                    print("  audio.bgm.enabled = false，跳过 BGM")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                want = resolve_duration(cfg, project)
                if bgm_cfg.get("source") == "mixkit":
                    if not out.is_file():
                        raise SystemExit(f"audio.bgm.source=mixkit，但缺 {out}；先跑 koubo mixkit bgm")
                    print(f"  Mixkit BGM：{bgm_cfg.get('title', '')}（沿用 work/bgm.wav）")
                    log["steps"].append({"step": step, "status": "ok", "source": "mixkit"})
                    continue
                if bgm_cfg.get("music_id"):
                    import music_library
                    cloud = music_library.prepare(cfg, project, want)
                    print(f"  云端音乐 {cloud.get('music_id')} {cloud.get('title', '')}"
                          f"（{cloud.get('status')}）")
                    log["steps"].append({"step": step, "status": "ok", "cloud": cloud})
                    continue
                have = 0.0
                if out.is_file():
                    import wave
                    with wave.open(str(out), "rb") as wav:
                        have = wav.getnframes() / wav.getframerate()
                if out.is_file() and abs(have - want) <= 0.25:
                    print(f"  work/bgm.wav {have:.2f}s 与片长一致，不重算")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                import make_bgm
                result = make_bgm.build(cfg, project)
            elif step == "beats":
                from workflow.audio_beats import build as build_beats
                result = build_beats(project)
                print(f"  真重音 {len(result.get('beats') or [])} 个 → work/beats.json")
            elif step == "preflight":
                from workflow.preflight import check as preflight
                result = preflight(project)
                if result["errors"]:
                    raise SystemExit("；".join(result["errors"]))
                for warning in result.get("warnings") or []:
                    print(f"  ⚠ {warning}")
                print(f"  预检通过（B-roll {result['broll']} / 草稿资源 {result['fx']}）")
            elif step == "frames":
                result = build_frames.build(cfg, project, resolve_duration(cfg, project))
            elif step == "render":
                if cfg["audio"]["speech_mode"] in ("source", "mixed"):
                    from workflow.source_speech import prepare_source_evidence
                    prepare_source_evidence(cfg, project)
                result = render.build(cfg, project, resolve_duration(cfg, project))
            elif step == "draft":
                from workflow.speech_policy import require_speech_ready
                if cfg["audio"]["speech_mode"] in ("source", "mixed"):
                    from workflow.source_speech import prepare_source_evidence
                    prepare_source_evidence(cfg, project)
                require_speech_ready(cfg, project)
                jy = cfg["jianying"]
                result = make_jianying_draft.build(
                    cfg, project, jy["name"], bool(jy["install"]),
                    p["draft_store"], jy["ratio"], True, bool(jy["force_install"]))
            elif step == "asset-audit":
                try:
                    from workflow.asset_library import audit_project
                    result = audit_project(project)
                except Exception as exc:  # noqa: BLE001
                    # 台账失败不该阻断成片/草稿；verify 的 asset-license 会记没查。
                    print(f"  ⚠ 素材台账失败：{type(exc).__name__}: {exc}")
                    log["steps"].append({"step": step, "status": "error",
                                         "error": f"{type(exc).__name__}: {exc}"})
                    continue
                summary = result.get("summary") or {}
                print(f"  素材台账 {result.get('overall')}：pass {summary.get('pass', 0)} / "
                      f"unchecked {summary.get('unchecked', 0)} / fail {summary.get('fail', 0)}")
                if result.get("overall") == "fail":
                    print("  ✗ 素材授权/文件有红项，verify 会拦；先补齐或替换素材")
                elif result.get("overall") == "unchecked":
                    print("  – 有素材需人工确认；这不是通过")
            elif step == "visual-review":
                if not (p["work"] / "visual-contract.json").is_file():
                    print("  没有 visual-contract.json，跳过视觉审查包")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                import make_visual_review
                result = make_visual_review.build(cfg, project, force=True)
            elif step == "verify":
                result = verify.run_checks(cfg, project)
            elif step == "review-outputs":
                import review_outputs
                result = review_outputs.build(project)
                print(f"  四道门：{ {g['name']: g['status'] for g in result['gates']} }")
                print(f"  报告 → {p['work'] / 'review-report.json'}")
            else:
                if not wants_narration(cfg):
                    print("  没有声明逐句旁白，跳过听审样张")
                    log["steps"].append({"step": step, "status": "skipped"})
                    continue
                from export_voice_review import export_review
                try:
                    result = export_review(cfg, project)
                except (ValueError, subprocess.CalledProcessError) as exc:
                    raise SystemExit(str(exc)) from exc
                print(f"  {result['lines']} 句 → {result['directory']}")
        except (SystemExit, Exception) as e:
            # SystemExit 是预期的配置/渲染错误；其他异常同样要留下现场，
            # 不能只打印 traceback 就丢掉本轮的 QC/日志/接触表。
            print(f"  ✗ {e}")
            log["steps"].append({"step": step, "status": "failed",
                                 "error": f"{type(e).__name__}: {e}"})
            write_json(p["work"] / "pipeline.json", log)
            try:
                from workflow.failure_bundle import capture
                failure = capture(project, step, f"{type(e).__name__}: {e}")
                print(f"  失败现场 → {failure}")
            except Exception as bundle_error:  # 诊断包不能遮蔽原始错误
                print(f"  ⚠ 失败现场未保存：{bundle_error}")
            raise
        dt = time.time() - t0
        log["steps"].append({"step": step, "status": "ok", "seconds": round(dt, 1),
                             "result": result if isinstance(result, dict) else None})
        print(f"  ✓ {dt:.1f}s")

    log["seconds"] = round(time.time() - t_all, 1)
    qc = next((s["result"] for s in log["steps"]
               if s["step"] == "verify" and isinstance(s.get("result"), dict)), None)
    if qc and qc["summary"]["fail"]:
        log["status"] = "failed"
        write_json(p["work"] / "pipeline.json", log)
        raise SystemExit(f"质检未通过：{qc['summary']['fail']} 项失败，"
                         "详见 work/qc-report.json；本轮不算交付完成")
    completed = {s["step"] for s in log["steps"] if s["status"] == "ok"}
    required = {"render", "draft", "verify"}
    if not a.auto and wants_narration(cfg) and cfg["audio"].get("voice_cues"):
        required.add("review")
    if not required <= completed:
        log["status"] = "partial"
        write_json(p["work"] / "pipeline.json", log)
        print(f"\n所选步骤执行完毕，用时 {log['seconds']:.1f}s；"
              "未同时完成要求的成片、草稿、质检与听审样张，不算完整交付")
        return
    review = next((s.get("result") for s in log["steps"] if s["step"] == "review"), None)
    from workflow.delivery import receipt_digest
    from workflow.voice_review import pipeline_review_state, refresh_review
    log["automation_complete"] = True
    log["render_receipt_sha256"] = receipt_digest(project)

    if a.auto:
        log["auto"] = True
        log["status"] = "automated"
        log["human_review"] = "not_required"
        write_json(p["work"] / "human-review.json", {
            "status": "not_required",
            "label": "全自动模式，未要求人工听审",
        })
        write_json(p["work"] / "pipeline.json", log)
        print(f"\n全自动成片完成，用时 {log['seconds']:.1f}s")
        print(f"  成片 → {qc['output'] if qc else '见 work/qc-report.json'}")
        print(f"  剪映草稿 → {project}/draft-store/（已登记进剪映草稿箱）")
        print("  人工听审 → 未执行（--auto）；需要复核时跑 export_voice_review.py")
        if qc and qc.get("summary"):
            sm = qc["summary"]
            print(f"  质检 {sm['pass']} 过 / {sm['fail']} 红 / {sm['unchecked']} 没查")
            if sm["unchecked"]:
                print(f"    ⚠ 有 {sm['unchecked']} 项没查 —— **没查不等于通过**，"
                      f"每项为什么没查写在 work/qc-report.json 的 detail 里")
        return

    human_status = refresh_review(cfg, project)
    log["status"] = pipeline_review_state(human_status["status"])
    if review:
        log["human_review"] = human_status["status"]
    write_json(p["work"] / "pipeline.json", log)
    print(f"\n产物生成完成，用时 {log['seconds']:.1f}s")
    print(f"  成片 → {qc['output'] if qc else '见 work/qc-report.json'}")
    if review:
        print(f"  逐句听审 → {Path(review['directory']) / '听审清单.md'}")
        print(f"  听审状态 → {human_status['label']}")
    print(f"  剪映草稿 → {project}/draft-store/"
          f"（已登记进剪映草稿箱，打开剪映 → 草稿箱即可）")
    if review:
        print("  成片、草稿和逐句听审样张齐全；草稿安装状态见 [draft]")
    else:
        print("  成片和草稿齐全；草稿安装状态见 [draft]")

    # 质检三态在收尾再报一次：跑完流水线的人多半只看最后这几行，
    # 「没查」的项如果只出现在 [verify] 那一段里，就等于没说。
    if qc and qc.get("summary"):
        sm = qc["summary"]
        print(f"  质检 {sm['pass']} 过 / {sm['fail']} 红 / {sm['unchecked']} 没查")
        if sm["fail"]:
            print("    ✗ 有红项，看 work/qc-report.json")
        if sm["unchecked"]:
            print(f"    ⚠ 有 {sm['unchecked']} 项没查 —— **没查不等于通过**，"
                  f"每项为什么没查写在 work/qc-report.json 的 detail 里")


if __name__ == "__main__":
    main()
