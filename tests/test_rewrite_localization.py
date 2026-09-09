import pytest

from app.rewrite_localization import (
    Replacement,
    apply_replacements,
    build_deterministic_fallback_replacements,
    detect_rewrite_language,
    extract_rejected_replacement_sources,
    find_residual_sources,
    parse_structured_rewrite_response,
    validate_rewrite_quality,
)


def test_rejected_near_name_gets_a_stable_distinct_fallback():
    raw = (
        '{"rewritten_text":"林一回家。","new_replacements":['
        '{"category":"人名","source":"林一","target":"林二","notes":""}'
        '],"warnings":[]}'
    )

    candidates = extract_rejected_replacement_sources(raw, "林一回家。")
    first = build_deterministic_fallback_replacements(candidates, "林一回家。", 1, [])
    second = build_deterministic_fallback_replacements(candidates, "林一回家。", 1, [])

    assert [item.source for item in first] == ["林一"]
    assert first[0].target == second[0].target
    assert first[0].target != "林一"
    assert first[0].local_replace_safe is True


def test_fallback_ignores_absent_source_and_avoids_existing_target():
    candidates = [
        {"category": "人名", "source": "林一"},
        {"category": "人名", "source": "不存在"},
    ]
    known = [Replacement("人名", "旧名", "陈舟", "", 1, True)]

    result = build_deterministic_fallback_replacements(
        candidates, "林一回家。", 1, known
    )

    assert [item.source for item in result] == ["林一"]
    assert result[0].target != "陈舟"


def test_detect_rewrite_language_distinguishes_japanese_and_chinese():
    assert detect_rewrite_language("彼女は駅へ向かった。理由は知らない。").code == "ja"
    assert detect_rewrite_language("她走向车站，却不知道原因。").code == "zh"


def test_parse_response_preserves_known_mapping_and_rejects_conflict():
    known = [Replacement("人名", "阿明", "陈舟", "", 1, True)]
    raw = (
        '{"rewritten_text":"阿明走进了房间。","new_replacements":['
        '{"category":"人名","source":"阿明","target":"周凯","notes":""}'
        '],"warnings":[]}'
    )

    with pytest.raises(ValueError, match="冲突"):
        parse_structured_rewrite_response(
            raw,
            source_text="阿明走进了房间。",
            batch_index=2,
            known_replacements=known,
        )


def test_apply_replacements_is_longest_first_and_reports_residuals():
    replacements = [
        Replacement("人名", "王", "赵", "", 1, False),
        Replacement("人名", "王小明", "陈舟", "", 1, True),
    ]

    assert apply_replacements("王小明见到了王。", replacements) == "陈舟见到了王。"
    assert find_residual_sources("陈舟见到了王。", replacements) == ["王"]


def test_apply_replacements_does_not_reprocess_a_new_name_as_another_source():
    replacements = [
        Replacement("人名", "阿明", "陈舟", "", 1, True),
        Replacement("人名", "陈舟", "东方", "", 2, True),
    ]

    assert apply_replacements("阿明和陈舟。", replacements) == "陈舟和东方。"


def test_detect_rewrite_language_does_not_force_kana_less_japanese_to_chinese():
    assert detect_rewrite_language("東京駅。午後、緊急会議。").code == "ja"


def test_quality_rejects_empty_summary_and_wrong_language():
    source = "彼女は扉を開けた。雨が降っていた。"
    errors = validate_rewrite_quality(
        source_text=source,
        rewritten_text="要約",
        language=detect_rewrite_language(source),
        min_ratio=0.75,
        max_ratio=1.35,
    )

    assert any("长度" in error for error in errors)
    assert any("日语" in error for error in errors)


@pytest.mark.parametrize("raw", ["", "not json", '{"rewritten_text":"正文"}'])
def test_parse_response_rejects_invalid_protocol(raw):
    with pytest.raises(ValueError):
        parse_structured_rewrite_response(
            raw,
            source_text="原文",
            batch_index=1,
            known_replacements=[],
        )


def test_parse_response_rejects_name_missing_from_source():
    raw = (
        '{"rewritten_text":"正文","new_replacements":['
        '{"category":"人名","source":"不存在","target":"新名","notes":""}'
        '],"warnings":[]}'
    )

    with pytest.raises(ValueError, match="原文"):
        parse_structured_rewrite_response(
            raw,
            source_text="实际正文",
            batch_index=1,
            known_replacements=[],
        )


def test_parse_response_normalizes_common_location_category_alias():
    raw = (
        '{"rewritten_text":"林一抵达旧城区。","new_replacements":['
        '{"category":"地点","source":"旧城区","target":"临川区","notes":"稳定地点"}'
        '],"warnings":[]}'
    )

    result = parse_structured_rewrite_response(
        raw,
        source_text="林一抵达旧城区。",
        batch_index=1,
        known_replacements=[],
    )

    assert result.replacements[0].category == "地名"


def test_parse_response_ignores_unselected_categories():
    raw = ('{"rewritten_text":"林一看到畜人。","new_replacements":['
           '{"category":"人名","source":"林一","target":"沈言","notes":""},'
           '{"category":"种族名","source":"畜人","target":"牧食者","notes":""}],"warnings":[]}')
    result = parse_structured_rewrite_response(raw, source_text="林一看到畜人。", batch_index=1,
                                               known_replacements=[], allowed_categories={"人名"})
    assert [item.source for item in result.replacements] == ["林一"]
    assert any("未选" in item for item in result.warnings)
