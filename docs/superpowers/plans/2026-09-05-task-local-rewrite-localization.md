# Task-Local Rewrite Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the pipeline's same-language rewrite stage with optional task-local proper-noun localization, cross-batch mappings, quality gates, task artifacts, and GUI controls.

**Architecture:** A new pure `app/rewrite_localization.py` module owns language heuristics, strict JSON parsing, replacement validation, safe application, and residual detection. `pipeline_runner` coordinates that module with the existing LLM route and task files; it keeps old plain-text rewrite behavior when the new option is off. Configuration and the Tk GUI expose safe defaults and persist the controls in normal production profiles.

**Tech Stack:** Python 3.12, existing Tkinter GUI, OpenAI-compatible/Claude text backends, `pytest`, JSON task artifacts.

## Global Constraints

- Preserve Chinese→Chinese and Japanese→Japanese output only; do not add translation.
- `ai_rewrite_proper_noun_localization_enabled` defaults to `false` and old plain-text rewrite must remain compatible when it is off.
- Mapping scope is one task directory only; no profile/global or cross-novel mapping store.
- Supported auto-localization categories are 人名、地名、家族名、组织名、机构名、种族名.
- Never allow an incomplete rewrite or an uncommitted temporary mapping into TTS, subtitles, images, or final task artifacts.
- Do not log API keys or full raw source text beyond the user-authorized task files.
- Existing `AGENTS.md` compile validation bundle remains mandatory after code changes.

---

## File Structure

- Create `app/rewrite_localization.py`: deterministic, dependency-light rewrite protocol helpers and replacement-map validation.
- Create `tests/test_rewrite_localization.py`: unit tests for the new pure helper API.
- Create `tests/test_pipeline_rewrite_localization.py`: mocked-LLM integration tests for batching, artifact commits, retries, fallback, and cleanup.
- Modify `app/config.py`: schema version, safe defaults, migration, and profile persistence behavior for rewrite-localization settings.
- Modify `app/gui.py`: rewrite controls, typed form parsing, and explanatory copy.
- Modify `app/pipeline_runner.py`: use structured rewrite mode when enabled, persist artifacts/checkpoints atomically, and clear artifacts on reset.
- Modify `docs/module_prompt_editing_guide.md`: operator-facing configuration and artifact documentation.

## Public Helper Interfaces

`app/rewrite_localization.py` will export these exact interfaces:

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class RewriteLanguage:
    code: str              # "ja", "zh", or "unknown"
    confidence: float      # 0.0 through 1.0
    warning: str = ""

@dataclass(frozen=True)
class Replacement:
    category: str
    source: str
    target: str
    notes: str
    batch: int
    local_replace_safe: bool

@dataclass(frozen=True)
class RewriteBatchResult:
    rewritten_text: str
    replacements: tuple[Replacement, ...]
    warnings: tuple[str, ...]

def detect_rewrite_language(text: str) -> RewriteLanguage: ...
def build_structured_rewrite_prompt(*, skill: str, language: RewriteLanguage,
                                    known_replacements: list[Replacement],
                                    batch_index: int, batch_count: int) -> tuple[str, str]: ...
def parse_structured_rewrite_response(raw: str, *, source_text: str,
                                      batch_index: int,
                                      known_replacements: list[Replacement]) -> RewriteBatchResult: ...
def validate_rewrite_quality(*, source_text: str, rewritten_text: str,
                             language: RewriteLanguage, min_ratio: float,
                             max_ratio: float) -> list[str]: ...
def apply_replacements(text: str, replacements: list[Replacement]) -> str: ...
def find_residual_sources(text: str, replacements: list[Replacement]) -> list[str]: ...
```

`pipeline_runner._ai_rewrite_paragraphs` will accept keyword-only structured-mode arguments and return a `RewriteRunResult` dataclass defined in `pipeline_runner`, containing final text, replacements, warnings, language, batch reports, and a success flag. Existing callers keep their current plain-text path.

### Task 1: Implement the deterministic rewrite-localization protocol helpers

**Files:**

- Create: `app/rewrite_localization.py`
- Create: `tests/test_rewrite_localization.py`

**Interfaces:**

- Consumes: standard library `dataclasses`, `json`, `re`, and the interface definitions above.
- Produces: parseable structured rewrite results and deterministic mapping/quality helpers used by `pipeline_runner` in Task 3.

- [ ] **Step 1: Write the failing helper tests**

Create `tests/test_rewrite_localization.py` with tests that establish each contract before implementation:

```python
from app.rewrite_localization import (
    Replacement, apply_replacements, detect_rewrite_language,
    find_residual_sources, parse_structured_rewrite_response,
    validate_rewrite_quality,
)

