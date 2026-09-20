# Longform Final-Character Episodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Make longform episodes target at least 22,000 actual post-rewrite narration characters, extending an episode by whole chapters when needed.

**Architecture:** Persist character-based limits in the project longform record and migrate minute-based records. Plan source chapters conservatively, then at rewrite completion atomically append whole source chapters and shrink only queued successor members before the pipeline proceeds. The GUI presents character settings and actual outcome instead of time estimates.

**Tech Stack:** Python 3, Tkinter, pytest, JSON project/job status stores.

## Global Constraints

- Default final narration range is exactly 22,000–88,000 characters.
- Never split, duplicate, or silently discard a source chapter.
- Never alter an already running or completed successor task.
- A book-end episode may remain below 22,000 characters, but must receive a visible warning.
- Preserve existing user project settings through migration.

---

### Task 1: Persist and migrate character-based longform settings

**Files:**
- Modify: \`app/config.py\`: settings defaults and migration
- Modify: \`app/project_manager.py\`: \`DEFAULT_LONGFORM_SETTINGS\` and \`normalize_longform_settings\`
- Test: \`tests/test_longform_projects.py\`

**Interfaces:** Produces \`longform["min_final_chars"]\` and \`longform["max_final_chars"]\` as integers; all new production code consumes these instead of minute settings.

- [ ] **Step 1: Write the failing tests**

\`\`\`python
def test_new_project_uses_final_character_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "projects")
    project_manager.PROJECTS_DIR.mkdir()
    project = project_manager.create_project("长篇")
    assert project["longform"]["min_final_chars"] == 22_000
    assert project["longform"]["max_final_chars"] == 88_000

def test_old_minute_longform_record_migrates_to_character_range():
    settings = project_manager.normalize_longform_settings({"min_minutes": 2, "max_minutes": 3})
    assert settings["min_final_chars"] == 44_000
    assert settings["max_final_chars"] == 66_000
\`\`\`

- [ ] **Step 2: Run test to verify it fails**

Run: \`pytest tests/test_longform_projects.py -k "final_character_defaults or minute_longform_record" -v\`

Expected: FAIL because the fields do not exist.

- [ ] **Step 3: Write minimal implementation**

Add \`longform_default_min_final_chars=22000\` and \`longform_default_max_final_chars=88000\`; increment the settings schema; migrate old global and project \`min_minutes/max_minutes\` using 22,000 characters per hour; validate positive integers and clamp maximum to minimum.

- [ ] **Step 4: Run test to verify it passes**

Run: \`pytest tests/test_longform_projects.py -k "final_character_defaults or minute_longform_record" -v\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`bash
git add app/config.py app/project_manager.py tests/test_longform_projects.py
git commit -m "feat: store longform final character targets"
\`\`\`

### Task 2: Plan complete chapters with final-character estimates

**Files:**
- Modify: \`app/pipeline_runner.py\`: planner, batch creators, snapshot
- Test: \`tests/test_longform_projects.py\`

**Interfaces:** Replaces the minute parameters of \`plan_longform_episodes\` with \`min_final_chars\`, \`max_final_chars\`, \`minimum_rewrite_ratio\`, and \`count\`. Each episode has \`estimated_final_chars\`, \`source_char_count\`, \`start_chapter\`, \`end_chapter\`, and \`chapters\`.

- [ ] **Step 1: Write the failing test**

\`\`\`python
def test_episode_planner_uses_conservative_final_character_estimate():
    chapters = [NovelChapter(index=i, title=f"第{i}章", text="甲" * 10_000) for i in range(1, 5)]
    episodes, warnings = pipeline_runner.plan_longform_episodes(
        chapters, min_final_chars=22_000, max_final_chars=88_000,
        minimum_rewrite_ratio=0.75, count=2,
    )
    assert [(item["start_chapter"], item["end_chapter"]) for item in episodes] == [(1, 3), (4, 4)]
    assert episodes[0]["estimated_final_chars"] == 22_500
    assert warnings == []
\`\`\`

- [ ] **Step 2: Run test to verify it fails**

Run: \`pytest tests/test_longform_projects.py::test_episode_planner_uses_conservative_final_character_estimate -v\`

Expected: FAIL because the keywords are unsupported.

- [ ] **Step 3: Write minimal implementation**

Project each source chapter as \`len(chapter.text) * minimum_rewrite_ratio\`. Include full chapters until the projected size reaches the lower limit. Once above lower limit, stop before a next chapter that exceeds the upper limit. Keep a single over-limit chapter and issue a character warning. Use the configured rewrite minimum ratio for book/TXT batches and freeze character limits in snapshots.

- [ ] **Step 4: Run test to verify it passes**

Run: \`pytest tests/test_longform_projects.py -k "episode_planner or reserved_cursor" -v\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`bash
git add app/pipeline_runner.py tests/test_longform_projects.py
git commit -m "feat: plan longform episodes by final character target"
\`\`\`

### Task 3: Extend an underlength episode and reassign queued successors

**Files:**
- Modify: \`app/project_manager.py\`: atomic batch mutation API
- Modify: \`app/pipeline_runner.py\`: source loading, rewrite-completion integration, status/log reporting
- Test: \`tests/test_longform_projects.py\`

**Interfaces:** Produces \`projects.extend_longform_member(project_id, batch_id, job_id, *, current_end_chapter, final_char_count) -> dict\`. The result has \`outcome\` in \`extended\`, \`target_met\`, \`book_end\`, \`successor_started\`, or \`unavailable\`, plus an optional claimed chapter and adjusted member ranges.

- [ ] **Step 1: Write failing tests**

\`\`\`python
def test_underlength_member_claims_first_chapter_from_queued_successor(monkeypatch, tmp_path):
    # batch member a1 owns 1-3; queued a2 owns 4-6
    result = project_manager.extend_longform_member(
        project_id, batch_id, "a1", current_end_chapter=3, final_char_count=18_000
    )
    saved = project_manager.load_project(project_id)["longform"]["batches"][0]
    assert result["outcome"] == "extended"
    assert result["chapter_index"] == 4
    assert [(m["start_chapter"], m["end_chapter"]) for m in saved["members"]] == [(1, 4), (5, 6)]

def test_underlength_member_does_not_mutate_running_successor(monkeypatch, tmp_path):
    # identical batch, but successor state is running
    assert result["outcome"] == "successor_started"
\`\`\`

- [ ] **Step 2: Run tests to verify they fail**

Run: \`pytest tests/test_longform_projects.py -k "underlength_member" -v\`

Expected: FAIL because \`extend_longform_member\` does not exist.

- [ ] **Step 3: Write minimal implementation**

Under the existing project write lock, find the active member and immediate successor. Claim only the successor’s first chapter while every impacted successor is queued; update ranges, source snapshots, and job status inputs atomically. Load indexed chapters from the copied TXT source or fetch exactly one book chapter. Rewrite and clean only that added chapter, merge it with approved prior text, persist \`final_char_count\`, and repeat until the frozen lower limit is met. At source exhaustion return \`book_end\`; never mutate a running/completed successor and return \`successor_started\` with a warning.

- [ ] **Step 4: Run tests to verify they pass**

Run: \`pytest tests/test_longform_projects.py -k "underlength_member or completed_member or paused_batch" -v\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`bash
git add app/project_manager.py app/pipeline_runner.py tests/test_longform_projects.py
git commit -m "feat: extend short longform episodes by chapter"
\`\`\`

### Task 4: Present character settings and outcomes in the GUI

**Files:**
- Modify: \`app/gui.py\`: longform variables, load/save validation, confirmation
- Modify: \`app/pipeline_runner.py\`: snapshot fields if needed
- Test: \`tests/test_longform_projects.py\`

**Interfaces:** GUI binds \`project_longform_min_final_chars_var\` and \`project_longform_max_final_chars_var\` to the persisted settings.

- [ ] **Step 1: Write the failing model test**

\`\`\`python
def test_longform_settings_snapshot_uses_final_character_limits():
    snapshot = pipeline_runner._longform_settings_snapshot(
        {"min_final_chars": 22_000, "max_final_chars": 88_000, "batch_episode_count": 5}
    )
    assert snapshot["min_final_chars"] == 22_000
    assert snapshot["max_final_chars"] == 88_000
\`\`\`

- [ ] **Step 2: Run test to verify it fails**

Run: \`pytest tests/test_longform_projects.py::test_longform_settings_snapshot_uses_final_character_limits -v\`

Expected: FAIL because snapshot minute fields remain.

- [ ] **Step 3: Write minimal implementation**

Rename Tk variables and display labels to “启用按字数连续分集”, “洗稿后最少字数”, and “最多字数”. Explain automatic whole-chapter extension. Validate positive integers, show configured character range in the confirmation dialog, and surface book-end/over-limit/successor-started warnings without changing task state.

- [ ] **Step 4: Run test to verify it passes**

Run: \`pytest tests/test_longform_projects.py -k "snapshot_uses_final_character_limits or longform" -v\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`bash
git add app/gui.py app/pipeline_runner.py tests/test_longform_projects.py
git commit -m "feat: show longform character targets in project UI"
\`\`\`

### Task 5: Run regression and the project validation bundle

**Files:**
- Verify: \`tests/test_longform_projects.py\`
- Verify: the safe-validation files listed in \`AGENTS.md\`

- [ ] **Step 1: Run longform tests**

Run: \`pytest tests/test_longform_projects.py -v\`

Expected: PASS.

- [ ] **Step 2: Compile production modules**

Run: \`python3 -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py\`

Expected: exit code 0.

- [ ] **Step 3: Run package compilation and smoke checks**

Run: \`python3 -m compileall app\`, then run the three imports/prints defined in \`AGENTS.md\`.

Expected: exit code 0; upload loader works; schema and browser profile print; secret redaction masks the example.

- [ ] **Step 4: Commit verification fixes only if required**

\`\`\`bash
git add app tests
git commit -m "test: verify longform character episode workflow"
\`\`\`

