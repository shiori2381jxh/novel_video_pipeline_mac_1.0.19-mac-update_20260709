# 可配置营销输出与日语读音分离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make marketing output quantity profile-configurable, remove Japanese inline readings from all marketing/cover text, and lock the selected text-account routing behavior with regression tests.

**Architecture:** `app.text_annotations` exposes one presentation-only Japanese reading cleaner. `app.pipeline_runner` obtains one validated marketing contract from configuration and uses it for model request instructions, parsing, validation, fallback data, cached metadata, candidate text, and cover context. `app.config` owns defaults/migration and `app.gui` exposes the contract fields in Batch & Upload.

**Tech Stack:** Python 3.12, Tkinter, pytest, JSON profiles.

## Global Constraints

- Japanese `written（kana）` must become `written` in marketing titles, summaries, tags, cover inputs, cache, metadata, candidate files, and local fallback; TTS and subtitle behavior must remain unchanged.
- Marketing title length is controlled only by each profile’s editable prompt. Runtime must not hard-code, rewrite, validate, truncate, or pad title lengths.
- Configurable quantities have defaults: titles `3`, synopses `1`, tags `5–10`; title and synopsis count floor is `1`.
- Selected text account `1–6` overrides default text API for every text-generation role. Default text API is used only when no text account is selected.
- Preserve non-overlapping pending workspace changes; the user explicitly authorizes replacing only changes overlapping this marketing/configuration scope.
- Do not modify existing task snapshots, media, uploaded titles, or TTS/subtitle source data.

---

### Task 1: Add presentation-only Japanese annotation cleaning and the marketing-contract configuration

**Files:**
- Modify: `app/text_annotations.py`
- Modify: `app/config.py: SETTINGS_SCHEMA_VERSION, DEFAULT_SETTINGS, _apply_compat_migrations`
- Modify: `data/defaults/settings.template.json`
- Modify: `data/defaults/profile.template.json`
- Modify: `data/defaults/日语推文默认配置.json`
- Modify: `data/profiles/*.json`
- Create: `tests/test_marketing_contract.py`

**Interfaces:**
- Produces: `marketing_display_text(text: str) -> str`, which removes valid inline Japanese readings while retaining the written word.
- Produces: `marketing_contract(values: Mapping[str, Any] | None = None) -> dict[str, int]`, returning `title_count`, `synopsis_count`, `tag_min_count`, and `tag_max_count` with validated floors/range.
- Consumes: existing `_FURIGANA_RE` in `app.text_annotations` and the config singleton’s storage/migration pattern.

- [ ] **Step 1: Write the failing presentation-cleaner and default-contract tests**

```python
from app.config import marketing_contract
from app.text_annotations import marketing_display_text, subtitle_display_text, tts_narration_text


def test_marketing_display_text_removes_only_inline_japanese_readings():
    source = "蒼真（そうま）は朝陽（あさひ）を見た。"
    assert marketing_display_text(source) == "蒼真は朝陽を見た。"
    assert subtitle_display_text(source) == "蒼真は朝陽を見た。"
    assert tts_narration_text(source) == "そうまはあさひを見た。"


def test_marketing_contract_defaults_and_clamps_required_counts():
    assert marketing_contract({}) == {
        "title_count": 3, "synopsis_count": 1, "tag_min_count": 5, "tag_max_count": 10,
    }
    assert marketing_contract({
        "marketing_title_count": 0,
        "marketing_synopsis_count": -1,
        "marketing_tag_min_count": 9,
        "marketing_tag_max_count": 2,
    }) == {"title_count": 1, "synopsis_count": 1, "tag_min_count": 9, "tag_max_count": 9}
```

- [ ] **Step 2: Run the focused test and verify it fails because the public cleaner/contract APIs do not exist**

Run: `python -m pytest tests/test_marketing_contract.py -v`

Expected: FAIL during import for `marketing_display_text` and `marketing_contract`.

- [ ] **Step 3: Implement the cleaner, contract normalization, schema migration, and profile defaults**

