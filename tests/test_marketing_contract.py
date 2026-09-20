import app.config as config_module

from app.config import marketing_contract
from app.text_annotations import marketing_display_text, subtitle_display_text, tts_narration_text
from app import pipeline_runner
from app.gui import PipelineGUI
from app.scrapers.base import Novel, NovelChapter


def test_marketing_display_text_removes_inline_readings_without_changing_tts_behavior():
    source = "蒼真（そうま）は朝陽（あさひ）を見た。"

    assert marketing_display_text(source) == "蒼真は朝陽を見た。"
    assert subtitle_display_text(source) == "蒼真は朝陽を見た。"
    assert tts_narration_text(source) == "そうまはあさひを見た。"


def test_marketing_contract_defaults_and_clamps_required_counts():
    assert marketing_contract({}) == {
        "title_count": 3,
        "synopsis_count": 1,
        "tag_min_count": 5,
        "tag_max_count": 10,
    }


def test_config_migration_preserves_the_profile_marketing_prompt():
    data = dict(config_module.DEFAULT_SETTINGS)
    custom_prompt = "タイトルは15〜25文字で、概要は作品の事実だけを使う。"
    data["marketing_candidates_prompt"] = custom_prompt

    config_module._apply_compat_migrations(data, {"settings_schema_version": 61})

    assert data["marketing_candidates_prompt"] == custom_prompt
    assert marketing_contract(data) == {
        "title_count": 3,
        "synopsis_count": 1,
        "tag_min_count": 5,
        "tag_max_count": 10,
    }
    assert marketing_contract({
        "marketing_title_count": 0,
        "marketing_synopsis_count": -1,
        "marketing_tag_min_count": 9,
        "marketing_tag_max_count": 2,
    }) == {
        "title_count": 1,
        "synopsis_count": 1,
        "tag_min_count": 9,
        "tag_max_count": 9,
    }


def test_marketing_candidates_follow_configured_counts_and_remove_inline_readings(monkeypatch):
    monkeypatch.setattr(pipeline_runner, "_marketing_contract", lambda: {
        "title_count": 2,
        "synopsis_count": 3,
        "tag_min_count": 4,
        "tag_max_count": 6,
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
        "title_count": 1,
        "synopsis_count": 1,
        "tag_min_count": 1,
        "tag_max_count": 2,
    })

    assert pipeline_runner._marketing_validation_error({
        "titles": ["短い"],
        "synopses": ["概要"],
        "tags": ["#タグ"],
    }) == ""


def test_local_marketing_fallback_and_cover_bundle_use_the_configured_contract(monkeypatch):
    monkeypatch.setattr(pipeline_runner, "_marketing_contract", lambda: {
        "title_count": 2,
        "synopsis_count": 1,
        "tag_min_count": 5,
        "tag_max_count": 6,
    })
    novel = Novel(
        site="text",
        novel_id="n-1",
        title="朝陽（あさひ）の物語",
        author="",
        description="",
        chapters=[NovelChapter(index=1, title="", text="蒼真（そうま）は朝陽（あさひ）を見た。二人は帰った。")],
    )

    fallback = pipeline_runner._fallback_marketing_candidates(novel, novel.full_text)
    cover = pipeline_runner._cover_marketing_bundle(novel, [], {
        "titles": ["蒼真（そうま）の告白", "朝陽（あさひ）の返事"],
        "synopses": ["蒼真（そうま）と朝陽（あさひ）の概要"],
    })

    assert len(fallback["titles"]) == 2
    assert len(fallback["synopses"]) == 1
    assert 5 <= len(fallback["tags"]) <= 6
    assert all("（" not in value and "）" not in value for value in fallback["titles"] + fallback["synopses"])
    assert cover["titles"] == ["蒼真の告白", "朝陽の返事"]
    assert cover["synopses"] == ["蒼真と朝陽の概要"]

    manual_cover = pipeline_runner._cover_marketing_bundle(novel, [], {
        "ai_cover_copy_enabled": False,
        "manual_cover_title": "蒼真（そうま）の表紙",
    })
    assert manual_cover["titles"] == ["蒼真の表紙"]
    assert "（" not in manual_cover["synopses"][0]

    cover_title, _ = pipeline_runner._cover_marketing_context(novel, [], {
        "short_title": "蒼真（そうま）の選択" * 12,
        "intro": "概要",
    })
    assert cover_title == "蒼真の選択" * 12