def test_detect_rewrite_language_distinguishes_japanese_and_chinese():
    assert detect_rewrite_language("彼女は駅へ向かった。理由は知らない。").code == "ja"
    assert detect_rewrite_language("她走向车站，却不知道原因。").code == "zh"

def test_parse_response_preserves_known_mapping_and_rejects_conflict():
    known = [Replacement("人名", "阿明", "陈舟", "", 1, True)]
    raw = '{"rewritten_text":"阿明走进了房间。","new_replacements":[{"category":"人名","source":"阿明","target":"周明","notes":""}],"warnings":[]}'
    with pytest.raises(ValueError, match="冲突"):
        parse_structured_rewrite_response(raw, source_text="阿明走进了房间。", batch_index=2, known_replacements=known)

def test_apply_replacements_is_longest_first_and_reports_residuals():
    replacements = [
        Replacement("人名", "王", "赵", "", 1, False),
        Replacement("人名", "王小明", "陈舟", "", 1, True),
    ]
    assert apply_replacements("王小明见到了王。", replacements) == "陈舟见到了王。"
    assert find_residual_sources("陈舟见到了王。", replacements) == ["王"]

def test_quality_rejects_empty_summary_and_wrong_language():
    ja = detect_rewrite_language("彼女は扉を開けた。雨が降っていた。")
    errors = validate_rewrite_quality(source_text="彼女は扉を開けた。雨が降っていた。", rewritten_text="要約", language=ja, min_ratio=0.75, max_ratio=1.35)
    assert any("长度" in error for error in errors)
    assert any("日语" in error for error in errors)
```

- [ ] **Step 2: Run the helper test file to verify failure**

Run: `python -m pytest tests/test_rewrite_localization.py -v`

Expected: collection error because `app.rewrite_localization` does not yet exist.

- [ ] **Step 3: Implement the minimal pure module**

Create `app/rewrite_localization.py` with the specified dataclasses and functions. Implement these exact rules:

```python
ALLOWED_REPLACEMENT_CATEGORIES = frozenset({"人名", "地名", "家族名", "组织名", "机构名", "种族名"})

def apply_replacements(text: str, replacements: list[Replacement]) -> str:
    result = str(text)
    for item in sorted(
        (item for item in replacements if item.local_replace_safe),
        key=lambda item: (-len(item.source), item.source),
    ):
        result = result.replace(item.source, item.target)
    return result
```

Make Japanese classification depend on the share of hiragana/katakana in meaningful non-space characters; classify predominantly CJK text with no supporting kana as Chinese; return `unknown` rather than guessing for short/low-signal inputs. Parse JSON with code-fence removal, require non-empty `rewritten_text`, require arrays for `new_replacements` and `warnings`, and reject source/target conflicts against the existing map. Only set `local_replace_safe=True` for multi-character source strings that are not obviously generic; keep one-character mappings as model instructions and residual warnings only. Reject source values missing from `source_text`, unknown categories, empty/overlong fields, identical names, and targets that are materially too similar after NFKC compaction.

Implement quality checks for empty results, configured length ratios, and high-confidence source-language mismatches. Return user-facing Chinese error strings rather than raising for normal quality failures.

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `python -m pytest tests/test_rewrite_localization.py -v`

Expected: PASS.

- [ ] **Step 5: Add coverage for malformed JSON and source validation**

Append these cases to the same test module:

```python
@pytest.mark.parametrize("raw", ["", "not json", '{"rewritten_text":"正文"}'])
def test_parse_response_rejects_invalid_protocol(raw):
    with pytest.raises(ValueError):
        parse_structured_rewrite_response(raw, source_text="原文", batch_index=1, known_replacements=[])

def test_parse_response_rejects_name_missing_from_source():
    raw = '{"rewritten_text":"正文","new_replacements":[{"category":"人名","source":"不存在","target":"新名","notes":""}],"warnings":[]}'
    with pytest.raises(ValueError, match="原文"):
        parse_structured_rewrite_response(raw, source_text="实际正文", batch_index=1, known_replacements=[])
