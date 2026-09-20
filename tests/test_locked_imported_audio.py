from app import pipeline_runner


def test_locked_imported_audio_keeps_saved_subtitle_durations(monkeypatch, tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_path = audio_dir / "imported_narration.mp3"
    audio_path.write_bytes(b"audio")
    pipeline_runner._write_json(
        tmp_path / pipeline_runner.IMPORTED_AUDIO_MANIFEST,
        {
            "mode": "imported_mp3",
            "path": "audio/imported_narration.mp3",
            "timing_mode": "subtitle_locked",
        },
    )
    pipeline_runner._write_json(tmp_path / "durations.json", [3.0, 7.0])
    monkeypatch.setattr(pipeline_runner, "_audio_duration", lambda _path: 10.0)

    audios, durations = pipeline_runner.stage_tts(
        [pipeline_runner.Segment(index=0, text="甲"), pipeline_runner.Segment(index=1, text="乙")],
        tmp_path,
    )

    assert audios == [audio_path]
    assert durations == [3.0, 7.0]
