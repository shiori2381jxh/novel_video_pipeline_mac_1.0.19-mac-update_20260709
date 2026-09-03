#!/usr/bin/env python3
"""Batch GUI for composing recap videos from existing audio and SRT files.

The tool deliberately reuses the parent novel-video project's configuration,
storyboard, image-generation, subtitle-style, and FFmpeg composition modules,
while bypassing scraping, text cleaning, and TTS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


TOOL_DIR = Path(__file__).resolve().parent
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
SRT_EXTENSIONS = {".srt"}
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | SRT_EXTENSIONS
PAIR_TOKEN_RE = re.compile(r"(?i)(音频|配音|旁白|字幕|audio|voice|narration|subtitle|subtitles|srt)")
SEPARATOR_RE = re.compile(r"[\s._\-—–（）()【】\[\]]+")
TIME_LINE_RE = re.compile(
    r"^\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})(?:\s+.*)?$"
)


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class MediaPair:
    key: str
    audio: Path
    srt: Path


@dataclass
class PairingResult:
    pairs: list[MediaPair]
    unmatched_audio: list[Path]
    unmatched_srt: list[Path]
    ambiguous: list[tuple[str, list[Path], list[Path]]]


def project_root_from_args(value: str = "") -> Path:
    candidates: list[Path] = []
    if value:
        candidates.append(Path(value).expanduser())
    env_value = os.environ.get("NOVEL_VIDEO_PROJECT_ROOT", "").strip()
    if env_value:
        candidates.append(Path(env_value).expanduser())
    marker = TOOL_DIR / "project_path.txt"
    if marker.exists():
        try:
            marked = marker.read_text(encoding="utf-8").splitlines()[0].strip()
            if marked:
                candidates.append(Path(marked).expanduser())
        except Exception:
            pass
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        candidates.extend(sorted(desktop.glob("novel_video_pipeline_mac_*"), reverse=True))
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "app" / "pipeline_runner.py").is_file() and (resolved / "app" / "config.py").is_file():
            return resolved
    raise RuntimeError("找不到原小说视频项目。请确认 project_path.txt 指向原项目文件夹。")


def load_pipeline_modules(project_root: Path) -> SimpleNamespace:
    root_text = str(project_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from app.config import config
    from app.pipeline_runner import (
        _audio_duration,
        _finalize_highlight_timeline,
        append_log,
        safe_job_name,
        stage_character_analysis,
        stage_character_references,
        stage_pacing,
        stage_story_context,
        stage_storyboard_and_image,
    )
    from app.scrapers.base import Novel, NovelChapter
    from app.stages.stage2_clean import Segment
    from app.stages.stage6_compose import build_ass, build_video

    return SimpleNamespace(
        config=config,
        audio_duration=_audio_duration,
        finalize_highlight_timeline=_finalize_highlight_timeline,
        append_log=append_log,
        safe_job_name=safe_job_name,
        stage_character_analysis=stage_character_analysis,
        stage_character_references=stage_character_references,
        stage_pacing=stage_pacing,
        stage_story_context=stage_story_context,
        stage_storyboard_and_image=stage_storyboard_and_image,
        Novel=Novel,
        NovelChapter=NovelChapter,
        Segment=Segment,
        build_ass=build_ass,
        build_video=build_video,
    )


def _read_text_with_fallback(path: Path) -> str:
    data = path.read_bytes()
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "shift_jis", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"无法识别字幕编码: {path.name}: {last_error}")


def _timestamp(parts: tuple[str, str, str, str]) -> float:
    hour, minute, second, millis = (int(value) for value in parts)
    fraction = millis / (10 ** len(parts[3]))
    return hour * 3600 + minute * 60 + second + fraction


def _clean_subtitle_text(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\\[^}]+\}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_srt(path: Path) -> list[Cue]:
    raw = _read_text_with_fallback(path).replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    cues: list[Cue] = []
    i = 0
    while i < len(lines):
        match = TIME_LINE_RE.match(lines[i])
        if not match:
            i += 1
            continue
        start = _timestamp(match.groups()[0:4])
        end = _timestamp(match.groups()[4:8])
        i += 1
        text_lines: list[str] = []
        while i < len(lines):
            if TIME_LINE_RE.match(lines[i]):
                break
            if not lines[i].strip():
                lookahead = i + 1
                while lookahead < len(lines) and not lines[lookahead].strip():
                    lookahead += 1
                if lookahead < len(lines) and (
                    TIME_LINE_RE.match(lines[lookahead])
                    or (lines[lookahead].strip().isdigit() and lookahead + 1 < len(lines) and TIME_LINE_RE.match(lines[lookahead + 1]))
                ):
                    i = lookahead
                    if i < len(lines) and lines[i].strip().isdigit():
                        i += 1
                    break
            text_lines.append(lines[i])
            i += 1
        text = _clean_subtitle_text(text_lines)
        if text and end > start:
            cues.append(Cue(start=max(0.0, start), end=end, text=text))
    cues.sort(key=lambda cue: (cue.start, cue.end))
    if not cues:
        raise ValueError(f"没有读到有效字幕时间轴: {path.name}")
    return cues


def pairing_key(path: Path) -> str:
    value = PAIR_TOKEN_RE.sub("", path.stem.casefold())
    value = SEPARATOR_RE.sub("", value)
    return value or SEPARATOR_RE.sub("", path.stem.casefold()) or path.stem.casefold()


def display_title(audio: Path, srt: Path) -> str:
    for stem in (audio.stem, srt.stem):
        cleaned = PAIR_TOKEN_RE.sub("", stem)
        cleaned = re.sub(r"[\s._\-—–]+", " ", cleaned).strip()
        if cleaned:
            return cleaned
    return audio.stem or "导入视频"


def pair_media_files(paths: list[Path]) -> PairingResult:
    unique = sorted({path.resolve() for path in paths if path.suffix.casefold() in SUPPORTED_EXTENSIONS})
    audio_groups: dict[str, list[Path]] = {}
    srt_groups: dict[str, list[Path]] = {}
    for path in unique:
        target = audio_groups if path.suffix.casefold() in AUDIO_EXTENSIONS else srt_groups
        target.setdefault(pairing_key(path), []).append(path)

    pairs: list[MediaPair] = []
    unmatched_audio: list[Path] = []
    unmatched_srt: list[Path] = []
    ambiguous: list[tuple[str, list[Path], list[Path]]] = []
    for key in sorted(set(audio_groups) | set(srt_groups)):
        audios = audio_groups.get(key, [])
        srts = srt_groups.get(key, [])
        if len(audios) == 1 and len(srts) == 1:
            pairs.append(MediaPair(key=key, audio=audios[0], srt=srts[0]))
        elif len(audios) > 1 or len(srts) > 1:
            ambiguous.append((key, audios, srts))
        else:
            unmatched_audio.extend(audios)
            unmatched_srt.extend(srts)

    # A single pair is safe even if the two filenames do not share a stem.
    if not ambiguous and len(unmatched_audio) == 1 and len(unmatched_srt) == 1:
        audio = unmatched_audio.pop()
        srt = unmatched_srt.pop()
        pairs.append(MediaPair(key=pairing_key(audio), audio=audio, srt=srt))

    pairs.sort(key=lambda item: (item.audio.name.casefold(), item.srt.name.casefold()))
    return PairingResult(pairs, unmatched_audio, unmatched_srt, ambiguous)


def allocation_durations(cues: list[Cue], audio_duration: float) -> list[float]:
    """Allocate the full audio timeline to SRT text segments for image pacing."""
    if not cues or audio_duration <= 0:
        return []
    starts = [0.0]
    previous = 0.0
    for cue in cues[1:]:
        current = max(previous, min(float(audio_duration), max(0.0, cue.start)))
        starts.append(current)
        previous = current
    boundaries = starts + [float(audio_duration)]
    raw = [max(0.001, boundaries[i + 1] - boundaries[i]) for i in range(len(cues))]
    minimum = min(0.05, audio_duration / max(1, len(cues) * 2))
    values = [max(minimum, value) for value in raw]
    total = sum(values)
    if total <= 0:
        return [audio_duration / len(cues)] * len(cues)
    scaled = [value * audio_duration / total for value in values]
    scaled[-1] += audio_duration - sum(scaled)
    return scaled


def _format_srt_time(seconds: float) -> str:
    millis_total = max(0, int(round(seconds * 1000)))
    hour, remainder = divmod(millis_total, 3_600_000)
    minute, remainder = divmod(remainder, 60_000)
    second, millis = divmod(remainder, 1000)
    return f"{hour:02d}:{minute:02d}:{second:02d},{millis:03d}"


def write_normalized_srt(cues: list[Cue], path: Path) -> None:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{_format_srt_time(cue.start)} --> {_format_srt_time(cue.end)}\n{cue.text}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def source_signature(pair: MediaPair) -> dict:
    def signature(path: Path) -> dict:
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    return {"audio": signature(pair.audio), "srt": signature(pair.srt)}


def choose_job_dir(output_root: Path, title: str, signature: dict, safe_name: Callable[[str], str]) -> Path:
    base = safe_name(title) or "导入视频"
    candidate = output_root / base
    sequence = 1
    while candidate.exists():
        manifest = candidate / "source_manifest.json"
        if manifest.exists():
            try:
                if json.loads(manifest.read_text(encoding="utf-8")).get("source") == signature:
                    return candidate
            except Exception:
                pass
        sequence += 1
        candidate = output_root / f"{base}_{sequence}"
    return candidate


def normalize_plan_durations(plans: list[object], audio_duration: float) -> None:
    if not plans:
        return
    values = [max(0.05, float(getattr(plan, "duration", 0.0) or 0.0)) for plan in plans]
    total = sum(values)
    scale = audio_duration / total if total > 0 else 1.0
    for plan, value in zip(plans, values):
        plan.duration = value * scale
    plans[-1].duration += audio_duration - sum(float(plan.duration) for plan in plans)


class BatchComposer:
    def __init__(self, modules: SimpleNamespace, output_root: Path, logger: Callable[[str], None], stop_event: threading.Event):
        self.m = modules
        self.output_root = output_root
        self.log = logger
        self.stop_event = stop_event

    def _job_log(self, job_dir: Path, message: str) -> None:
        clean = str(message).rstrip()
        if not clean:
            return
        self.log(clean)
        self.m.append_log(job_dir, clean)

    def run_pair(self, pair: MediaPair, index: int, total: int) -> Path:
        title = display_title(pair.audio, pair.srt)
        signature = source_signature(pair)
        job_dir = choose_job_dir(self.output_root, title, signature, self.m.safe_job_name)
        job_dir.mkdir(parents=True, exist_ok=True)
        log = lambda message: self._job_log(job_dir, message)
        write_json(job_dir / "source_manifest.json", {"schema_version": 1, "source": signature})
        write_json(
            job_dir / "status.json",
            {"state": "running", "title": title, "output_basename": title, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
        )
        log(f"\n===== [{index}/{total}] {title} =====")
        log(f"音频: {pair.audio.name}")
        log(f"字幕: {pair.srt.name}")

        try:
            cues = parse_srt(pair.srt)
            audio_duration = float(self.m.audio_duration(pair.audio))
            if audio_duration <= 0.05:
                raise ValueError(f"无法读取音频时长: {pair.audio.name}")
            active_cues = [cue for cue in cues if cue.start < audio_duration]
            if not active_cues:
                raise ValueError("所有字幕都位于音频结束时间之后")
            if cues[-1].end > audio_duration + 0.5:
                log(f"警告: SRT 结束于 {cues[-1].end:.2f}s，音频为 {audio_duration:.2f}s；超出部分会随音频结束截断。")
            elif audio_duration > cues[-1].end + 3.0:
                log(f"提示: 音频比最后一条字幕长 {audio_duration - cues[-1].end:.2f}s，最后画面会延续到音频结束。")
            log(f"读取完成: 音频 {audio_duration:.2f}s，字幕 {len(cues)} 条。")

            source_audio = job_dir / f"source_audio{pair.audio.suffix.casefold()}"
            source_srt_original = job_dir / "subtitle_original.srt"
            if pair.audio.resolve() != source_audio.resolve():
                shutil.copy2(pair.audio, source_audio)
            if pair.srt.resolve() != source_srt_original.resolve():
                shutil.copy2(pair.srt, source_srt_original)
            write_normalized_srt(cues, job_dir / "subtitle.srt")

            durations = allocation_durations(active_cues, audio_duration)
            segments = [self.m.Segment(index=i, text=cue.text) for i, cue in enumerate(active_cues)]
            write_json(
                job_dir / "segments.json",
                [
                    {"i": segment.index, "text": segment.text, "srt_start": cue.start, "srt_end": cue.end, "image_timeline_duration": durations[i]}
                    for i, (segment, cue) in enumerate(zip(segments, active_cues))
                ],
            )
            write_json(job_dir / "durations.json", durations)
            full_text = "\n\n".join(cue.text for cue in active_cues)
            novel = self.m.Novel(
                site="srt_audio_import",
                novel_id=hashlib.sha1(str(pair.srt.resolve()).encode("utf-8")).hexdigest()[:16],
                title=title,
                description="从已有音频和 SRT 导入",
                chapters=[self.m.NovelChapter(index=0, title=title, text=full_text)],
            )
            write_json(
                job_dir / "novel.json",
                {"site": novel.site, "id": novel.novel_id, "title": title, "chapters": [{"index": 0, "title": title, "text": full_text}]},
            )

            if self.stop_event.is_set():
                raise InterruptedError("用户要求停止")
            log("按 SRT 时间轴计算画面节奏……")
            plans = self.m.stage_pacing(segments, durations, on_log=log)
            if not plans:
                raise RuntimeError("未生成任何画面计划")

            if self.stop_event.is_set():
                raise InterruptedError("用户要求停止")
            story_context = self.m.stage_story_context(novel, segments, job_dir, on_log=log)
            character_analysis = self.m.stage_character_analysis(novel, segments, job_dir, on_log=log)
            character_analysis = self.m.stage_character_references(character_analysis, job_dir, on_log=log)

            if self.stop_event.is_set():
                raise InterruptedError("用户要求停止")
            images = self.m.stage_storyboard_and_image(
                plans,
                job_dir,
                character_analysis=character_analysis,
                story_context=story_context,
                on_log=log,
                on_prog=lambda progress: log(f"出图进度 {int(progress * 100)}%") if progress in {0.0, 1.0} else None,
            )
            self.m.finalize_highlight_timeline(plans, segments, durations, job_dir, on_log=log)
            normalize_plan_durations(plans, audio_duration)
            write_json(
                job_dir / "plans.json",
                [
                    {"image_index": plan.image_index, "duration": plan.duration, "segment_indexes": [s.index for s in plan.segments], "text": plan.text}
                    for plan in plans
                ],
            )

            if self.stop_event.is_set():
                raise InterruptedError("用户要求停止")
            exact_subtitles = [(cue.start, cue.end, cue.text) for cue in cues]
            ass_path = job_dir / "subtitle.ass"
            config = self.m.config
            self.m.build_ass(
                exact_subtitles,
                ass_path,
                font=config.video_subtitle_font,
                size=config.video_subtitle_size,
                video_w=config.video_width,
                video_h=config.video_height,
                position=config.get("video_subtitle_position", "下边"),
                primary_color=config.get("video_subtitle_color", "#FFFFFF"),
                outline_color=config.get("video_subtitle_outline_color", "#000000"),
                back_color=config.get("video_subtitle_back_color", "#000000"),
                outline=float(config.get("video_subtitle_outline", 4.0) or 4.0),
                shadow=float(config.get("video_subtitle_shadow", 1.0) or 1.0),
                margin_v=int(config.get("video_subtitle_margin_v", 60) or 60),
                margin_lr=int(config.get("video_subtitle_margin_lr", 56) or 56),
                spacing=float(config.get("video_subtitle_spacing", 0.0) or 0.0),
                bold=bool(config.get("video_subtitle_bold", False)),
                italic=bool(config.get("video_subtitle_italic", False)),
                chars_per_line=int(config.get("video_subtitle_chars_per_line", 24) or 24),
                max_lines=int(config.get("video_subtitle_max_lines", 2) or 2),
            )
            bgm_text = str(config.video_bgm_path or "").strip()
            bgm = Path(bgm_text).expanduser() if bgm_text else None
            if bgm and not bgm.exists():
                log(f"警告: 找不到背景音乐，已跳过: {bgm}")
                bgm = None
            output_name = self.m.safe_job_name(title) + ".mp4"
            output = job_dir / output_name
            temporary = job_dir / (self.m.safe_job_name(title) + ".tmp.mp4")
            temporary.unlink(missing_ok=True)
            log("开始合成视频，视频总长以导入音频为准……")
            self.m.build_video(
                images=images,
                image_durations=[float(plan.duration) for plan in plans],
                audio_path=source_audio,
                out_path=temporary,
                on_log=log,
                width=config.video_width,
                height=config.video_height,
                fps=config.video_fps,
                ken_burns=bool(config.ken_burns),
                subtitle_ass=ass_path,
                bgm_path=bgm,
                bgm_volume=config.video_bgm_volume,
                long_mode=config.video_long_mode,
                cleanup_temp=config.video_cleanup_temp,
                motion=str(config.video_motion or "none"),
                motion_curve=str(config.get("video_motion_curve", "ease") or "ease"),
                motion_cycle_seconds=float(config.get("video_motion_cycle_seconds", 18.0) or 18.0),
                transition=config.video_transition,
                transition_duration=float(config.video_transition_duration or 0.4),
                video_encoder=str(config.get("video_encoder", "libx264") or "libx264"),
                video_encoder_preset=str(config.get("video_encoder_preset", "veryfast") or "veryfast"),
                video_encoder_quality=int(config.get("video_encoder_quality", 20) or 20),
            )
            produced_duration = float(self.m.audio_duration(temporary))
            if produced_duration <= 0.05:
                raise RuntimeError("合成结果时长为零")
            if audio_duration > 10 and produced_duration < audio_duration * 0.95:
                raise RuntimeError(f"合成视频明显短于音频: 视频 {produced_duration:.2f}s / 音频 {audio_duration:.2f}s")
            temporary.replace(output)
            write_json(
                job_dir / "status.json",
                {
                    "state": "completed",
                    "title": title,
                    "output_basename": title,
                    "video": str(output),
                    "audio_duration": audio_duration,
                    "video_duration": produced_duration,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            log(f"完成: {output}")
            return output
        except Exception as exc:
            state = "stopped" if isinstance(exc, InterruptedError) else "failed"
            write_json(
                job_dir / "status.json",
                {"state": state, "title": title, "error": str(exc), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
            )
            raise


class App:
    def __init__(self, root: tk.Tk, project_root: Path):
        self.root = root
        self.project_root = project_root
        self.modules = load_pipeline_modules(project_root)
        self.files: set[Path] = set()
        self.pairing = PairingResult([], [], [], [])
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self.running = False

        root.title("音频 + SRT 视频合成工具")
        root.geometry("1040x760")
        root.minsize(900, 650)
        self._build()
        self._refresh_pairs()
        self.root.after(120, self._poll_log)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        intro = ttk.LabelFrame(outer, text="导入已有音频和字幕", padding=10)
        intro.pack(fill=tk.X)
        ttk.Label(
            intro,
            text="支持一次导入多组文件；同名文件会自动配对，例如：作品A.mp3 + 作品A.srt。程序跳过配音，保留 SRT 原时间轴并按音频总长合成。",
            wraplength=970,
        ).pack(anchor=tk.W)
        buttons = ttk.Frame(intro)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="选择音频和 SRT", command=self._choose_files).pack(side=tk.LEFT)
        ttk.Button(buttons, text="选择包含文件的文件夹", command=self._choose_input_folder).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="清空列表", command=self._clear_files).pack(side=tk.LEFT)

        settings = ttk.Frame(intro)
        settings.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(settings, text="沿用配置").pack(side=tk.LEFT)
        profiles = self.modules.config.list_profiles()
        active_profile = str(self.modules.config.get("active_profile", "配置1") or "配置1")
        self.profile_var = tk.StringVar(value=active_profile if active_profile in profiles else profiles[0])
        self.profile_combo = ttk.Combobox(settings, state="readonly", width=18, values=profiles, textvariable=self.profile_var)
        self.profile_combo.pack(side=tk.LEFT, padx=(6, 18))
        ttk.Label(settings, text="输出位置").pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value=str(TOOL_DIR / "输出"))
        ttk.Entry(settings, textvariable=self.output_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(settings, text="更改", command=self._choose_output).pack(side=tk.LEFT)
        ttk.Button(settings, text="打开输出", command=self._open_output).pack(side=tk.LEFT, padx=(6, 0))

        pair_box = ttk.LabelFrame(outer, text="自动配对结果", padding=8)
        pair_box.pack(fill=tk.BOTH, expand=True, pady=10)
        columns = ("status", "audio", "srt")
        self.tree = ttk.Treeview(pair_box, columns=columns, show="headings", height=10)
        self.tree.heading("status", text="状态")
        self.tree.heading("audio", text="音频")
        self.tree.heading("srt", text="SRT 字幕")
        self.tree.column("status", width=130, anchor=tk.W)
        self.tree.column("audio", width=410, anchor=tk.W)
        self.tree.column("srt", width=410, anchor=tk.W)
        scrollbar = ttk.Scrollbar(pair_box, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X)
        self.start_button = ttk.Button(actions, text="开始批量生成视频", command=self._start)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(actions, text="完成当前步骤后停止", command=self._stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=6)
        self.summary_var = tk.StringVar(value="等待导入文件")
        ttk.Label(actions, textvariable=self.summary_var).pack(side=tk.LEFT, padx=12)

        log_box = ttk.LabelFrame(outer, text="运行记录", padding=6)
        log_box.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.log_text = scrolledtext.ScrolledText(log_box, height=12, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _choose_files(self) -> None:
        selected = filedialog.askopenfilenames(
            title="选择音频和 SRT（可以多选）",
            filetypes=[
                ("音频和字幕", ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.flac", "*.ogg", "*.opus", "*.srt")),
                ("所有文件", "*.*"),
            ],
        )
        self._add_paths([Path(value) for value in selected])

    def _choose_input_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择包含音频和 SRT 的文件夹")
        if not selected:
            return
        folder = Path(selected)
        self._add_paths([path for path in folder.iterdir() if path.is_file()])

    def _add_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS:
                self.files.add(path.resolve())
        self._refresh_pairs()

    def _clear_files(self) -> None:
        if self.running:
            return
        self.files.clear()
        self._refresh_pairs()

    def _refresh_pairs(self) -> None:
        self.pairing = pair_media_files(list(self.files))
        self.tree.delete(*self.tree.get_children())
        for item in self.pairing.pairs:
            self.tree.insert("", tk.END, values=("已配对", item.audio.name, item.srt.name))
        for path in self.pairing.unmatched_audio:
            self.tree.insert("", tk.END, values=("缺少同名 SRT", path.name, ""))
        for path in self.pairing.unmatched_srt:
            self.tree.insert("", tk.END, values=("缺少同名音频", "", path.name))
        for _key, audios, srts in self.pairing.ambiguous:
            self.tree.insert(
                "",
                tk.END,
                values=("文件名重复，无法配对", ", ".join(path.name for path in audios), ", ".join(path.name for path in srts)),
            )
        self.summary_var.set(
            f"已配对 {len(self.pairing.pairs)} 组；未配对 {len(self.pairing.unmatched_audio) + len(self.pairing.unmatched_srt)} 个"
        )

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="选择输出文件夹", initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)

    def _open_output(self) -> None:
        output = Path(self.output_var.get()).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(output)])
            elif os.name == "nt":
                os.startfile(str(output))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(output)])
        except Exception as exc:
            messagebox.showerror("无法打开", str(exc))

    def _append_log(self, message: str) -> None:
        self.log_queue.put(str(message))

    def _poll_log(self) -> None:
        changed = False
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, message.rstrip() + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
            changed = True
        if changed:
            self.root.update_idletasks()
        self.root.after(120, self._poll_log)

    def _start(self) -> None:
        if self.running:
            return
        if not self.pairing.pairs:
            messagebox.showwarning("没有可处理文件", "请先选择至少一组音频和 SRT。")
            return
        if self.pairing.unmatched_audio or self.pairing.unmatched_srt or self.pairing.ambiguous:
            proceed = messagebox.askyesno("存在未配对文件", "未配对或重名的文件将被跳过，只处理已配对项目。继续吗？")
            if not proceed:
                return
        output = Path(self.output_var.get()).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("输出位置不可用", str(exc))
            return
        self.stop_event.clear()
        self.running = True
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.profile_combo.configure(state=tk.DISABLED)
        pairs = list(self.pairing.pairs)
        profile = self.profile_var.get()
        threading.Thread(target=self._worker, args=(pairs, output, profile), daemon=True).start()

    def _stop(self) -> None:
        self.stop_event.set()
        self.stop_button.configure(state=tk.DISABLED)
        self._append_log("已收到停止要求；当前正在调用的出图或合成步骤结束后停止。")

    def _worker(self, pairs: list[MediaPair], output: Path, profile: str) -> None:
        completed = 0
        failed = 0
        try:
            self.modules.config.load_profile(profile)
            composer = BatchComposer(self.modules, output, self._append_log, self.stop_event)
            self._append_log(f"使用原项目配置：{profile}")
            self._append_log(f"输出目录：{output}")
            for index, pair in enumerate(pairs, start=1):
                if self.stop_event.is_set():
                    break
                try:
                    composer.run_pair(pair, index, len(pairs))
                    completed += 1
                except InterruptedError:
                    self._append_log("任务已停止。")
                    break
                except Exception as exc:
                    failed += 1
                    self._append_log(f"失败: {pair.audio.name} + {pair.srt.name}: {exc}")
                    self._append_log(traceback.format_exc())
            if self.stop_event.is_set():
                final = f"已停止：完成 {completed} 组，失败 {failed} 组。"
            else:
                final = f"批量处理结束：完成 {completed} 组，失败 {failed} 组。"
            self._append_log(final)
            self.root.after(0, lambda: messagebox.showinfo("处理结束", final))
        except Exception as exc:
            final = f"批量任务无法继续：{exc}"
            self._append_log(final)
            self._append_log(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror("处理失败", final))
        finally:
            self.root.after(0, self._finish_worker)

    def _finish_worker(self) -> None:
        self.running = False
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.profile_combo.configure(state="readonly")
        self.summary_var.set("处理结束，可打开输出文件夹查看结果")


def run_self_test() -> None:
    sample = """1
