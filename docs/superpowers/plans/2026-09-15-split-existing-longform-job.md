# Split Existing Longform Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely split completed job `001` into three stopped child jobs that retain existing TTS audio but generate new images and compose new MP4 files when resumed.

**Architecture:** Add a narrowly scoped reusable splitter that validates a completed job's aligned segments, audio durations and subtitles; it creates a child directory per approved SRT cue range. It slices the already concatenated narration at exact cue times and writes a locked imported-audio timing manifest, so normal resume uses the child MP3/timings without TTS. Each child has rebased text, audio, timing and subtitles but no image or compose artifacts.

**Tech Stack:** Python 3, existing job JSON/SRT artifacts, pytest, ffmpeg-compatible MP3 assets.

## Global Constraints

- Preserve the parent job directory and its status unchanged.
- Do not regenerate or delete TTS audio; child narration is extracted from the completed parent audio at exact SRT cue time.
- Use exact SRT end-cue cuts 1266 and 2512; all child durations must remain within 1–3 hours.
- Omit parent images, plans and final MP4 from child jobs.
- Create `001-1`, `001-2`, and `001-3` as stopped jobs; do not start workers.

---

### Task 1: Add an artifact splitter with validation

**Files:**
- Modify: `app/pipeline_runner.py`
- Test: `tests/test_existing_job_split.py`

**Interfaces:**
- Produces: `split_completed_job_at_srt_cues(parent_job_id: str, child_job_ids: list[str], cut_cue_indexes: list[int]) -> list[dict]`.
- Consumes: parent `segments.json`, `durations.json`, `audio/seg_*.mp3`, `subtitle.srt`, `status.json`, and source snapshots.

- [ ] **Step 1: Write the failing test**

```python
def test_split_completed_job_rebases_audio_and_subtitles_without_images(tmp_path, monkeypatch):
    parent = _make_completed_job(tmp_path, cue_count=6, durations=[10.0] * 6)
    monkeypatch.setattr(pipeline_runner, "job_dir_for", lambda job_id: tmp_path / job_id)

    children = pipeline_runner.split_completed_job_at_srt_cues(
        "parent", ["part-1", "part-2", "part-3"], [2, 4]
    )

    assert [item["audio_segment_count"] for item in children] == [2, 2, 2]
    assert (tmp_path / "part-1" / "audio" / "seg_00000.mp3").exists()
    assert not (tmp_path / "part-1" / "images").exists()
    assert pipeline_runner._read_json(tmp_path / "part-1" / "status.json", {})["stage"] == "stopped"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_existing_job_split.py -v`

Expected: FAIL because the splitter does not exist.

- [ ] **Step 3: Implement the minimal splitter**

```python
def split_completed_job_at_srt_cues(parent_job_id, child_job_ids, cut_cue_indexes):
    # Validate aligned source artifacts before creating children.
    # Partition at cue boundaries, rebase cue timestamps to zero,
    # extract child narration, lock the imported-audio timings, and write stopped statuses.
    # Do not copy images, plans, compose manifest, or final video.
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_existing_job_split.py -v`

Expected: PASS.

### Task 2: Preserve locked audio on a resumed child job

**Files:**
- Modify: `app/pipeline_runner.py` only if existing TTS cache handling cannot recognize copied child artifacts.
- Test: `tests/test_existing_job_split.py`

**Interfaces:**
- Consumes: stopped child job from Task 1.
- Produces: a resumed child job that leaves locked audio/timings untouched while proceeding to fresh image generation.

- [ ] **Step 1: Write the failing behavior test**

```python
def test_resumed_split_child_keeps_locked_audio_and_requires_new_images(monkeypatch, tmp_path):
    child = _make_split_child(tmp_path)
    monkeypatch.setattr(pipeline_runner, "job_dir_for", lambda _job_id: child)

    imported = pipeline_runner._job_imported_audio(child)

    assert imported is not None
    assert not (child / "images").exists()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_existing_job_split.py -k resumed_split_child -v`

Expected: FAIL if the child does not contain a locked imported-audio manifest.

- [ ] **Step 3: Preserve the locked subtitle timing during resume**

```python
# If an imported-audio manifest declares `timing_mode: subtitle_locked`,
# stage_tts returns the persisted durations instead of replacing them with
# text-weight estimates.  The SRT file is rebuilt only from those timings.
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_existing_job_split.py -v`

Expected: PASS.

### Task 3: Execute and verify the approved 001 split

**Files:**
- Create: `data/jobs/001-1/*`, `data/jobs/001-2/*`, `data/jobs/001-3/*`
- Verify: `data/jobs/生日那天,发现自己被圈养十八年 - 不吃魔芋_001/*`

**Interfaces:**
- Consumes: parent task and Task 1's splitter.
- Produces: three stopped child jobs for the approved cue cuts 1266 and 2512.

- [ ] **Step 1: Run the splitter in dry-run validation mode**

Run: `python -c "from app.pipeline_runner import split_completed_job_at_srt_cues; ..."`

Expected: report cue ranges and durations approximately 2.00, 2.00, and 1.92 hours without writing files.

- [ ] **Step 2: Create the three child jobs**

Run: `python -c "from app.pipeline_runner import split_completed_job_at_srt_cues; ..."`

Expected: create `001-1`, `001-2`, and `001-3` with stopped statuses.

- [ ] **Step 3: Verify parent preservation and child alignment**

Run: `python -m pytest tests/test_existing_job_split.py -v` and a read-only artifact report.

Expected: parent status remains completed; child durations sum to the parent; each child has matching text/audio/durations/SRT and no images or final MP4.
