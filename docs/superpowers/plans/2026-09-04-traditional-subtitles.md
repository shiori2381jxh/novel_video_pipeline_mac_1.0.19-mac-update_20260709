# 繁体字幕开关 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in setting that converts only the main video's ASS and SRT subtitle text from simplified to traditional Chinese.

**Architecture:** `opencc-python-reimplemented` supplies local, dictionary-backed simplified-to-traditional conversion. `stage6_compose` accepts an explicit conversion flag and applies it before its shared subtitle event splitter, so ASS and SRT use the identical converted source. The pipeline forwards the persisted GUI setting only for main-video composition paths.

**Tech Stack:** Python 3, tkinter, pytest, OpenCC (`s2twp` conversion profile).

## Global Constraints

- The new setting is named `video_subtitle_traditional` and defaults to `False`.
- Only main-video `subtitle.ass` and `subtitle.srt` text changes when enabled.
- Source text, TTS, segment files, storyboards, images, titles, upload metadata, and Short subtitles remain unchanged.
- Conversion is local and must preserve non-Chinese characters.
- Existing subtitle output must remain byte-for-byte behaviorally unchanged while the flag is disabled.

---

### Task 1: Add and test subtitle conversion in the composition layer

**Files:**
- Modify: `requirements.txt`
- Modify: `app/stages/stage6_compose.py:build_ass`, `app/stages/stage6_compose.py:build_srt`, `app/stages/stage6_compose.py:_split_subtitle_events`
- Create: `tests/test_stage6_compose_subtitles.py`

**Interfaces:**
- Consumes: `list[tuple[float, float, str]]` subtitle events.
- Produces: `build_ass(..., traditional: bool = False) -> None` and `build_srt(..., traditional: bool = False) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
from app.stages.stage6_compose import build_ass, build_srt


def test_build_ass_converts_only_subtitle_text_when_traditional_enabled(tmp_path):
    output = tmp_path / "subtitle.ass"
    build_ass([(0.0, 1.0, "后发现台风，ABC 123")], output, traditional=True)
    assert "後發現颱風，ABC 123" in output.read_text(encoding="utf-8")


def test_build_srt_keeps_simplified_text_when_traditional_disabled(tmp_path):
    output = tmp_path / "subtitle.srt"
    build_srt([(0.0, 1.0, "后发现台风，ABC 123")], output)
    assert "后发现台风，ABC 123" in output.read_text(encoding="utf-8")


def test_build_srt_converts_subtitle_text_when_traditional_enabled(tmp_path):
    output = tmp_path / "subtitle.srt"
    build_srt([(0.0, 1.0, "后发现台风，ABC 123")], output, traditional=True)
    assert "後發現颱風，ABC 123" in output.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_stage6_compose_subtitles.py -v`

Expected: FAIL because `build_ass` and `build_srt` do not accept `traditional`.

- [ ] **Step 3: Add the local conversion dependency and minimal implementation**

Add `opencc-python-reimplemented>=0.1.7` to `requirements.txt`. In `stage6_compose.py`, lazily construct `OpenCC("s2twp")` in a module-private helper and pass `traditional` through `_split_subtitle_events`. Convert each normalized subtitle event only when `traditional` is true. Preserve the current default (`False`) and keep timings and event splitting unchanged.

```python
def _convert_subtitle_text(text: str, traditional: bool) -> str:
    if not traditional:
        return text
    return _subtitle_opencc().convert(text)
```

- [ ] **Step 4: Run the subtitle tests to verify they pass**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_stage6_compose_subtitles.py -v`

Expected: PASS; the enabled cases contain `後發現颱風` and the disabled case contains `后发现台风`.

- [ ] **Step 5: Commit**

This workspace has no `.git` directory. Record the modified files and test output in the final handoff instead of attempting a commit.

### Task 2: Persist and expose the main-video setting, then forward it into both main composition paths

**Files:**
- Modify: `app/config.py:DEFAULTS` video subtitle settings
- Modify: `app/gui.py` subtitle controls and `_collect_ui_to_config` boolean keys
- Modify: `app/pipeline_runner.py:_stage_compose_manifest_impl` main subtitle calls
- Modify: `tests/test_stage6_compose_subtitles.py`

**Interfaces:**
- Consumes: `config.get("video_subtitle_traditional", False)`.
- Produces: both main-video `build_ass` and `build_srt` calls receive `traditional=bool(config.get("video_subtitle_traditional", False))`.

- [ ] **Step 1: Write the failing forwarding test**

```python
import inspect
from app import pipeline_runner


def test_main_video_composition_forwards_traditional_subtitle_setting():
    source = inspect.getsource(pipeline_runner._stage_compose_manifest_impl)
    assert 'traditional=bool(config.get("video_subtitle_traditional", False))' in source
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_stage6_compose_subtitles.py::test_main_video_composition_forwards_traditional_subtitle_setting -v`

Expected: FAIL because `_stage_compose_manifest_impl` does not forward the setting.

- [ ] **Step 3: Add the setting and forward it**

Add `"video_subtitle_traditional": False` alongside existing video subtitle defaults. Add `check("繁体字幕", "video_subtitle_traditional")` below the subtitle style toggles in the GUI, and add that key to `bool_keys`. In `_stage_compose_manifest_impl`, pass the exact `traditional` value to its main-video ASS/SRT calls. `resume_compose_only` already routes through `stage_compose`, which delegates to this implementation. Do not change any Short subtitle call.

- [ ] **Step 4: Run all feature tests to verify they pass**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_stage6_compose_subtitles.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

This workspace has no `.git` directory. Record the modified files and test output in the final handoff instead of attempting a commit.

### Task 3: Run project validation

**Files:**
- Verify: `app/config.py`, `app/gui.py`, `app/pipeline_runner.py`, `app/stages/stage6_compose.py`, `requirements.txt`, `tests/test_stage6_compose_subtitles.py`

**Interfaces:**
- Consumes: the completed Tasks 1 and 2 changes.
- Produces: fresh test and compilation evidence.

- [ ] **Step 1: Run focused tests**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_stage6_compose_subtitles.py -v`

Expected: PASS with all conversion and forwarding tests passing.

- [ ] **Step 2: Run the project safe compilation bundle**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py
.\.venv\Scripts\python.exe -m compileall app
```

Expected: both commands exit with code 0.

- [ ] **Step 3: Verify scope**

Run: `git diff -- app/config.py app/gui.py app/pipeline_runner.py app/stages/stage6_compose.py requirements.txt tests/test_stage6_compose_subtitles.py`

Expected: unavailable because this workspace is not a Git repository; instead inspect each changed file directly and confirm no Short subtitle call received the new flag.

- [ ] **Step 4: Commit**

This workspace has no `.git` directory. Do not create a repository or commit; report this limitation.