```python
# app/text_annotations.py
def marketing_display_text(text: str) -> str:
    return _FURIGANA_RE.sub(lambda match: match.group("written"), str(text or ""))

# app/config.py
def marketing_contract(values: Mapping[str, Any] | None = None) -> dict[str, int]:
    source = values if values is not None else config.data
    title_count = max(1, _to_int(source.get("marketing_title_count"), 3))
    synopsis_count = max(1, _to_int(source.get("marketing_synopsis_count"), 1))
    tag_min = max(0, _to_int(source.get("marketing_tag_min_count"), 5))
    tag_max = max(tag_min, _to_int(source.get("marketing_tag_max_count"), 10))
    return {"title_count": title_count, "synopsis_count": synopsis_count, "tag_min_count": tag_min, "tag_max_count": tag_max}
```

Set the four fields in `DEFAULT_SETTINGS`, increase schema version, migrate missing/invalid old values, and remove old title-character controls from marketing behavior only. Update templates and every existing profile’s four fields to `3/1/5/10`; update their marketing prompts and JSON examples to request those same quantities without inventing a runtime character limit.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m pytest tests/test_marketing_contract.py -v`

Expected: PASS for the cleaner and contract normalization cases.

- [ ] **Step 5: Inspect the task-local diff without committing yet**

```bash
git diff -- app/text_annotations.py app/config.py data/defaults/settings.template.json data/defaults/profile.template.json data/defaults/日语推文默认配置.json data/profiles tests/test_marketing_contract.py
```

Expected: only the cleaner, contract defaults/migration, and explicitly requested profile defaults are present. Keep these changes uncommitted until Task 4 so the user-requested implementation lands in one integrated code commit.

### Task 2: Drive all marketing generation and cover data with the contract

**Files:**
- Modify: `app/pipeline_runner.py: _candidate_tags, _parse_marketing_candidates, _marketing_validation_error, _fallback_marketing_candidates, _write_marketing_candidates_text, _metadata_has_marketing_candidates, stage_metadata, _cover_marketing_bundle, _build_cover_prompt`
- Modify: `tests/test_marketing_contract.py`
- Modify: `tests/test_pipeline_rewrite_localization.py`

**Interfaces:**
- Consumes: `marketing_display_text`, `marketing_contract`, and a contract dictionary with `title_count`, `synopsis_count`, `tag_min_count`, `tag_max_count`.
- Produces: marketing bundles whose `titles`, `synopses`, and `tags` exactly satisfy the selected contract; all user-facing strings are display-cleaned.
- Preserves: optional `short_script` behavior and existing factual/topic validation.

- [ ] **Step 1: Write failing dynamic-contract tests**

```python
def test_marketing_parser_and_validation_follow_configured_counts(monkeypatch):
    monkeypatch.setattr(pipeline_runner, "_marketing_contract", lambda: {
        "title_count": 2, "synopsis_count": 3, "tag_min_count": 4, "tag_max_count": 6,
    })
    bundle = pipeline_runner._parse_marketing_candidates({
        "titles": ["蒼真（そうま）の告白", "朝陽（あさひ）の返事"],
        "synopses": ["概要一", "概要二", "概要三"],
        "tags": ["#BL", "#学園", "#幼なじみ", "#片思い"],
    })
    assert bundle["titles"] == ["蒼真の告白", "朝陽の返事"]
    assert bundle["synopses"] == ["概要一", "概要二", "概要三"]
    assert pipeline_runner._marketing_validation_error(bundle) == ""


def test_marketing_validation_does_not_enforce_legacy_title_character_range(monkeypatch):
    monkeypatch.setattr(pipeline_runner, "_marketing_contract", lambda: {
        "title_count": 1, "synopsis_count": 1, "tag_min_count": 1, "tag_max_count": 2,
    })
    assert pipeline_runner._marketing_validation_error({
        "titles": ["短い"], "synopses": ["概要"], "tags": ["#タグ"],
    }) == ""
```

- [ ] **Step 2: Run the focused tests and verify they fail under the fixed 3/2/10–15 contract**

Run: `python -m pytest tests/test_marketing_contract.py -v`

Expected: FAIL because parser truncates to 3/2, validation requires fixed counts/lengths, and no marketing contract helper exists in the pipeline.

- [ ] **Step 3: Implement contract-based generation end to end**

```python
def _marketing_contract() -> dict[str, int]:
    return config.marketing_contract()

