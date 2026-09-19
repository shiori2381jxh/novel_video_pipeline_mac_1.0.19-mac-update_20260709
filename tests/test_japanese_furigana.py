import pytest

from app.text_annotations import subtitle_display_text, tts_narration_text
from app import pipeline_runner
from app.pipeline_runner import _prepare_tts_pronunciation
from app.stages.stage2_clean import Segment


@pytest.mark.parametrize(
    ("source", "expected_tts", "expected_subtitle"),
    [
        (
            "世（よ）の絶望（ぜつぼう）を煮詰めた（につめた）ように泣いている。",
            "よのぜつぼうをにつめたように泣いている。",
            "世の絶望を煮詰めたように泣いている。",
        ),
        (
            "彼（かれ）は万一（まんいち）に備（そな）えて、多額（たがく）の現金（げんきん）を持ち合わせ（もちあわせ）ていた。",
            "かれはまんいちにそなえて、たがくのげんきんをもちあわせていた。",
            "彼は万一に備えて、多額の現金を持ち合わせていた。",
        ),
        (
            "長（なが）い旅（たび）の末（すえ）、彼（かれ）らは目的地（もくてきち）に行き着いた（いきついた）。",
            "ながいたびのすえ、かれらはもくてきちにいきついた。",
            "長い旅の末、彼らは目的地に行き着いた。",
        ),
    ],
)
def test_japanese_furigana_produces_distinct_tts_and_subtitle_text(source, expected_tts, expected_subtitle):
    assert tts_narration_text(source) == expected_tts
    assert subtitle_display_text(source) == expected_subtitle


def test_tts_narration_supports_half_width_parentheses_and_cleans_symbols_after_replacement():
    source = "彼(かれ)「は」[万一(まんいち)]——備（そな）えて"

    result = tts_narration_text(source)

    assert result == "かれはまんいち，そなえて"
    assert not any(symbol in result for symbol in "（）()[]［］【】{}｛｝「」『』———―－-\"'“”‘’")


def test_tts_keeps_non_furigana_parenthetical_content_without_parenthesis_symbols():
    assert tts_narration_text("彼（注釈）(note)は来た") == "彼注釈noteは来た"


def test_tts_preparation_applies_inline_furigana_for_any_provider(tmp_path):
    segments = [Segment(0, "世（よ）の絶望（ぜつぼう）——彼（かれ）")]

    narration, replacements, entries, dictionary_hash = _prepare_tts_pronunciation(
        segments, tmp_path, "openai"
    )

    assert narration == ["よのぜつぼう，かれ"]
    assert replacements == [0]
    assert entries == []
    assert dictionary_hash == ""


def test_legacy_tts_redo_rebuilds_broken_segments_from_saved_source(tmp_path, monkeypatch):
    source = "世（よ）の絶望（ぜつぼう）を煮詰めた（につめた）ように泣いている。"
    (tmp_path / "novel.json").write_text(
        '{"site":"text","id":"","title":"t","author":"","description":"",'
        '"chapters":[{"index":1,"title":"","text":"' + source + '"}]}',
        encoding="utf-8",
    )
    (tmp_path / "segments.json").write_text('[{"i":0,"text":"世よの絶望ぜつぼう"}]', encoding="utf-8")
    monkeypatch.setattr(pipeline_runner, "stage_clean", lambda novel, **_kwargs: [Segment(0, source)])

    assert pipeline_runner._rebuild_legacy_furigana_segments(tmp_path) is True
    assert pipeline_runner._load_job_segments(tmp_path)[0].text == source