def test_metadata_stage_writes_configured_display_clean_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_runner, "_marketing_contract", lambda: {
        "title_count": 2,
        "synopsis_count": 1,
        "tag_min_count": 5,
        "tag_max_count": 6,
    })
    monkeypatch.setattr(pipeline_runner, "_can_call_text_llm", lambda: False)
    novel = Novel(
        site="text",
        novel_id="n-2",
        title="朝陽（あさひ）の物語",
        author="",
        description="",
        chapters=[NovelChapter(index=1, title="", text="蒼真（そうま）は朝陽（あさひ）を見た。二人は帰った。")],
    )

    metadata = pipeline_runner.stage_metadata(novel, tmp_path)

    assert len(metadata["titles"]) == 2
    assert len(metadata["synopses"]) == 1
    assert all("（" not in value and "）" not in value for value in metadata["titles"] + metadata["synopses"])
    saved = pipeline_runner._read_json(tmp_path / "marketing_candidates.json", {})
    assert saved["titles"] == metadata["titles"]
    assert saved["synopses"] == metadata["synopses"]


def test_selected_text_account_overrides_the_default_text_route(monkeypatch):
    values = {
        "ai_api_enabled": True,
        "ai_api_base_url": "https://default.example/v1",
        "ai_api_key": "default-key",
        "ai_api_text_model": "default-model",
        "relay_station_count": 1,
        "llm_relay_station": 1,
        "relay_station_1_base_url": "https://text.example/v1",
        "relay_station_1_api_key": "text-key",
        "relay_station_1_text_model": "text-model",
    }
    monkeypatch.setattr(pipeline_runner.config, "get", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(pipeline_runner.config, "llm_provider", "openai")
    monkeypatch.setattr(pipeline_runner.config, "llm_base_url", "https://legacy.example/v1")
    monkeypatch.setattr(pipeline_runner.config, "llm_api_key", "legacy-key")
    monkeypatch.setattr(pipeline_runner.config, "llm_model", "legacy-model")

    route = pipeline_runner._llm_route_settings()

    assert route == {
        "provider": "openai",
        "base_url": "https://text.example/v1",
        "api_key": "text-key",
        "model": "text-model",
    }


def test_text_route_uses_the_default_account_when_no_text_account_is_selected(monkeypatch):
    values = {
        "ai_api_enabled": True,
        "ai_api_base_url": "https://default.example/v1",
        "ai_api_key": "default-key",
        "ai_api_text_model": "default-model",
        "relay_station_count": 1,
        "llm_relay_station": 0,
        "relay_station_1_base_url": "https://text.example/v1",
        "relay_station_1_api_key": "text-key",
        "relay_station_1_text_model": "text-model",
    }
    monkeypatch.setattr(pipeline_runner.config, "get", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(pipeline_runner.config, "llm_provider", "openai")
    monkeypatch.setattr(pipeline_runner.config, "llm_base_url", "https://legacy.example/v1")
    monkeypatch.setattr(pipeline_runner.config, "llm_api_key", "legacy-key")
    monkeypatch.setattr(pipeline_runner.config, "llm_model", "legacy-model")

    route = pipeline_runner._llm_route_settings()

    assert route == {
        "provider": "openai",
        "base_url": "https://default.example/v1",
        "api_key": "default-key",
        "model": "default-model",
    }


def test_marketing_regeneration_message_and_gui_integer_fields_follow_contract():
    message = PipelineGUI._marketing_regeneration_message({
        "title_count": 2,
        "synopsis_count": 1,
        "tag_min_count": 5,
        "tag_max_count": 10,
    })
    integer_keys, _float_keys, _bool_keys = PipelineGUI._config_key_sets(object.__new__(PipelineGUI))

    assert "2 个标题、1 个概梗和 5–10 个内容标签" in message
    assert {
        "marketing_title_count",
        "marketing_synopsis_count",
        "marketing_tag_min_count",
        "marketing_tag_max_count",
    } <= integer_keys