def _marketing_validation_error(bundle: dict, contract: dict | None = None) -> str:
    rules = contract or _marketing_contract()
    # require exactly rules["title_count"] and rules["synopsis_count"];
    # require tags in [rules["tag_min_count"], rules["tag_max_count"]];
    # retain duplicate/source-wrapper checks; do not inspect character lengths.
```

Use the contract when truncating parsed fields, limiting tags, building retry feedback and JSON shape, creating fallbacks, writing TXT candidate labels, checking `metadata`, and forming `input_hash`. Build a dynamic JSON example from the configured counts rather than replacing the editable prompt’s text. Apply `marketing_display_text` to story material, parsed candidates, fallback data, metadata, candidate TXT values, `_cover_marketing_bundle`, and `_build_cover_prompt` context. Keep enough fallback source sentences to create any configured positive count, with stable de-duplication only where source material supplies alternatives.

Update existing tests whose fixtures assume 2 synopses so they use the configured/default contract intentionally.

- [ ] **Step 4: Run focused marketing and furigana regression tests and verify they pass**

Run: `python -m pytest tests/test_marketing_contract.py tests/test_japanese_furigana.py tests/test_pipeline_rewrite_localization.py -v`

Expected: PASS; dynamic counts work, old title length is not enforced, display text loses readings only outside TTS, and manual cover regeneration remains compatible.

- [ ] **Step 5: Inspect the pipeline diff without committing yet**

```bash
git diff -- app/pipeline_runner.py tests/test_marketing_contract.py tests/test_pipeline_rewrite_localization.py
```

Expected: no fixed marketing quantities or title-character constraints remain in the execution path, while unrelated pipeline changes remain distinguishable for Task 4’s authorized-overlap review.

### Task 3: Expose contract fields in Batch & Upload and lock text-account routing

**Files:**
- Modify: `app/gui.py: Batch & Upload section, numeric field persistence, marketing-regeneration confirmation copy`
- Modify: `tests/test_marketing_contract.py`
- Modify: `tests/test_gui_scroll_collapse.py` only if existing GUI construction tests require the new controls

**Interfaces:**
- Consumes: the four `marketing_*_count` settings and `pipeline_runner._llm_route_settings()`.
- Produces: editable Batch & Upload controls with local validation and dynamic confirmation wording.
- Preserves: selected `llm_relay_station` behavior; no image account is used for text jobs.

- [ ] **Step 1: Write failing GUI/config-route tests**

```python
def test_selected_text_account_overrides_default_route(monkeypatch):
    values = {
        "ai_api_enabled": True, "ai_api_base_url": "https://default.example/v1",
        "ai_api_key": "default-key", "ai_api_text_model": "default-model",
        "llm_provider": "openai", "llm_base_url": "https://legacy.example/v1",
        "llm_api_key": "legacy-key", "llm_model": "legacy-model",
        "relay_station_count": 1, "llm_relay_station": 1,
        "relay_station_1_base_url": "https://text.example/v1",
        "relay_station_1_api_key": "text-key", "relay_station_1_text_model": "text-model",
    }
    monkeypatch.setattr(pipeline_runner.config, "get", values.get)
    monkeypatch.setattr(pipeline_runner.config, "llm_provider", "openai")
    monkeypatch.setattr(pipeline_runner.config, "llm_base_url", values["llm_base_url"])
    monkeypatch.setattr(pipeline_runner.config, "llm_api_key", values["llm_api_key"])
    monkeypatch.setattr(pipeline_runner.config, "llm_model", values["llm_model"])
    assert pipeline_runner._llm_route_settings()["base_url"] == "https://text.example/v1"


def test_marketing_regeneration_message_uses_current_contract():
    assert PipelineGUI._marketing_regeneration_message({
        "title_count": 2, "synopsis_count": 1, "tag_min_count": 5, "tag_max_count": 10,
    }).startswith("将使用当前设置，为选中的")
