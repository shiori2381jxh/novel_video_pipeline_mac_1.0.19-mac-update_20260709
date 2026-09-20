import json
from pathlib import Path

from app import pipeline_runner
from app.config import DEFAULT_SETTINGS


VISUAL_PROMPT_KEYS = (
    "llm_storyboard_prompt",
    "llm_storyboard_user_template",
    "llm_image_prompt_prefix",
    "llm_image_style_suffix",
    "character_analysis_prompt",
    "character_reference_prompt_suffix",
    "cover_custom_prompt",
    "cover_poster_method_prompt",
)
FORCED_ISEKAI_TERMS = ("isekai", "异世界", "fantasy world")


def _visual_prompt_text(values: dict) -> str:
    return "\n".join(str(values.get(key, "")) for key in VISUAL_PROMPT_KEYS).lower()


def test_storyboard_fallback_follows_source_without_isekai(monkeypatch):
    values = {
        "llm_image_prompt_prefix": "Neutral editorial illustration",
        "llm_image_style_suffix": "cinematic rendering",
    }
    monkeypatch.setattr(pipeline_runner.config, "get", lambda key, default=None: values.get(key, default))

    prompt = pipeline_runner._fallback_storyboard_prompt("东京写字楼里，律师整理合同。")

    assert "story's stated world, era, characters, costumes, and setting" in prompt
    assert "unrelated story" in prompt
    assert "isekai" not in prompt.lower()


def test_default_visual_prompts_do_not_force_isekai():
    text = _visual_prompt_text(DEFAULT_SETTINGS)

    assert not any(term in text for term in FORCED_ISEKAI_TERMS)


def test_saved_visual_prompt_profiles_do_not_force_isekai():
    root = Path(__file__).resolve().parents[1]
    paths = [root / "data" / "settings.json", *(root / "data" / "profiles").glob("*.json")]

    for path in paths:
        values = json.loads(path.read_text(encoding="utf-8"))
        text = _visual_prompt_text(values)
        assert not any(term in text for term in FORCED_ISEKAI_TERMS), path.name


def test_bl_profile_requires_only_adult_male_cover_characters():
    root = Path(__file__).resolve().parents[1]
    values = json.loads((root / "data" / "profiles" / "日语BL推文.json").read_text(encoding="utf-8"))
    prompt = str(values.get("cover_custom_prompt") or "").lower()

    assert "boys' love" in prompt
    assert "only adult male characters" in prompt
    assert "do not include women" in prompt
