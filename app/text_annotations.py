"""Convert inline Japanese furigana without mutating the saved source text."""

from __future__ import annotations

import re


_JAPANESE_WORD = r"[\u3400-\u9fff々〆ヶ][\u3040-\u30ff\u3400-\u9fff々〆ヶー]*?"
_KANA_READING = r"[ぁ-ゖァ-ヺー・]+"
_FURIGANA_RE = re.compile(
    rf"(?P<written>{_JAPANESE_WORD})[（(](?P<reading>{_KANA_READING})[）)]"
)
_TTS_BRACKET_AND_QUOTE_RE = re.compile(r"[（）()\[\]［］【】{}｛｝「」『』\"'“”‘’]")
_TTS_DASH_RE = re.compile(r"[—―－-]+")


def subtitle_display_text(text: str) -> str:
    """Hide only valid ``word（kana）`` annotations from subtitle source text."""
    return _FURIGANA_RE.sub(lambda match: match.group("written"), str(text or ""))


def has_inline_furigana(text: str) -> bool:
    """Return whether text contains at least one supported Japanese annotation."""
    return _FURIGANA_RE.search(str(text or "")) is not None


def tts_narration_text(text: str) -> str:
    """Replace inline furigana, then remove TTS-hostile symbols for every provider."""
    value = _FURIGANA_RE.sub(lambda match: match.group("reading"), str(text or ""))
    value = _TTS_DASH_RE.sub("，", value)
    value = _TTS_BRACKET_AND_QUOTE_RE.sub("", value)
    value = re.sub(r"[，,]{2,}", "，", value)
    return value.strip()