```

Run: `python -m pytest tests/test_rewrite_localization.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the isolated helper deliverable when a valid Git worktree is available**

Run: `git status --short && git add app/rewrite_localization.py tests/test_rewrite_localization.py && git commit -m "feat: add rewrite localization protocol helpers"`

Expected: a commit containing only Task 1 files. In the currently supplied workspace Git reports no valid repository; preserve the staged-free files and record that fact instead of fabricating a commit.

### Task 2: Add safe configuration defaults and GUI controls

**Files:**

- Modify: `app/config.py:29, 361-370, _apply_compat_migrations`
- Modify: `app/gui.py:1863-1867, _config_key_sets`
- Create: `tests/test_rewrite_localization_config.py`

**Interfaces:**

- Consumes: `DEFAULT_SETTINGS` and GUI form key sets.
- Produces: persisted `ai_rewrite_proper_noun_localization_enabled`, `ai_rewrite_min_length_ratio`, and `ai_rewrite_max_length_ratio` values for Task 3.

- [ ] **Step 1: Write failing defaults and form-type tests**

Create `tests/test_rewrite_localization_config.py`:

```python
from app.config import DEFAULT_SETTINGS
from app.gui import App

def test_rewrite_localization_defaults_are_safe():
    assert DEFAULT_SETTINGS["ai_rewrite_proper_noun_localization_enabled"] is False
    assert DEFAULT_SETTINGS["ai_rewrite_min_length_ratio"] == 0.75
    assert DEFAULT_SETTINGS["ai_rewrite_max_length_ratio"] == 1.35

def test_gui_treats_rewrite_localization_as_boolean_and_ratios_as_float():
    int_keys, float_keys, bool_keys = App._config_key_sets(object.__new__(App))
    assert "ai_rewrite_proper_noun_localization_enabled" in bool_keys
    assert {"ai_rewrite_min_length_ratio", "ai_rewrite_max_length_ratio"} <= float_keys
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_rewrite_localization_config.py -v`

Expected: FAIL with missing default keys.

- [ ] **Step 3: Add defaults, migration, and controls**

In `app/config.py`, increase `SETTINGS_SCHEMA_VERSION` by one and add the three defaults adjacent to `ai_rewrite_enabled`. In `_apply_compat_migrations`, add a `saved_version < 56` block that uses `setdefault` for every new field so modified legacy prompts and preferences are untouched.

In `app/gui.py`, add the new checkbox immediately below `AI 洗稿改写`, add two ratio rows below the batch-size row, and rename the label passed to `textrow` to `洗稿 Skill（可编辑）`. Place a concise explanatory `ttk.Label` below the checkbox: `开启后在当前任务内统一改写人名、地名等专名；中文仍输出中文，日语仍输出日语。` Add the boolean to `bool_keys` and both ratio settings to `float_keys`.

- [ ] **Step 4: Run configuration tests and syntax validation**

Run: `python -m pytest tests/test_rewrite_localization_config.py -v; python -m py_compile app/config.py app/gui.py`

Expected: PASS and no compiler output.

- [ ] **Step 5: Commit the configuration/UI deliverable when Git is available**

Run: `git add app/config.py app/gui.py tests/test_rewrite_localization_config.py && git commit -m "feat: add rewrite localization controls"`

Expected: a commit containing only Task 2 files, or a recorded no-repository result in this workspace.

### Task 3: Integrate structured rewriting, artifacts, retry, and atomic fallback

**Files:**

- Modify: `app/pipeline_runner.py:imports, _rewrite_story_text, _ai_rewrite_paragraphs, reset_from_clean_reuse_images`
- Create: `tests/test_pipeline_rewrite_localization.py`

**Interfaces:**

- Consumes: Task 1 helpers and Task 2 config values.
- Produces: `text_rewritten.txt`, `text_rewrite_report.json`, `text_rewrite_replacements.json`, and transient `text_rewrite_checkpoint.json`.

- [ ] **Step 1: Write failing integration tests with a fake LLM**

Create `tests/test_pipeline_rewrite_localization.py`. Monkeypatch `pipeline_runner.LLMBackend` with a fake whose `storyboard()` records requests and returns queued responses. Include these tests:

