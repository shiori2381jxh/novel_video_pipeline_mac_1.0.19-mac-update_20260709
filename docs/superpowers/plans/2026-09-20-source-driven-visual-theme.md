# Source-Driven Visual Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every in-video illustration follow the imported novel's genre, era, settings, and events instead of an isekai preset.

**Architecture:** Existing prompt assembly remains intact. The implementation replaces biased prompt text in defaults and stored profiles, and changes the storyboard fallback from an isekai lock to a source-material lock.

**Tech Stack:** Python 3, pytest, JSON configuration files.

## Global Constraints

- No manual genre selector or API/image-provider changes.
- No fixed fantasy, medieval, magic, castle, dungeon, isekai, or light-novel setting.
- Preserve unrelated existing worktree changes.

---

### Task 1: Test and remove the hard-coded fallback lock

**Files:**
- Modify: `tests/test_pipeline_rewrite_localization.py`
- Modify: `app/pipeline_runner.py:10112-10126`

- [ ] Write a regression test that calls `_fallback_storyboard_prompt` with a neutral prefix and asserts its output does not contain `isekai` and tells the model to follow the source world, era, locations, characters, and setting.
- [ ] Run `python -m pytest tests/test_pipeline_rewrite_localization.py -v` and confirm that assertion fails against the current isekai fallback.
- [ ] Replace the sentence `Keep the Japanese isekai light-novel illustration style` with source-grounded wording that forbids importing unrelated people, places, eras, or genre conventions.
- [ ] Re-run the targeted test and confirm it passes.

### Task 2: Test and neutralize bundled defaults

**Files:**
- Modify: `app/config.py:204-309`
- Modify: `data/defaults/settings.template.json`
- Modify: `data/defaults/profile.template.json`
- Modify: `data/defaults/日语推文默认配置.json`
- Modify: `tests/test_historical_snapshot_migration.py`

- [ ] Add a test that joins the visual prompt fields in `DEFAULT_SETTINGS` and asserts it contains none of `isekai`, `异世界`, or `fantasy world`.
- [ ] Run the test and confirm it fails.
- [ ] Make storyboard, image prefix/suffix, character-analysis, character-reference, and cover wording source-driven. The character-analysis prompt must direct the model to infer genre, era, visual style, and recurring background strictly from the imported text; modern, cultivation, historical, and fantasy scenes appear only when source text supports them.
- [ ] Re-run the test and confirm it passes.

### Task 3: Test and neutralize all saved prompt profiles

**Files:**
- Modify: `data/settings.json`
- Modify: `data/profiles/*.json`
- Modify: `tests/test_historical_snapshot_migration.py`

- [ ] Add a test that loads `data/settings.json` and each profile, checks only the image-generation prompt fields, and asserts that none contain `isekai`, `异世界`, or `fantasy world`.
- [ ] Run the test and confirm it fails on current saved values.
- [ ] Replace only those prompt fields in settings and every profile, including `異世界推文1`, with the neutral source-driven values. Do not alter credentials, routes, model choices, or publishing data.
- [ ] Re-run the test and confirm it passes.

### Task 4: Verify the complete change

**Files:**
- Verify: `app/config.py`, `app/pipeline_runner.py`, `app/character_analysis.py`

- [ ] Run `python -m pytest tests/test_historical_snapshot_migration.py tests/test_pipeline_rewrite_localization.py -v`.
- [ ] Run `rg -n -i --glob '*.py' --glob '*.json' 'isekai|异世界|fantasy world' app data/defaults data/settings.json data/profiles` and investigate any remaining non-documentation matches.
- [ ] Run the repository safe validation bundle from `AGENTS.md`.
- [ ] Review `git status --short`; stage no unrelated changes.