00:00:00,500 --> 00:00:02,000
第一句字幕

2
00:00:03.250 --> 00:00:05.000
<i>第二句</i> 字幕
"""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        srt = root / "作品_字幕.srt"
        audio = root / "作品_音频.mp3"
        srt.write_text(sample, encoding="utf-8")
        audio.write_bytes(b"test")
        cues = parse_srt(srt)
        assert len(cues) == 2
        assert cues[0].start == 0.5 and cues[1].start == 3.25
        assert cues[1].text == "第二句 字幕"
        result = pair_media_files([srt, audio])
        assert len(result.pairs) == 1
        durations = allocation_durations(cues, 7.0)
        assert len(durations) == 2 and abs(sum(durations) - 7.0) < 1e-6
    print("self-test OK")


def run_integration_test(project_root: Path) -> None:
    """Run an API-free placeholder-image + FFmpeg end-to-end smoke test."""
    modules = load_pipeline_modules(project_root)
    original = modules.config.as_dict()
    try:
        modules.config.update(
            {
                "ai_api_enabled": False,
                "llm_provider": "openai",
                "llm_api_key": "",
                "image_provider": "placeholder",
                "character_analysis_enabled": False,
                "character_reference_enabled": False,
                "storyboard_highlight_enabled": False,
                "pacing_mode": "by_duration",
                "pacing_seconds_per_image": 1.5,
                "image_width": 320,
                "image_height": 568,
                "video_width": 320,
                "video_height": 568,
                "video_fps": 10,
                "video_long_mode": True,
                "ken_burns": False,
                "video_motion": "none",
                "video_transition": "none",
                "video_bgm_path": "",
                "video_encoder": "libx264",
                "video_encoder_preset": "ultrafast",
                "video_encoder_quality": 28,
                "video_subtitle_font": "Arial",
                "video_subtitle_size": 24,
                "max_parallel_images": 1,
                "max_parallel_video_clips": 1,
            }
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "离线检查_音频.wav"
            srt = root / "离线检查_字幕.srt"
            rate = 16_000
            seconds = 4.0
            with wave.open(str(audio), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                frames = bytearray()
                for index in range(int(rate * seconds)):
                    sample = int(1600 * math.sin(2 * math.pi * 220 * index / rate))
                    frames.extend(struct.pack("<h", sample))
                handle.writeframes(bytes(frames))
            cues = [Cue(0.4, 1.8, "第一条离线测试字幕"), Cue(2.2, 3.7, "第二条离线测试字幕")]
            write_normalized_srt(cues, srt)
            pair = MediaPair(pairing_key(audio), audio, srt)
            output_root = root / "output"
            output = BatchComposer(modules, output_root, print, threading.Event()).run_pair(pair, 1, 1)
            if not output.exists() or output.stat().st_size < 1000:
                raise RuntimeError("integration test did not create a valid MP4")
            produced = modules.audio_duration(output)
            if produced < 3.8:
                raise RuntimeError(f"integration test MP4 is too short: {produced:.2f}s")
            print(f"integration-test OK: {produced:.2f}s")
    finally:
        modules.config.update(original)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import audio + SRT and compose videos using the novel video pipeline modules")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check-project", action="store_true")
    parser.add_argument("--integration-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    try:
        project_root = project_root_from_args(args.project_root)
        if args.integration_test:
            run_integration_test(project_root)
            return 0
        if args.check_project:
            modules = load_pipeline_modules(project_root)
            print(f"project OK: {project_root}")
            print(f"active profile: {modules.config.get('active_profile', '配置1')}")
            return 0
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("无法启动", str(exc))
            root.destroy()
        except Exception:
            print(str(exc), file=sys.stderr)
        return 2
    root = tk.Tk()
    App(root, project_root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
