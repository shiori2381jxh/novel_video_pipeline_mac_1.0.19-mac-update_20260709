# 项目级洗稿替换类别 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个长片项目保存一组允许自动改名的类别，并在后续分集洗稿时强制使用这组白名单。

**Architecture:** 项目 `longform` 设置保存规范化类别列表，任务组快照把它传入每一集任务状态。结构化洗稿提示词与映射解析共用该白名单；未选映射被忽略但正文继续使用。

**Tech Stack:** Python 3、Tkinter、JSON 项目存储、pytest。

## Global Constraints

- 允许类别：人名、地名、家族名、组织名、机构名、种族名。
- “城市名”和“地点”规范化为“地名”；空输入默认为“人名”。
- 配置只存入 `data/projects/<project_id>/project.json` 的 `longform`，不写入全局配置。
- 未选类别不得替换“畜人”等原词，也不得使正文洗稿失败。

---

### Task 1: 项目设置规范化与存储

**Files:**
- Modify: `app/project_manager.py:60-110`
- Test: `tests/test_longform_projects.py`

**Interfaces:**
- Produces: `normalize_rewrite_replacement_categories(value: object) -> list[str]`.
- Produces: `longform["rewrite_replacement_categories"]: list[str]`.

- [ ] **Step 1: Write the failing test**

```python
def test_longform_project_normalizes_rewrite_categories():
    settings = normalize_longform_settings(
        {"rewrite_replacement_categories": "人名、城市名\n地点、种族名"}
    )
    assert settings["rewrite_replacement_categories"] == ["人名", "地名", "种族名"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: FAIL because the setting does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def normalize_rewrite_replacement_categories(value: object) -> list[str]:
    aliases = {"城市名": "地名", "地点": "地名", "種族名": "种族名"}
    allowed = ("人名", "地名", "家族名", "组织名", "机构名", "种族名")
    # split Chinese/ASCII commas and newlines, normalize, de-duplicate;
    # return ["人名"] when no allowed value remains.
```

Add the default list to `DEFAULT_LONGFORM_SETTINGS` and normalize it in `normalize_longform_settings`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_longform_projects.py -q`

Expected: PASS.

### Task 2: 洗稿任务快照和类别白名单

**Files:**
- Modify: `app/pipeline_runner.py:1349-1366,1461-1470,2017-2040,2703-2850`
- Modify: `app/rewrite_localization.py:103-192`
- Test: `tests/test_pipeline_rewrite_localization.py`
- Test: `tests/test_rewrite_localization.py`

**Interfaces:**
- Consumes: `longform["rewrite_replacement_categories"]`.
- Produces: status field `longform_rewrite_replacement_categories`.
- Changes: `build_structured_rewrite_prompt(..., allowed_categories: Collection[str])`.
- Changes: `parse_structured_rewrite_response(..., allowed_categories: Collection[str])`.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_response_ignores_unselected_replacement_categories():
    raw = _reply("林一看到畜人。", [
        {"category": "人名", "source": "林一", "target": "沈言", "notes": ""},
        {"category": "种族名", "source": "畜人", "target": "牧食者", "notes": ""},
    ])
    result = parse_structured_rewrite_response(
        raw, source_text="林一看到畜人。", batch_index=1,
        known_replacements=[], allowed_categories={"人名"},
    )
    assert [item.source for item in result.replacements] == ["林一"]
    assert any("未选" in item for item in result.warnings)
```

Also test that a longform job generated from a project with `["人名", "地名"]` has the same list in its task status.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rewrite_localization.py tests/test_pipeline_rewrite_localization.py tests/test_longform_projects.py -q`

Expected: FAIL because parser and job status do not support the new field.

- [ ] **Step 3: Write minimal implementation**

Add the category list to `_longform_settings_snapshot` and each created job status. For longform jobs, pass the status list to structured prompt construction and parsing. Prompt text must list only the selected categories. Parser must normalize aliases, ignore valid-but-unselected mappings with a warning, and never persist them to the cross-episode ledger.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rewrite_localization.py tests/test_pipeline_rewrite_localization.py tests/test_longform_projects.py -q`

Expected: PASS.

### Task 3: 长篇项目 GUI 输入

**Files:**
- Modify: `app/gui.py:985-1008,7379-7422,7439-7468`
- Test: `tests/test_rewrite_localization_config.py`

**Interfaces:**
- Consumes: `project_longform_rewrite_categories_var: tk.StringVar`.
- Produces: `update_novel_project_longform_settings(..., {"rewrite_replacement_categories": value})`.

- [ ] **Step 1: Write the behavior regression test**

```python
def test_gui_keeps_rewrite_categories_project_scoped():
    _ints, _floats, bool_keys = PipelineGUI._config_key_sets(object.__new__(PipelineGUI))
    assert "rewrite_replacement_categories" not in bool_keys
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `python -m pytest tests/test_rewrite_localization_config.py -q`

Expected: PASS; the field must remain project-scoped rather than becoming a global checkbox.

- [ ] **Step 3: Write minimal implementation**

Add a `StringVar(value="人名")`, an Entry labelled `替换类别`, and help text `例如：人名、地名；仅替换填写的类别，城市名/地点按地名处理。` to the longform project section. Reset/load it with project selection and include its raw value when saving longform settings.

- [ ] **Step 4: Run GUI and project tests**

Run: `python -m pytest tests/test_longform_projects.py tests/test_rewrite_localization_config.py -q`

Expected: PASS.

### Task 4: 文档与完整验证

**Files:**
- Modify: `README.md`
- Modify: `docs/module_prompt_editing_guide.md`
- Test: `tests/test_rewrite_localization_docs.py`

- [ ] **Step 1: Document the field**

State that the project-level input accepts `人名、地名`; it is saved before a new task group is created; existing queued jobs retain their old snapshot until rewashed or recreated.

- [ ] **Step 2: Add docs assertions and run them**

```python
for text in (guide, readme):
    assert "替换类别" in text
    assert "人名、地名" in text
```

Run: `python -m pytest tests/test_rewrite_localization_docs.py -q`

Expected: PASS.

- [ ] **Step 3: Run the final verification**

```powershell
python -m pytest -q
python -m py_compile app\config.py app\gui.py app\pipeline_runner.py app\upload.py app\vendor\stage5_upload_browser.py app\youtube_ad_suitability.py app\updater.py app\update_tab.py scripts\apply_update.py scripts\build_release_package.py
python -m compileall app
```

Expected: all tests pass and compilation exits with code 0.