```python
def test_structured_rewrite_passes_prior_mapping_to_next_batch(monkeypatch, tmp_path, configured_rewrite):
    replies = [
        '{"rewritten_text":"旧名进入房间。","new_replacements":[{"category":"人名","source":"旧名","target":"新名","notes":""}],"warnings":[]}',
        '{"rewritten_text":"旧名离开房间。","new_replacements":[],"warnings":[]}',
    ]
    fake = install_fake_llm(monkeypatch, replies)
    result = pipeline_runner._rewrite_story_text("旧名进入房间。\n\n旧名离开房间。", job_dir=tmp_path)
    assert result == "新名进入房间。\n\n新名离开房间。"
    assert "新名" in fake.requests[1]
    assert (tmp_path / "text_rewrite_replacements.json").is_file()
    assert not (tmp_path / "text_rewrite_checkpoint.json").exists()

def test_invalid_structured_reply_retries_then_falls_back_without_final_artifacts(monkeypatch, tmp_path, configured_rewrite):
    install_fake_llm(monkeypatch, ["not json", "still not json"])
    source = "田中は駅へ向かった。"
    assert pipeline_runner._rewrite_story_text(source, job_dir=tmp_path) == source
    assert not (tmp_path / "text_rewritten.txt").exists()
    assert not (tmp_path / "text_rewrite_replacements.json").exists()

def test_reset_from_clean_removes_rewrite_localization_artifacts(tmp_path, monkeypatch):
    # Arrange the existing reset preconditions and write the three artifacts.
    # Assert all three task-local localization files are removed.
```

Make `configured_rewrite` monkeypatch `config.get`/settings so `ai_rewrite_enabled` and `ai_rewrite_proper_noun_localization_enabled` are true, batch size forces two batches, and length ratios permit the fixture text.

- [ ] **Step 2: Run the integration tests to verify failure**

Run: `python -m pytest tests/test_pipeline_rewrite_localization.py -v`

Expected: FAIL because structured rewrite behavior and artifacts do not exist.

- [ ] **Step 3: Add a run-result container and artifact constants**

Near existing pipeline task constants define:

```python
REWRITE_REPLACEMENTS_FILE = "text_rewrite_replacements.json"
REWRITE_CHECKPOINT_FILE = "text_rewrite_checkpoint.json"

@dataclass
class RewriteRunResult:
    text: str
    replacements: list[Replacement]
    warnings: list[str]
    language: RewriteLanguage
    batches: list[dict]
```

Import `dataclass` and Task 1 helper types/functions. Extend every pipeline cleanup list that currently removes `text_rewritten.txt`/`text_rewrite_report.json` to also remove `REWRITE_REPLACEMENTS_FILE` and `REWRITE_CHECKPOINT_FILE`.

- [ ] **Step 4: Implement structured batch execution without altering plain mode**

Refactor `_ai_rewrite_paragraphs` into two explicit branches:

```python
if not bool(config.get("ai_rewrite_proper_noun_localization_enabled", False)):
    return _ai_rewrite_plaintext_batches(paragraphs, on_log)
return _ai_rewrite_structured_batches(paragraphs, on_log, job_dir=job_dir)
```

The plaintext branch must retain the existing request and fence stripping unchanged. The structured branch must detect language from the full source, construct prompts through `build_structured_rewrite_prompt`, process batches sequentially, parse each response, validate each response against the current batch, merge only non-conflicting mappings, and persist a checkpoint after each complete valid batch.

For a parse or quality error, append a strict retry suffix requesting valid JSON with all required fields and run exactly one additional request for that same batch. For a second error, raise `ValueError`; `_rewrite_story_text` catches it, logs the safe fallback, deletes the checkpoint, and returns the original source without writing final rewrite artifacts.

- [ ] **Step 5: Atomically write final results and reports**

In `_rewrite_story_text`, write the old report and `text_rewritten.txt` only after structured execution returns every batch successfully. For structured mode, locally apply safe mappings to the joined text, calculate residuals, and write this JSON:

```python
{
  "language": {"code": result.language.code, "confidence": result.language.confidence, "warning": result.language.warning},
  "replacements": [asdict(item) for item in result.replacements],
  "warnings": result.warnings,
  "residual_sources": residuals,
  "batches": result.batches
}
```

Add language, mapping count, residual count, quality ratios, and structured-mode state to `text_rewrite_report.json`. Use an existing `_write_json` helper with a temporary path plus `replace()` if the helper is not already atomic; do not leave a partially written final JSON. Delete the checkpoint only after both final artifacts have written successfully.

