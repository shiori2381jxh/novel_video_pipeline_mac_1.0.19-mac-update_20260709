from app.config import DEFAULT_SETTINGS
from app.gui import PipelineGUI


def test_rewrite_localization_defaults_are_safe():
    assert DEFAULT_SETTINGS["ai_rewrite_proper_noun_localization_enabled"] is False
    assert DEFAULT_SETTINGS["ai_rewrite_min_length_ratio"] == 0.75
    assert DEFAULT_SETTINGS["ai_rewrite_max_length_ratio"] == 1.35


def test_gui_treats_rewrite_localization_as_boolean_and_ratios_as_float():
    _int_keys, float_keys, bool_keys = PipelineGUI._config_key_sets(object.__new__(PipelineGUI))

    assert "ai_rewrite_proper_noun_localization_enabled" in bool_keys
    assert {"ai_rewrite_min_length_ratio", "ai_rewrite_max_length_ratio"} <= float_keys
