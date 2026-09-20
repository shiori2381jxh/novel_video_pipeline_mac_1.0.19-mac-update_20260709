# Windows Upload File Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably attach a Windows local MP4 to YouTube Studio before its scheduled-publish flow begins.

**Architecture:** Keep `_select_file_via_dialog` as the public selection entrypoint. On Windows, it will first use the same browser-side path currently used on other platforms; a failed browser assignment will retain the current native picker routine as a compatibility fallback. A small test module will exercise the dispatcher with controllable helper outcomes.

**Tech Stack:** Python 3, Playwright synchronous API, pytest/unittest mocking, Windows native `ctypes` fallback.

## Global Constraints

- Keep the existing scheduled publishing and YouTube channel guard behavior unchanged.
- Do not remove the native Windows picker; retain it as last-resort compatibility handling.
- Do not report file-selection success until YouTube's metadata title field is present.
- Run the project safe validation bundle after the focused regression test.

---

### Task 1: Add a regression test for Windows browser-first selection

**Files:**
- Create: `tests/test_stage5_upload_browser.py`
- Modify: `app/vendor/stage5_upload_browser.py:1800-1820`

**Interfaces:**
- Consumes: `_select_file_via_dialog(page, video_path, on_log, timeout) -> bool`
- Produces: a platform-independent dispatch helper returning `True` when the browser-side selection succeeds, and only invoking the native picker when it fails.

- [ ] **Step 1: Write the failing test**

```python
def test_windows_selection_prefers_browser_input(monkeypatch, tmp_path):
    import app.vendor.stage5_upload_browser as upload
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    calls = []

    monkeypatch.setattr(upload.os, "name", "nt")
    monkeypatch.setattr(upload, "_select_file_with_playwright", lambda *args: calls.append("browser") or True)
    monkeypatch.setattr(upload, "_try_select_file_once", lambda *args: calls.append("native") or True)

    assert upload._select_file_via_dialog(object(), video, lambda _message: None, 1_000)
    assert calls == ["browser"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_stage5_upload_browser.py::test_windows_selection_prefers_browser_input -v`

Expected: FAIL because the current Windows branch invokes `_try_select_file_once` directly.

- [ ] **Step 3: Write minimal implementation**

```python
if os.name == "nt":
    if _select_file_with_playwright(page, video_path, on_log, timeout):
        return True
    on_log("  ⚠️ 浏览器文件输入设置失败，改用 Windows 文件选择窗口...")
    return _try_select_file_once(page, video_path, on_log, timeout)
return _select_file_with_playwright(page, video_path, on_log, timeout)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_stage5_upload_browser.py::test_windows_selection_prefers_browser_input -v`

Expected: PASS and the native helper is not called.

- [ ] **Step 5: Commit**

The current workspace has no `.git` directory, so record this as not applicable; do not initialize or create a repository.

### Task 2: Prove native fallback remains available

**Files:**
- Modify: `tests/test_stage5_upload_browser.py`
- Modify: `app/vendor/stage5_upload_browser.py:1800-1820`

**Interfaces:**
- Consumes: `_select_file_with_playwright(...) -> bool` and `_try_select_file_once(...) -> bool`
- Produces: Windows fallback behavior that calls the native helper only after browser-side assignment returns `False`.

- [ ] **Step 1: Write the failing test**

```python
def test_windows_selection_uses_native_picker_after_browser_failure(monkeypatch, tmp_path):
    import app.vendor.stage5_upload_browser as upload
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    calls = []

    monkeypatch.setattr(upload.os, "name", "nt")
    monkeypatch.setattr(upload, "_select_file_with_playwright", lambda *args: calls.append("browser") or False)
    monkeypatch.setattr(upload, "_try_select_file_once", lambda *args: calls.append("native") or True)

    assert upload._select_file_via_dialog(object(), video, lambda _message: None, 1_000)
    assert calls == ["browser", "native"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_stage5_upload_browser.py::test_windows_selection_uses_native_picker_after_browser_failure -v`

Expected: FAIL because the initial implementation has not yet introduced the fallback branch.

- [ ] **Step 3: Write minimal implementation**

```python
if os.name == "nt":
    if _select_file_with_playwright(page, video_path, on_log, timeout):
        return True
    on_log("  ⚠️ 浏览器文件输入设置失败，改用 Windows 文件选择窗口...")
    return _try_select_file_once(page, video_path, on_log, timeout)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_stage5_upload_browser.py -v`

Expected: PASS with both dispatch-order tests.

- [ ] **Step 5: Commit**

The current workspace has no `.git` directory, so record this as not applicable; do not initialize or create a repository.

### Task 3: Validate the changed upload path

**Files:**
- Modify: `app/vendor/stage5_upload_browser.py`
- Test: `tests/test_stage5_upload_browser.py`

**Interfaces:**
- Consumes: the file-selection dispatcher from Tasks 1 and 2.
- Produces: a syntactically valid browser uploader with Windows browser-first selection.

- [ ] **Step 1: Run focused regression tests**

Run: `python -m pytest tests/test_stage5_upload_browser.py -v`

Expected: PASS.

- [ ] **Step 2: Run the safe validation bundle**

Run: `python -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py`

Expected: exit code 0.

- [ ] **Step 3: Validate dynamic uploader imports**

Run: `python -c "from app import upload; mod = upload._load(); print(mod.__name__, hasattr(mod, 'upload_via_browser'), hasattr(mod, '_select_file_with_playwright'))"`

Expected: module path followed by `True True`.

- [ ] **Step 4: Commit**

The current workspace has no `.git` directory, so record this as not applicable; do not initialize or create a repository.
