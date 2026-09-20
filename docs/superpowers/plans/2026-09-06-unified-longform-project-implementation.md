# 统一长篇项目中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy project workflow with a source-backed longform project workflow that safely creates and runs chapter-bounded episode groups.

**Architecture:** Keep each episode as the existing resumable job format, but persist the source, allocation cursor, batches, and cross-episode ledgers under its project. Extend the global queue selector so a batch is an exclusive scheduling unit. The GUI remains the existing Tk project tab and adds explicit longform import actions and settings rather than changing the rest of the application shell.

**Tech Stack:** Python 3, Tkinter/ttk, JSON files under `data/projects`, existing scraper interfaces, pytest, FFmpeg/TTS pipeline.

## Global Constraints

- Keep normal “加入任务” behavior unchanged.
- Do not fetch a remote book's whole text until the user creates a batch.
- Defaults are 60 minimum minutes, 240 maximum minutes, and 5 episodes per batch; every project may override them.
- Never split a detected source chapter; an oversized chapter remains whole after an explicit warning/confirmation.
- A batch is strict FIFO: a later member or outside job cannot start while an earlier member is incomplete; any member failure or stop pauses the entire batch.
- Project-level name memory and character/reference locking are optional, manual switches.
- Existing tasks, projects, settings, media, and uploads remain readable and are never automatically deleted or rewritten.
- Use `apply_patch` for edits. This workspace has no Git metadata, so do not attempt commits; record verification instead.

---

### Task 1: Complete durable longform project state

**Files:**
- Modify: `app/project_manager.py`
- Modify: `app/config.py`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Produces `normalize_longform_settings(value: object) -> dict`, `bind_longform_source(project_id: str, *, kind: str, reference: str, title: str, source_hash: str = "") -> dict`, `update_longform_settings(project_id: str, updates: dict) -> dict`.
- Produces `create_longform_batch(project_id: str, episodes: list[dict], settings_snapshot: dict) -> dict`, `attach_longform_batch_jobs(project_id: str, batch_id: str, job_ids: list[str]) -> dict`, `get_longform_batch(project_id: str, batch_id: str) -> dict`, `pause_longform_batch(project_id: str, batch_id: str, job_id: str, error: str) -> dict`, and `complete_longform_member(project_id: str, batch_id: str, job_id: str) -> dict`.
- Consumed by Tasks 2–5. Batch records must include `batch_id`, `state`, `members`, `source_start`, `source_end`, `settings_snapshot`, `reserved_next_chapter`, and `completed_next_chapter`.

- [ ] **Step 1: Write failing persistence and migration tests**

```python
def test_new_project_has_safe_longform_defaults(tmp_path, monkeypatch):
    projects = load_project_manager(monkeypatch, tmp_path)
    project = projects.create_project("长篇")
    assert project["longform"]["enabled"] is False
    assert project["longform"]["min_minutes"] == 60
    assert project["longform"]["max_minutes"] == 240
    assert project["longform"]["batch_episode_count"] == 5

def test_failed_batch_does_not_advance_completed_cursor(tmp_path, monkeypatch):
    projects = load_project_manager(monkeypatch, tmp_path)
    project = projects.create_project("长篇")
    projects.bind_longform_source(project["project_id"], kind="txt", reference="source.txt", title="长篇")
    batch = projects.create_longform_batch(project["project_id"], [{"start_chapter": 1, "end_chapter": 3}], {"min_minutes": 60})
    projects.attach_longform_batch_jobs(project["project_id"], batch["batch_id"], ["episode-1"])
    projects.pause_longform_batch(project["project_id"], batch["batch_id"], "episode-1", "TTS failed")
    saved = projects.load_project(project["project_id"])
    assert saved["longform"]["completed_next_chapter"] == 1
    assert saved["longform"]["batches"][0]["state"] == "paused"
```

- [ ] **Step 2: Run the new persistence tests and verify they fail**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: FAIL because the longform methods and schema have not been fully defined.

- [ ] **Step 3: Implement normalized schema, atomic updates, and settings migration**

In `app/project_manager.py`, add a normalized `longform` object to every loaded/saved project. Use the existing `_project_file_lock` for every mutating operation. Store a source record without fetching remote content. Add batches only after the planner has immutable source boundaries; reserve boundaries at creation and advance `completed_next_chapter` only when `complete_longform_member` completes the last member.

In `app/config.py`, increment `SETTINGS_SCHEMA_VERSION`; add `longform_default_min_minutes: 60`, `longform_default_max_minutes: 240`, and `longform_default_batch_episode_count: 5` to `DEFAULT_SETTINGS`; add a migration that supplies these keys to legacy settings and profiles without changing existing projects.

