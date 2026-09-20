"""Rebuild marketing, scene images, cover, and main video without touching TTS.

This operator tool is intentionally narrow: existing segmented audio and its
durations remain authoritative, while the active configuration supplies the
latest marketing and visual-generation rules.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import pipeline_runner as pr


def rebuild(job_id: str) -> None:
    job_dir = pr.job_dir_for(job_id)
    if pr.is_worker_running(job_id):
        raise RuntimeError(f"{job_id} is still running")

    def log(message: str) -> None:
        pr.append_log(job_dir, message)

    status = pr.load_status(job_id, include_worker=False)
    novel = pr._read_saved_novel(job_dir / "novel.json")
    segments = pr._read_saved_segments(job_dir / "segments.json")
    if novel is None or not segments:
        raise RuntimeError("missing saved novel or segments")

    durations = pr._read_json(job_dir / "durations.json", [])
    if not isinstance(durations, list) or len(durations) != len(segments):
        raise RuntimeError("missing or invalid durations.json")
    durations = [float(value) for value in durations]
    audio_dir = job_dir / "audio"
    audios = [audio_dir / f"seg_{index:05d}.mp3" for index in range(len(segments))]
    missing = [path.name for path in audios if not path.exists()]
    if missing:
        raise RuntimeError(f"missing TTS segments: {', '.join(missing[:5])}")

    pr.write_status(job_dir, job_id=job_id, stage="visual_rebuild", progress=0.20, error="", worker_pid=os.getpid())
    log("== visual-only rebuild: current rules; reuse existing TTS audio and durations ==")
    story_context = pr.stage_story_context(novel, segments, job_dir, on_log=log)
    metadata = pr.stage_metadata(novel, job_dir, story_context, segments=segments, on_log=log)
    if pr.series_animation_enabled_for_job(job_dir):
        metadata = pr.apply_series_presentation(metadata, job_dir, on_log=log)
        pr._write_json(job_dir / "metadata.json", metadata)
    character_analysis = pr.stage_character_analysis(novel, segments, job_dir, on_log=log)
    character_analysis = pr.share_series_character_analysis(job_dir, character_analysis, on_log=log)
    character_analysis = pr.stage_character_references(character_analysis, job_dir, on_log=log)

    pr.write_status(job_dir, job_id=job_id, stage="images", progress=0.50, error="", worker_pid=os.getpid())
    plans = pr.stage_pacing(segments, durations, on_log=log)
    pr._write_json(job_dir / "plans.json", [pr._image_plan_to_dict(plan) for plan in plans])
    images = pr.stage_storyboard_and_image(plans, job_dir, character_analysis, story_context, on_log=log)
    pr._finalize_highlight_timeline(plans, segments, durations, job_dir, on_log=log)
    pr._write_json(job_dir / "plans.json", [pr._image_plan_to_dict(plan) for plan in plans])

    pr.write_status(job_dir, job_id=job_id, stage="cover", progress=0.84, error="", worker_pid=os.getpid())
    cover = pr.stage_cover(novel, segments, job_dir, metadata=metadata, on_log=log)
    pr.write_status(job_dir, job_id=job_id, stage="compose", progress=0.90, error="", worker_pid=os.getpid(), cover=str(cover))
    video = pr.stage_compose(audios, durations, segments, plans, images, job_dir, on_log=log)
    pr.write_status(
        job_dir,
        job_id=job_id,
        stage="completed",
        progress=1.0,
        error="",
        worker_pid=None,
        video=str(video),
        cover=str(cover),
        finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    log(f"visual-only rebuild completed: {video}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id", nargs="+")
    args = parser.parse_args()
    failures = []
    for job_id in args.job_id:
        try:
            rebuild(job_id)
        except Exception as exc:
            job_dir = pr.job_dir_for(job_id)
            pr.write_status(job_dir, job_id=job_id, stage="failed", error=str(exc), worker_pid=None)
            pr.append_log(job_dir, f"visual-only rebuild failed: {exc}")
            failures.append(job_id)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