```

- [ ] **Step 2: Run the focused tests and verify the GUI helper test fails before implementation**

Run: `python -m pytest tests/test_marketing_contract.py -v`

Expected: FAIL for missing `_marketing_regeneration_message`; selected-account route test remains a guard for existing behavior.

- [ ] **Step 3: Replace old fixed title-character GUI controls with contract controls**

```python
# In the Batch & Upload section
row("候选标题数量", "marketing_title_count", "3")
row("候选概要数量", "marketing_synopsis_count", "1")
row("标签最少数量", "marketing_tag_min_count", "5")
row("标签最多数量", "marketing_tag_max_count", "10")

@staticmethod
def _marketing_regeneration_message(contract: dict[str, int]) -> str:
    return (
        "将使用当前设置，为选中的 {count} 个任务重新生成 "
        f"{contract['title_count']} 个标题、{contract['synopsis_count']} 个概梗和 "
        f"{contract['tag_min_count']}–{contract['tag_max_count']} 个内容标签。"
    )
```

Include the fields in the GUI’s integer conversion list. Before applying/saving settings, reject zero/negative title or synopsis counts and inverted tag ranges with a message that names the invalid field. Use the helper in the confirmation dialog. Do not alter the existing text-account combo or route code unless the route regression test exposes a defect.

- [ ] **Step 4: Run the GUI and route regression tests and verify they pass**

Run: `python -m pytest tests/test_marketing_contract.py tests/test_gui_scroll_collapse.py -v`

Expected: PASS; Batch & Upload has dynamic marketing configuration, and selecting a text account resolves to that account.

- [ ] **Step 5: Inspect the GUI diff without committing yet**

```bash
git diff -- app/gui.py tests/test_marketing_contract.py tests/test_gui_scroll_collapse.py
```

Expected: the old title-character widgets are gone from Batch & Upload, the four count controls are present, and only the user-authorized overlapping GUI changes will be included in Task 4’s single code commit.

### Task 4: Integrate authorized overlapping workspace changes and run full validation

**Files:**
- Modify: only approved overlapping hunks in `app/config.py`, `app/gui.py`, `app/pipeline_runner.py`, templates, profiles, and related tests
- Inspect: `git diff --check`, `git diff --cached`, `git status --short`

**Interfaces:**
- Consumes: Task 1–3 contract APIs and existing pending changes.
- Produces: one integrated commit that includes the user-authorized overlap resolution without unrelated workspace changes.

- [ ] **Step 1: Review every remaining overlapping hunk against the contract requirements**

```bash
git diff -- app/config.py app/gui.py app/pipeline_runner.py data/defaults data/profiles tests
```

Classify each hunk as required by this feature, compatible and retained, or conflicting and replaced. Do not stage unrelated files, deleted utilities, job data, cache directories, or other feature work.

- [ ] **Step 2: Run the project’s safe validation bundle**

Run:

```bash
python -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py
python -m compileall app
python -m pytest tests/test_marketing_contract.py tests/test_japanese_furigana.py tests/test_pipeline_rewrite_localization.py tests/test_gui_scroll_collapse.py -v
```

Expected: every command exits `0`, and the focused pytest run has no failures.

- [ ] **Step 3: Inspect exactly what will be committed**

```bash
git diff --check
git status --short
git diff --cached --check
git diff --cached --stat
```

Expected: no whitespace errors; staged paths only contain this feature’s source, tests, profiles/templates, design, and plan documents plus user-authorized overlapping hunks.

- [ ] **Step 4: Create the integrated feature commit**

```bash
git add app/config.py app/gui.py app/pipeline_runner.py app/text_annotations.py data/defaults data/profiles tests docs/superpowers/specs/2026-09-20-configurable-marketing-contract-design.md docs/superpowers/plans/2026-09-20-configurable-marketing-contract.md
git commit -m "feat: configure marketing candidates per profile"
```

- [ ] **Step 5: Re-run the focused regression suite from the committed tree**

Run: `python -m pytest tests/test_marketing_contract.py tests/test_japanese_furigana.py tests/test_pipeline_rewrite_localization.py tests/test_gui_scroll_collapse.py -v`

Expected: PASS, then report the exact commit ID and any unrelated remaining workspace changes.
