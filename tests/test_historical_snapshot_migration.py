from app.config import DEFAULT_SETTINGS, _apply_compat_migrations


def test_schema_55_profile_migrates_without_removed_minute_defaults():
    saved = {"settings_schema_version": 55, "active_profile": "日语BL推文"}
    data = dict(DEFAULT_SETTINGS)

    _apply_compat_migrations(data, saved)

    assert data["longform_default_batch_episode_count"] == 5
    assert data["longform_default_min_final_chars"] == 18_000


def test_chinese_tweet_profile_migrates_forced_historical_snapshot():
    saved = {
        "settings_schema_version": 58,
        "active_profile": "中文推文配置",
        "llm_image_prompt_prefix": "Single finished 16:9 Chinese historical fiction illustration for a novel recap video",
        "llm_image_style_suffix": "Japanese manga advertisement style applied to Chinese historical fiction",
        "llm_storyboard_user_template": "Task: turn this Chinese historical-fiction excerpt into ONE finished English image-generation prompt",
        "character_reference_prompt_suffix": "Chinese historical fiction character design",
    }
    data = dict(DEFAULT_SETTINGS)
    data.update(saved)

    _apply_compat_migrations(data, saved)

    assert data["llm_image_prompt_prefix"] == DEFAULT_SETTINGS["llm_image_prompt_prefix"]
    assert data["llm_image_style_suffix"] == DEFAULT_SETTINGS["llm_image_style_suffix"]
    assert data["llm_storyboard_user_template"] == DEFAULT_SETTINGS["llm_storyboard_user_template"]
    assert data["character_reference_prompt_suffix"] == DEFAULT_SETTINGS["character_reference_prompt_suffix"]