- [ ] **Step 6: Run integration tests and existing subtitle tests**

Run: `python -m pytest tests/test_pipeline_rewrite_localization.py tests/test_stage6_compose_subtitles.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the pipeline deliverable when Git is available**

Run: `git add app/pipeline_runner.py tests/test_pipeline_rewrite_localization.py && git commit -m "feat: localize proper nouns during task rewrite"`

Expected: a commit containing only Task 3 files, or a recorded no-repository result in this workspace.

### Task 4: Document operation and execute project validation

**Files:**

- Modify: `docs/module_prompt_editing_guide.md:洗稿提示词怎么改`
- Modify: `README.md:AI 洗稿、朗读净化与自动读音`

**Interfaces:**

- Consumes: final GUI labels and task artifacts from Tasks 2–3.
- Produces: accurate instructions for enabling, auditing, and safely rerunning task-local rewrite localization.

- [ ] **Step 1: Add documentation assertions first**

Create `tests/test_rewrite_localization_docs.py`:

```python
from pathlib import Path

def test_operator_docs_describe_task_local_rewrite_localization():
    root = Path(__file__).parents[1]
    guide = (root / "docs" / "module_prompt_editing_guide.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    for text in (guide, readme):
        assert "专名本地化" in text
        assert "text_rewrite_replacements.json" in text
        assert "任务内" in text
```

- [ ] **Step 2: Run the documentation test to verify failure**

Run: `python -m pytest tests/test_rewrite_localization_docs.py -v`

Expected: FAIL because the new operator guidance does not yet exist.

- [ ] **Step 3: Document exact operator behavior**

In both documents, describe:

- The toggle is opt-in and preserves the original same-language behavior when off.
- The Skill determines rewrite style; it should explicitly preserve events, causality, viewpoint, conclusion, and information volume.
- Chinese input gets Chinese-style names and Japanese input gets Japanese-style names; no translation occurs.
- Mappings live in a task only and are written to `text_rewrite_replacements.json` with residual warnings.
- “重做洗稿和配音” discards the task mapping and produces a new one under the current Skill/settings.
- One-character/generic name-like sources are not blindly local-replaced and must be reviewed in the report.

- [ ] **Step 4: Run all feature tests and mandatory validation**

Run:

```powershell
python -m pytest tests/test_rewrite_localization.py tests/test_rewrite_localization_config.py tests/test_pipeline_rewrite_localization.py tests/test_rewrite_localization_docs.py tests/test_stage6_compose_subtitles.py -v
python -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/rewrite_localization.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py
python -m compileall app
@'
from app import upload
mod = upload._load()
print(mod.__name__, hasattr(mod, "upload_via_browser"), hasattr(mod, "_select_file_with_playwright"))
from app.config import config
print(config.get("settings_schema_version"), config.get("browser_chrome_profile"))
from app.utils.secrets import redact_secret_text
print(redact_secret_text("Bearer sk-example1234567890"))
'@ | python -
```

Expected: every test passes, compilation is silent, the upload loader prints three `True`/expected values, and the final line redacts the sample key.

- [ ] **Step 5: Inspect only relevant changes**

Run: `git diff -- app/rewrite_localization.py app/config.py app/gui.py app/pipeline_runner.py tests docs README.md`

Expected: only the task-local rewrite-localization feature and its documentation are present; do not touch unrelated dirty files.

- [ ] **Step 6: Commit documentation and verification changes when Git is available**

Run: `git add README.md docs/module_prompt_editing_guide.md tests/test_rewrite_localization_docs.py && git commit -m "docs: explain task-local rewrite localization"`

Expected: a commit containing Task 4 files, or a recorded no-repository result in this workspace.

## Plan Self-Review

- Spec coverage: Tasks 1 and 3 implement language preservation, mapping memory, validation, residual checking, retries, fallback, checkpointing, and artifacts. Task 2 implements safe opt-in configuration and GUI persistence. Task 4 covers operator docs and the required project validation bundle.
- Completeness scan: no deferred implementation steps are present; every test and production implementation step names files, commands, and expected behavior.
- Type consistency: `Replacement`, `RewriteLanguage`, and `RewriteBatchResult` originate in Task 1; Task 3 imports them and produces `RewriteRunResult`; config key names are identical across Tasks 2–3; artifact constants are used in pipeline and reset steps.
