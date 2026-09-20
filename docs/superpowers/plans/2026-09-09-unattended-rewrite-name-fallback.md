# Unattended Rewrite Name Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure enabled proper-name localization never silently completes with a rejected near-name mapping.

**Architecture:** Add deterministic fallback-name helpers in `app/rewrite_localization.py`, then use them from the structured batch flow in `app/pipeline_runner.py` after model retries. Existing job reports and longform ledger code persist the mapping for later episodes.

**Tech Stack:** Python 3, pytest, JSON job artifacts.

## Global Constraints

- No dialog or manual input may block GUI, workers, or queues.
- A fallback is deterministic for the same source/category, visibly distinct, and non-conflicting.
- Preserve plaintext rewriting when localization is disabled.
- Persist automatic mappings in existing reports and the longform ledger.

---

### Task 1: Add deterministic fallback mapping helpers

**Files:**
- Modify: `app/rewrite_localization.py:1-285`
- Test: `tests/test_rewrite_localization.py`

**Interfaces:**
- Produces `extract_rejected_replacement_sources(raw: str, source_text: str) -> list[dict[str, str]]`.
- Produces `build_deterministic_fallback_replacements(candidates, source_text, batch_index, known_replacements) -> list[Replacement]`.

- [ ] **Step 1: Write failing tests**

Test an invalid `林一 → 林二` response: extraction yields `林一`; two fallback calls yield the same valid, non-`林一` target. Test that a source absent from the batch is discarded and that existing targets are avoided.

- [ ] **Step 2: Run test to verify failure**

Run `python -m pytest tests/test_rewrite_localization.py -q`. Expected: FAIL because the helpers are absent.

- [ ] **Step 3: Implement the helpers**

Parse only optional JSON replacement entries whose allowed-category source occurs in the batch. Hash source plus category into curated Chinese/Japanese target pools; probe to avoid known targets and `_names_too_similar`; construct each result with `_validate_replacement` and `notes="自动兜底：模型改名校验失败"`.

- [ ] **Step 4: Run test to verify success**

Run `python -m pytest tests/test_rewrite_localization.py -q`. Expected: PASS.

### Task 2: Repair structured-batch failures without an operator

**Files:**
- Modify: `app/pipeline_runner.py:75-95,2678-2790,1980-2070`
- Test: `tests/test_pipeline_rewrite_localization.py`

**Interfaces:**
- Consumes both Task 1 helpers.
- Produces fallback `Replacement` records in `RewriteRunResult.replacements`, which existing report and ledger code persists.

- [ ] **Step 1: Write failing tests**

Test two identical `林一 → 林二` invalid replies: the rewritten output contains a fallback target and `text_rewrite_replacements.json` contains the mapping with an `自动兜底` note. Test an invalid reply followed by an empty-map retry: a third, strict JSON-only name-identification request is made rather than completing a zero-mapping localization run.

- [ ] **Step 2: Run test to verify failure**

Run `python -m pytest tests/test_pipeline_rewrite_localization.py -q`. Expected: FAIL because current retries retain the original text.

- [ ] **Step 3: Implement the repair flow**

Retain candidate sources from rejected replies. After normal retries, create deterministic fallback mappings when candidates exist and the rewritten text passed quality checks. If no candidate exists and the batch has neither a new nor known mapping, make one automatic JSON-only name-identification request and validate it through the ordinary parser. If that cannot identify a source, fail rather than complete a zero-mapping localization run. Add repair warnings to batch and replacement reports.

- [ ] **Step 4: Verify focused tests and the project bundle**

Run `python -m pytest tests/test_pipeline_rewrite_localization.py tests/test_rewrite_localization.py -q`, then run the validation bundle in `AGENTS.md`. Expected: all commands exit 0.

- [ ] **Step 5: Commit if a repository becomes available**

The current workspace is not a Git repository; otherwise commit the four changed Python/test files with message `feat: recover rewrite names without operator input`.
