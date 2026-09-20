# Short Retry Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a retried Short report its current state in the task queue immediately and accurately without altering the finished main-video state.

**Architecture:** Persist a dedicated `short_retry_in_progress` flag in each job's existing `status.json`. The retry worker owns transitions into and out of this flag; the GUI's existing Short-column formatter renders it before stale errors. It also schedules a table refresh after every per-job transition.

**Tech Stack:** Python 3, Tkinter, existing JSON status persistence, unittest.

## Global Constraints

- Never overwrite the status fields `stage`, `progress`, or `error` during a Short retry.
- Persist only redacted exception text.
- Do not add dependencies.

---

### Task 1: Add testable Short retry status helpers

**Files:**
- Create: `tests/test_short_retry_status.py`
- Modify: `app/pipeline_runner.py:7996-8018`

**Interfaces:**
- Produces `mark_job_short_retrying(job_id: str) -> None`.
- Produces `mark_job_short_retry_failed(job_id: str, error: str) -> None`.
- `regenerate_job_short()` clears `short_retry_in_progress` when it writes successful output.

- [ ] **Step 1: Write the failing tests**

```python
def test_short_retry_markers_preserve_main_job_status(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "job_dir_for", lambda _job_id: tmp_path)
    pr.write_status(tmp_path, stage="completed", progress=1.0, error="", short_error="old")
    pr.mark_job_short_retrying("job-1")
    status = pr.load_status("job-1", include_worker=False)
    assert status["stage"] == "completed"
    assert status["progress"] == 1.0
    assert status["short_retry_in_progress"] is True
    assert status["short_error"] == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_short_retry_status.ShortRetryStatusTests.test_short_retry_markers_preserve_main_job_status -v`

Expected: FAIL because `mark_job_short_retrying` does not exist.

- [ ] **Step 3: Write the minimal implementation**

```python
def mark_job_short_retrying(job_id: str) -> None:
    write_status(_safe_job_path(job_id), short_error="", short_retry_in_progress=True)

def mark_job_short_retry_failed(job_id: str, error: str) -> None:
    write_status(_safe_job_path(job_id), short_error=redact_secret_text(error), short_retry_in_progress=False)
```

Update the successful `write_status` in `regenerate_job_short()` to include `short_retry_in_progress=False`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_short_retry_status -v`

Expected: PASS.

### Task 2: Render the persisted retry state and refresh after each outcome

**Files:**
- Modify: `app/gui.py:6325-6368,7850-7867`
- Modify: `tests/test_short_retry_status.py`

**Interfaces:**
- `_short_queue_status(job_id: str, status: dict) -> str` returns `"制作中"` when `short_retry_in_progress` is true.
- `_regenerate_selected_shorts()` calls `pr.mark_job_short_retrying()` before regeneration, calls `pr.mark_job_short_retry_failed()` in its exception branch, and requests `self._refresh_jobs()` on the Tk main thread after each job.

- [ ] **Step 1: Write the failing tests**

```python
def test_short_queue_status_prefers_retrying_over_previous_error(gui, monkeypatch):
    monkeypatch.setattr(gui_module.Path, "exists", lambda _path: False)
    assert gui._short_queue_status("job-1", {
        "short_retry_in_progress": True,
        "short_error": "old failure",
    }) == "制作中"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_short_retry_status.ShortRetryStatusTests.test_short_queue_status_prefers_retrying_over_previous_error -v`

Expected: FAIL because the formatter returns `"失败"`.

- [ ] **Step 3: Write the minimal implementation**

```python
if bool(status.get("short_retry_in_progress", False)):
    return "制作中"
```

Place this check before `short_error` in `_short_queue_status`. In the worker's per-job `try`/`except`, write the corresponding start/success/failure status and call `self.root.after(0, self._refresh_jobs)` immediately after each completed job.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m unittest tests.test_short_retry_status -v`

Expected: PASS.

### Task 3: Run project validation

**Files:**
- Verify: `app/pipeline_runner.py`, `app/gui.py`, `tests/test_short_retry_status.py`

- [ ] **Step 1: Run focused regression tests**

Run: `python -m unittest tests.test_short_retry_status -v`

Expected: PASS.

- [ ] **Step 2: Run the mandated compile validation**

Run: `python3 -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py`

Expected: exit code 0.

- [ ] **Step 3: Run the mandated smoke import**

Run: `python3 -c "from app import upload; mod=upload._load(); assert hasattr(mod, 'upload_via_browser'); from app.config import config; assert config.get('settings_schema_version') is not None"`

Expected: exit code 0.