- [ ] **Step 4: Run persistence tests and configuration imports**

Run: `python -m pytest tests/test_longform_projects.py tests/test_rewrite_localization_config.py -q`

Expected: PASS. Verify a legacy `project.json` missing `longform` loads with disabled defaults.

- [ ] **Step 5: Record verification**

Run: `git rev-parse --show-toplevel`

Expected: the known “not a git repository” result. Do not create or emulate a commit.

### Task 2: Plan source ranges and materialize only one batch

**Files:**
- Modify: `app/scrapers/qingtian.py`
- Modify: `app/pipeline_runner.py:plan_longform_episodes`, `app/pipeline_runner.py:create_next_longform_book_batch`, `app/pipeline_runner.py:create_next_longform_local_batch`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Consumes Task 1's source and batch APIs.
- Produces `QingtianAggregateScraper.fetch_chapter_range(url_or_id: str, start_chapter: int, end_chapter: int) -> Novel`.
- Produces `plan_longform_episodes(chapters: list[NovelChapter], *, seconds_per_character: float, min_minutes: int, max_minutes: int, count: int) -> tuple[list[dict], list[str]]` where each episode contains only whole input chapters and `start_chapter`, `end_chapter`, `estimated_seconds`, `chapters`.
- Produces `create_longform_jobs_from_episodes(...) -> list[str]` with per-job frozen settings snapshot, batch ID/order, and a task-local source snapshot.

- [ ] **Step 1: Write failing source and boundary tests**

```python
def test_planner_ends_before_next_chapter_that_exceeds_maximum():
    chapters = [chapter(1, 4_000), chapter(2, 4_000), chapter(3, 4_000)]
    episodes, warnings = runner.plan_longform_episodes(
        chapters, seconds_per_character=1.0, min_minutes=100, max_minutes=150, count=2
    )
    assert [(item["start_chapter"], item["end_chapter"]) for item in episodes] == [(1, 2), (3, 3)]
    assert warnings == []

def test_planner_keeps_one_oversized_chapter_whole():
    episodes, warnings = runner.plan_longform_episodes(
        [chapter(7, 20_000)], seconds_per_character=1.0, min_minutes=60, max_minutes=240, count=1
    )
    assert episodes[0]["start_chapter"] == episodes[0]["end_chapter"] == 7
    assert "完整章节" in warnings[0]

def test_book_batch_fetches_only_range_needed_for_requested_episodes(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runner, "_build_scraper", lambda _site: range_scraper(calls, chapters=make_chapters(40)))
    batch, jobs, _ = runner.create_next_longform_book_batch(make_enabled_project(tmp_path, count=2))
    assert len(jobs) == 2
    assert max(calls) < 40
```

- [ ] **Step 2: Run planner tests and verify they fail**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: FAIL for missing range fetch, unbounded/faulty source handling, or incomplete materialization state.

- [ ] **Step 3: Implement bounded source retrieval and safe local snapshots**

Implement a catalog-aware chapter-range method in `qingtian.py` that resolves the book once, slices the catalog by 1-based source index, and fetches only requested chapter content. Do not call the full-book `fetch` path for a longform batch.

In `pipeline_runner.py`, retain recognized chapter headings in the materialized source text so the batch ledger remains auditable; each task's later cleaning may remove them for narration. For TXT, create a project-owned immutable source copy and verify a stored hash before each new batch. Use heading ranges when headings exist; otherwise use paragraph/complete-sentence ranges and persist offsets rather than referring to a mutable original file.

Store the exact per-episode text and settings snapshot before queueing, so later setting changes cannot alter a pending batch. Do not create audio, image, cover, or video artifacts during planning.

- [ ] **Step 4: Run focused tests and inspect planned task directories**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: PASS. Assert planned jobs have only status/log/source snapshot files and no `audio`, `images`, `cover`, or MP4 output.

- [ ] **Step 5: Record verification**

Run: `python -m py_compile app/project_manager.py app/pipeline_runner.py app/scrapers/qingtian.py`

Expected: exit code 0.

### Task 3: Make longform batches exclusive in the global queue

**Files:**
- Modify: `app/pipeline_runner.py:start_next_queued_job`, `app/pipeline_runner.py:queue_all_pending_jobs`, task completion/error handling near `run_pipeline`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Consumes Task 1 batch records and Task 2 job status fields `longform_batch_id`, `longform_batch_order`, and `project_id`.
- Produces `next_runnable_job(rows: list[dict]) -> str | None` or an equivalent private selector used by `start_next_queued_job`.
- Calls `projects.pause_longform_batch` on every failed or stopped member and `projects.complete_longform_member` only after a member's configured full delivery pipeline succeeds.

