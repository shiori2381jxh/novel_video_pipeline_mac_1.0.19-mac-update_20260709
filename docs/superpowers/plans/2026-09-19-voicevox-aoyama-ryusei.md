# VOICEVOX 青山龍星音色 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 青山龍星（ノーマル）selectable in the curated VOICEVOX list and synthesize through speaker ID 13.

**Architecture:** `app.backends.tts` owns both the curated labels displayed by the GUI and the mapping from their stable UI codes to VOICEVOX speaker IDs. Add one label and one mapping there; retain direct raw ID behavior. A focused unit test will exercise the backend's existing numeric-code parsing by intercepting its HTTP calls.

**Tech Stack:** Python 3, pytest, httpx-compatible project HTTP wrapper, local VOICEVOX HTTP API.

## Global Constraints

- Add only `311｜男｜青山龍星｜普通`; do not add other 青山龍星 styles.
- Curated code `311` must resolve to VOICEVOX speaker ID `13` for both API calls.
- Do not edit active settings or profiles.
- Preserve existing support for a raw VOICEVOX speaker ID.

---

### Task 1: Curated voice mapping

**Files:**
- Modify: `tests/test_voicevox_curated_voices.py`
- Modify: `app/backends/tts.py:569-590`

**Interfaces:**
- Consumes: `TTSBackend._synth_voicevox(text: str, out_path: Path) -> None` and `VOICEVOX_FREQUENT_VOICE_IDS: dict[int, int]`.
- Produces: a curated entry `311｜男｜青山龍星｜普通` that requests speaker `13` from `/audio_query` and `/synthesis`.

- [ ] **Step 1: Write the failing test**

```python
from app.backends.tts import TTSBackend, VOICEVOX_FREQUENT_VOICES


def test_aoyama_ryusei_curated_code_uses_installed_speaker_id(tmp_path, monkeypatch):
    calls = []

    class Response:
        content = b"RIFF"
        def raise_for_status(self): pass
        def json(self): return {"accent_phrases": []}

    monkeypatch.setattr("app.backends.tts.http_post", lambda url, **kwargs: (calls.append((url, kwargs)) or Response()))
    backend = TTSBackend("voicevox", "311｜男｜青山龍星｜普通")
    backend._synth_voicevox("テスト", tmp_path / "voice.wav")

    assert "311｜男｜青山龍星｜普通" in VOICEVOX_FREQUENT_VOICES
    assert [item[1]["params"]["speaker"] for item in calls] == [13, 13]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_voicevox_curated_voices.py -v`

Expected: FAIL because the curated entry is absent and the backend passes `311`, not `13`.

- [ ] **Step 3: Write minimal implementation**

```python
VOICEVOX_FREQUENT_VOICE_IDS = {
    111: 2, 112: 0, 113: 6, 114: 4, 115: 36, 116: 37,
    121: 8,
    131: 10,
    211: 11, 212: 39, 213: 40, 214: 41,
    311: 13,  # 青山龍星 ノーマル
}

# Append this exact string after the four 玄野武宏 options.
"311｜男｜青山龍星｜普通",
```

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m pytest tests/test_voicevox_curated_voices.py tests/test_japanese_furigana.py -v`

Expected: PASS; the curated mapping is correct and inline-furigana behavior is unchanged.

- [ ] **Step 5: Run the real local synthesis probe**

Run a short Python probe with `TTSBackend("voicevox", "311｜男｜青山龍星｜普通")` and source text `神楽（かぐら）`. Confirm that `tts_narration_text()` produces `かぐら`, `subtitle_display_text()` retains `神楽`, and the generated WAV opens successfully.

- [ ] **Step 6: Commit**

```bash
git add app/backends/tts.py tests/test_voicevox_curated_voices.py
git commit -m "feat: add Aoyama Ryusei VoiceVox voice"
```
