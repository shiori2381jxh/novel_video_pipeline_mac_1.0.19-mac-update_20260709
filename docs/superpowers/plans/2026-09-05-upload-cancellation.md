# Upload Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop requests prevent the active upload from opening, restarting, or reconnecting Chrome again.

**Architecture:** `stage5_upload_browser.py` receives the existing upload job object at its lifecycle boundaries. A small cancellation-aware wait helper is used for retry pauses and Chrome readiness waits so the outer upload loop can return before any subsequent browser action.

**Tech Stack:** Python 3, Playwright sync upload implementation, pytest/unittest-style isolated module tests.

## Global Constraints

- Preserve the signed-in Chrome process when a user stops an upload.
- Do not start, restart, or reconnect Chrome after `job.is_cancelled()` becomes true.
- Do not change the behavior of uploads that have not been cancelled.

---

### Task 1: Make Chrome lifecycle waits cancellation-aware

**Files:**
- Create: `tests/test_stage5_upload_cancellation.py`
- Modify: `app/vendor/stage5_upload_browser.py:282-317,567-715`

**Interfaces:**
- Consumes: upload job objects exposing `is_cancelled() -> bool`.
- Produces: `_wait_until_cancelled(job, seconds) -> bool`, where `True` means cancellation was observed; `_launch_chrome(..., job=None) -> bool` returns without spawning Chrome when cancelled.

- [ ] **Step 1: Write the failing test**

```python
def test_launch_chrome_does_not_spawn_when_job_is_cancelled(monkeypatch):
    job = CancelledJob()
    monkeypatch.setattr(upload, "_find_chrome_exe", lambda: "chrome.exe")
    popen = monkeypatch.setattr(upload.subprocess, "Popen", fail_if_called)

    assert upload._launch_chrome(SimpleNamespace(), lambda _msg: None, "Account-4", job) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_stage5_upload_cancellation.py::test_launch_chrome_does_not_spawn_when_job_is_cancelled -v`

Expected: FAIL because `_launch_chrome` has no `job` parameter.

- [ ] **Step 3: Write minimal implementation**

```python
def _is_cancelled(job) -> bool:
    return bool(job is not None and job.is_cancelled())

def _launch_chrome(config, on_log, profile_name="", job=None):
    if _is_cancelled(job):
        on_log("上传已取消")
        return False
    # existing launch logic
```

Pass `job` from all launch/restart callers and check it before each retry, restart, and reconnect action. Replace retry `time.sleep` calls with a helper that wakes in short intervals and returns early when cancelled.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_stage5_upload_cancellation.py -v`

Expected: PASS.

- [ ] **Step 5: Run project-safe verification**

Run: `python -m py_compile app/vendor/stage5_upload_browser.py app/gui.py app/pipeline_runner.py`

Expected: exit code 0.

- [ ] **Step 6: Commit**

This workspace is not a Git checkout, so no commit is possible. Record the changed files and verification result in the handoff.