- [ ] **Step 1: Write failing scheduling tests**

```python
def test_queue_runs_all_members_of_active_batch_before_unrelated_job(monkeypatch, tmp_path):
    seed_jobs(tmp_path, [
        queued("a1", batch="batch-a", order=1), queued("a2", batch="batch-a", order=2),
        queued("other"),
    ])
    assert runner.next_runnable_job(runner.list_jobs(20)) == "a1"
    mark_completed("a1")
    assert runner.next_runnable_job(runner.list_jobs(20)) == "a2"
    mark_completed("a2")
    assert runner.next_runnable_job(runner.list_jobs(20)) == "other"

def test_failed_member_pauses_batch_and_blocks_later_member(monkeypatch, tmp_path):
    seed_jobs(tmp_path, [queued("a1", batch="batch-a", order=1), queued("a2", batch="batch-a", order=2)])
    mark_failed("a1")
    assert runner.next_runnable_job(runner.list_jobs(20)) is None
    assert batch_state("batch-a") == "paused"
```

- [ ] **Step 2: Run queue tests and verify they fail**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: FAIL because current global ordering can pick a later or unrelated queued job and lacks complete batch gating.

- [ ] **Step 3: Implement one exclusive batch selector and lifecycle updates**

Before selecting ordinary queued work, find the earliest non-terminal longform batch in queue order. Permit only its earliest incomplete member, and only when no member of that batch is running. If a batch is paused, skip it and do not start later members; the normal queue may proceed only after the user explicitly resumes or removes that paused batch according to the UI action.

On worker success, mark the member complete after upload if auto-upload is enabled, otherwise after composition. On all existing failure, skip, and stop paths, pause the batch before calling the next-job selector. Preserve current non-longform concurrency and queue behavior.

- [ ] **Step 4: Run scheduling tests and a non-longform regression**

Run: `python -m pytest tests/test_longform_projects.py tests/test_pipeline_rewrite_localization.py -q`

Expected: PASS. Verify an unrelated ordinary queue remains FIFO when there is no active longform batch.

- [ ] **Step 5: Record verification**

Run: `python -m py_compile app/pipeline_runner.py`

Expected: exit code 0.

### Task 4: Add optional project continuity ledgers

**Files:**
- Modify: `app/project_manager.py`
- Modify: `app/pipeline_runner.py:_rewrite_story_text`, `app/pipeline_runner.py:stage_clean`, `app/pipeline_runner.py:share_series_character_analysis`, `app/pipeline_runner.py:stage_character_references`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Produces `load_project_name_ledger(project_id: str) -> dict` and `merge_project_name_ledger(project_id: str, entries: list[dict]) -> dict` backed by `data/projects/{project_id}/longform_name_ledger.json`.
- Consumes a job's `project_id` and its frozen `longform_project_name_memory_enabled` / `longform_project_character_lock_enabled` status fields.
- Produces job-local audit snapshots while retaining the existing shared character profile/reference APIs.

- [ ] **Step 1: Write failing continuity tests**

```python
def test_project_name_memory_reuses_existing_mapping(monkeypatch, tmp_path):
    project_id = seed_project_name_ledger(tmp_path, {"林晚": "早川澪"})
    text = runner.rewrite_with_project_memory("林晚走进大厅", project_id=project_id, model=fake_model("林晚走进大厅"))
    assert "早川澪" in text
    assert load_name_ledger(project_id)["mappings"]["林晚"]["canonical"] == "早川澪"

def test_disabled_project_locks_leave_existing_task_local_behavior(monkeypatch, tmp_path):
    job_dir = make_job(tmp_path, project_id="", longform_project_name_memory_enabled=False)
    assert runner._rewrite_story_text("林晚", job_dir=job_dir) == "林晚"
```

- [ ] **Step 2: Run continuity tests and verify they fail**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: FAIL because the task-local rewrite checkpoint cannot read or merge a project-level ledger.

- [ ] **Step 3: Implement opt-in project name and character behavior**

Read the frozen per-job longform flags, never live GUI settings, in pipeline stages. For enabled name memory, load known mappings before prompting/validating rewrite batches, merge only validated new mappings under the project lock, then write a job-local snapshot for audit. Keep the current task-local rewrite path unchanged when disabled.

For enabled character locking, reuse and strengthen the existing project character profiles, name registry, visual bible, and character-reference manifest: resolve characters by canonical rewritten name plus aliases, preserve `confirmed` records, append new identities, and reuse existing reference assets. Do not modify character behavior when the switch is off.

