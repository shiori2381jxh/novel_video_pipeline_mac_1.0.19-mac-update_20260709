# Longform Target Character Episodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make longform episodes select the whole-chapter boundary closest to a project-editable 22,000-character target, with 18,000 and 88,000 as safeguards.

**Architecture:** Persist `target_final_chars` with the two existing bounds and normalize legacy records to 22,000. A pure planner receives all three values and chooses the nearest eligible chapter boundary. The project GUI saves, loads, validates, and explains the setting.

**Tech Stack:** Python 3, Tkinter/ttk, pytest.

## Global Constraints

- Target, minimum, and maximum are project-editable positive integers; defaults are 22,000, 18,000, and 88,000.
- Enforce `min_final_chars <= target_final_chars <= max_final_chars`.
- Never split a source chapter.
- Legacy records without a target use 22,000.

---

### Task 1: Persist target defaults and legacy normalization

**Files:**
- Modify: `app/config.py`
- Modify: `app/project_manager.py`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Produces: `normalize_longform_settings(value: object) -> dict` including `target_final_chars: int`.

- [ ] **Step 1: Write failing tests**

```python
def test_old_longform_record_without_target_uses_default_target():
    settings = project_manager.normalize_longform_settings(
        {"min_final_chars": 18_000, "max_final_chars": 88_000}
    )
    assert settings["target_final_chars"] == 22_000
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_longform_projects.py -k without_target -v`

Expected: FAIL because `target_final_chars` is absent.

- [ ] **Step 3: Implement defaults and normalization**

```python
"longform_default_min_final_chars": 18000,
"longform_default_target_final_chars": 22000,
"longform_default_max_final_chars": 88000,
# Normalize target after min/max and clamp it into [minimum, maximum].
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_longform_projects.py -k without_target -v`

Expected: PASS.

### Task 2: Select chapter boundary nearest the target

**Files:**
- Modify: `app/pipeline_runner.py`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Consumes: `plan_longform_episodes(chapters, min_final_chars, target_final_chars, max_final_chars, minimum_rewrite_ratio, count)`.
- Produces: episode dictionaries and `_longform_settings_snapshot()` including the target.

- [ ] **Step 1: Write failing planner tests**

```python
def test_episode_planner_chooses_complete_chapter_boundary_nearest_target():
    chapters = [
        NovelChapter(index=1, title="第1章", text="甲" * 10_000),
        NovelChapter(index=2, title="第2章", text="乙" * 9_000),
        NovelChapter(index=3, title="第3章", text="丙" * 8_000),
    ]
    episodes, _ = pipeline_runner.plan_longform_episodes(
        chapters, min_final_chars=18_000, target_final_chars=22_000,
        max_final_chars=88_000, minimum_rewrite_ratio=1.0, count=1,
    )
    assert episodes[0]["end_chapter"] == 2
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_longform_projects.py -k nearest_target -v`

Expected: FAIL because the planner lacks the target argument.

- [ ] **Step 3: Implement planning and propagation**

```python
if estimated_chars >= minimum:
    next_total = estimated_chars + chapter_chars
    if abs(estimated_chars - target) <= abs(next_total - target):
        break
```

Pass the target to both batch creators and retain the existing warning behavior for a required/standalone over-limit chapter.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_longform_projects.py -v`

Expected: PASS.

### Task 3: Expose target in the project UI

**Files:**
- Modify: `app/gui.py`
- Test: `tests/test_longform_projects.py`, `tests/test_gui_scroll_collapse.py`

**Interfaces:**
- Consumes: `longform["target_final_chars"]`.
- Produces: `project_longform_target_final_chars_var: tk.StringVar` passed to the project update method.

- [ ] **Step 1: Write failing snapshot test**

```python
def test_longform_settings_snapshot_includes_target_characters():
    snapshot = pipeline_runner._longform_settings_snapshot(
        {"min_final_chars": 18_000, "target_final_chars": 22_000, "max_final_chars": 88_000}
    )
    assert snapshot["target_final_chars"] == 22_000
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_longform_projects.py::test_longform_settings_snapshot_includes_target_characters -v`

Expected: FAIL because the snapshot omits the target.

- [ ] **Step 3: Implement editable target UI**

```python
self.project_longform_target_final_chars_var = tk.StringVar(
    value=str(config.get("longform_default_target_final_chars", 22000))
)
if not (longform_minimum <= longform_target <= longform_maximum):
    messagebox.showwarning("长篇分集设置无效", "最少、目标、最多字数须为正整数，且最少≤目标≤最多。")
    return None
```

Place “目标字数” between the minimum and maximum inputs. Load/save it, and revise the description and confirmation to say the target is preferred while bounds are safeguards.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_longform_projects.py tests/test_gui_scroll_collapse.py -v`

Expected: PASS.

### Task 4: Verify the integrated change

**Files:**
- Verify: `app/config.py`, `app/project_manager.py`, `app/gui.py`, `app/pipeline_runner.py`, `tests/test_longform_projects.py`

- [ ] **Step 1: Run focused regression coverage**

Run: `python -m pytest tests/test_longform_projects.py tests/test_gui_scroll_collapse.py -v`

Expected: PASS.

- [ ] **Step 2: Run the safe validation bundle**

Run: `python3 -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py`

Expected: exit code 0.

- [ ] **Step 3: Inspect the final change set**

Run: `git diff --check; git diff -- app/config.py app/project_manager.py app/gui.py app/pipeline_runner.py tests/test_longform_projects.py`

Expected: no whitespace errors and consistent use of `target_final_chars`.
