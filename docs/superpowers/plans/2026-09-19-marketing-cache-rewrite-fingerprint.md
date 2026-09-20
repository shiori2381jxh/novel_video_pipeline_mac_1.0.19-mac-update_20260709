# Marketing Cache Rewrite Fingerprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure marketing copy and cover prompts are regenerated from rewritten task text rather than source-text-era cache entries.

**Architecture:** `stage_metadata` will select the task-local rewritten text as its marketing evidence when available. Its existing input hash will then reject any cached candidates made from earlier source text.

**Tech Stack:** Python 3, pytest, `app.pipeline_runner` cache helpers.

## Global Constraints

- Do not remove user jobs, covers, videos, settings, or unrelated generated files.
- Preserve existing behavior for tasks without a non-empty `text_rewritten.txt`.
- Never special-case a character name; use content identity.
- Run the AGENTS.md validation bundle after the change.

---

### Task 1: Add the failing stale-cache regression

**Files:**
- Modify: `tests/test_pipeline_rewrite_localization.py`

**Interfaces:**
- Consumes: `pipeline_runner.stage_metadata(novel, job_dir, story_context, segments, on_log)`.
- Produces: a test which places rewritten “沈川” text beside a cache created from “林一” source material and asserts the cache is not reused.

- [ ] Write a test with a task-local `text_rewritten.txt`, a valid preexisting `marketing_candidates.json` keyed to source material, and a fake LLM response based on rewritten material.
- [ ] Run `python -m pytest tests/test_pipeline_rewrite_localization.py -q`; verify the new regression fails because old cache is reused.
- [ ] Add a companion test proving a task without rewritten text continues to use normal `Novel`/segment sampling.

### Task 2: Make rewritten text the marketing evidence

**Files:**
- Modify: `app/pipeline_runner.py:6487-6520`
- Test: `tests/test_pipeline_rewrite_localization.py`

**Interfaces:**
- Consumes: non-empty `job_dir / "text_rewritten.txt"`.
- Produces: both sampled and expanded marketing material from rewritten text; the contents are already included in the existing input hash.

- [ ] Add a small helper that reads non-empty `text_rewritten.txt` and samples it using the project’s existing text-sampling behavior; otherwise it returns the current `sampled_story_input` results.
- [ ] Replace the two direct `sampled_story_input` calls in `stage_metadata` with the helper.
- [ ] Run `python -m pytest tests/test_pipeline_rewrite_localization.py -q`; verify both regression and compatibility tests pass.
- [ ] Inspect `git diff -- app/pipeline_runner.py tests/test_pipeline_rewrite_localization.py` to ensure no unrelated behavior changed.

### Task 3: Run project validation

**Files:**
- Verify: `app/config.py`, `app/gui.py`, `app/pipeline_runner.py`, `app/upload.py`, `app/vendor/stage5_upload_browser.py`, `app/youtube_ad_suitability.py`, `app/updater.py`, `app/update_tab.py`, `scripts/apply_update.py`, `scripts/build_release_package.py`

- [ ] Run the AGENTS.md `py_compile`, `compileall`, and Python smoke-check bundle.
- [ ] Report fresh focused-test and compilation results, and identify unrelated pre-existing dirty files as untouched.