- [ ] **Step 4: Run continuity and existing rewrite tests**

Run: `python -m pytest tests/test_longform_projects.py tests/test_rewrite_localization.py tests/test_pipeline_rewrite_localization.py -q`

Expected: PASS. Verify known names and confirmed references remain stable across two sequential jobs.

- [ ] **Step 5: Record verification**

Run: `python -m py_compile app/project_manager.py app/pipeline_runner.py`

Expected: exit code 0.

### Task 5: Finish the existing Tk integration, conversion, and operator documentation

**Files:**
- Modify: `app/gui.py`
- Modify: `README.md`
- Modify: `docs/module_prompt_editing_guide.md`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Consumes Tasks 1–4 APIs.
- Produces GUI handlers `_add_selected_search_to_longform`, `_add_selected_files_to_longform`, `_convert_selected_job_to_longform`, `_create_current_longform_batch`, `_resume_current_longform_batch` and project tree labels derived from persisted batch state.

- [ ] **Step 1: Write failing GUI/API seam tests**

```python
def test_search_longform_handler_binds_reference_without_creating_regular_job(monkeypatch):
    gui = make_gui_with_one_search_result(monkeypatch, title="百万字小说", ref="qingtian://book")
    gui._add_selected_search_to_longform()
    assert recorded_bindings() == [("book", "qingtian://book", "百万字小说")]
    assert recorded_regular_jobs() == []

def test_convert_pending_regular_book_job_reuses_its_reference(monkeypatch, tmp_path):
    job_id = seed_pending_book_job(tmp_path, "qingtian://book")
    assert runner.convert_pending_book_job_to_longform(job_id, "project-1") is True
    assert not runner.job_dir_for(job_id).exists()
    assert project_source("project-1")["reference"] == "qingtian://book"
```

- [ ] **Step 2: Run GUI seam tests and verify they fail**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: FAIL for missing file-import action, conversion API, group resume UI, or incomplete handler wiring.

- [ ] **Step 3: Complete UI using the current project's visual conventions**

Keep the existing notebook tab, `ttk.LabelFrame`, toolbar, project tree, and series title controls. Rename user-facing “系列项目” copy to “长篇项目” where it describes this replacement workflow. Keep `加入选中书籍` as the normal-task action and the existing `加入长篇项目…` action as its explicit companion.

Add the same explicit longform choice to file/TXT import and pasted-text import. For local text, copy content into the project source store before binding. Add conversion only for non-running pending book/TXT jobs; require confirmation and retain completed/running jobs unchanged. Add project-tree child rows or concise labels for batch state, completed boundary, and paused member. The action to create a batch must show a preview with episode boundaries and warnings before final creation; the resume action must resume only the paused member.

Document: the two import choices, 60–240/5 defaults, expected estimate calibration, whole-chapter behavior, group queue semantics, pause/retry semantics, optional name/persona switches, TXT behavior, and safe legacy migration.

- [ ] **Step 4: Run UI seam tests and project documentation checks**

Run: `python -m pytest tests/test_longform_projects.py tests/test_rewrite_localization_docs.py -q`

Expected: PASS. Manually launch the GUI and confirm the project tab opens without Tcl errors, defaults display correctly, and normal book import remains present.

- [ ] **Step 5: Run the project safe validation bundle**

Run:

```bash
python3 -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py
python3 -m compileall app
python3 - <<'PY'
from app import upload
mod = upload._load()
print(mod.__name__, hasattr(mod, "upload_via_browser"), hasattr(mod, "_select_file_with_playwright"))
from app.config import config
print(config.get("settings_schema_version"), config.get("browser_chrome_profile"))
from app.utils.secrets import redact_secret_text
print(redact_secret_text("Bearer sk-example1234567890"))
PY
```

Expected: every command exits successfully; output contains redacted rather than raw test credential text.

## Plan self-review

- Spec coverage: Task 1 covers persistent settings, source/progress/batches and safe migration. Task 2 covers all three source classes, whole-chapter timing and task snapshots. Task 3 covers strict batch queue ownership and pause/resume. Task 4 covers manual cross-episode names and locked character assets. Task 5 covers the existing GUI style, explicit import routes, conversion, preview, documentation and complete validation.
- Placeholder scan: no TBD/TODO or unspecified validation remains; each task states concrete functions, files, tests and expected command outcomes.
- Type consistency: Tasks 2–5 consume the Task 1 names (`longform`, `batch_id`, `members`, `complete_longform_member`, `pause_longform_batch`) consistently. All planned episode dicts use `start_chapter`, `end_chapter`, `estimated_seconds`, and `chapters`.
