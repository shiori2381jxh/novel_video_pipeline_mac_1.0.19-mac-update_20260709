from pathlib import Path

from app.backends import tts


class _Response:
    content = b"RIFFfake-wav"

    def raise_for_status(self):
        return None

    def json(self):
        return {"speedScale": 1.0, "intonationScale": 1.0, "prePhonemeLength": 0.1, "postPhonemeLength": 0.1}


def test_aoyama_ryusei_uses_voicevox_speaker_13(monkeypatch, tmp_path: Path):
    calls = []

    def fake_http_post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr(tts, "http_post", fake_http_post)
    tts.TTSBackend("voicevox", "311｜男｜青山龍星｜普通")._synth_voicevox("神楽", tmp_path / "aoyama.wav")

    assert [kwargs["params"]["speaker"] for _url, kwargs in calls] == [13, 13]
    assert "311｜男｜青山龍星｜普通" in tts.VOICEVOX_FREQUENT_VOICES
