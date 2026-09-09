import inspect
import json
from types import SimpleNamespace

from app import pipeline_runner
from app.stages.stage6_compose import build_ass, build_srt


def test_build_ass_converts_only_subtitle_text_when_traditional_enabled(tmp_path):
    output = tmp_path / "subtitle.ass"

    build_ass([(0.0, 1.0, "后发现台风，ABC 123")], output, traditional=True)

    assert "後發現颱風，ABC 123" in output.read_text(encoding="utf-8")


def test_build_srt_keeps_simplified_text_when_traditional_disabled(tmp_path):
    output = tmp_path / "subtitle.srt"

    build_srt([(0.0, 1.0, "后发现台风，ABC 123")], output)

    assert "后发现台风，ABC 123" in output.read_text(encoding="utf-8")


def test_build_srt_converts_subtitle_text_when_traditional_enabled(tmp_path):
    output = tmp_path / "subtitle.srt"

    build_srt([(0.0, 1.0, "后发现台风，ABC 123")], output, traditional=True)

    assert "後發現颱風，ABC 123" in output.read_text(encoding="utf-8")


def test_main_video_composition_forwards_traditional_subtitle_setting():
    source = inspect.getsource(pipeline_runner._stage_compose_manifest_impl)

    assert 'traditional=bool(config.get("video_subtitle_traditional", False))' in source


def test_main_video_cache_includes_traditional_subtitle_setting():
    source = inspect.getsource(pipeline_runner._stage_compose_manifest_impl)

    assert '"traditional": bool(config.get("video_subtitle_traditional", False))' in source


def test_compose_only_retry_refreshes_existing_settings_snapshot(monkeypatch, tmp_path):
    snapshot = tmp_path / "settings_snapshot.json"
    snapshot.write_text(json.dumps({"video_subtitle_traditional": False}), encoding="utf-8")
    settings = {"video_subtitle_traditional": True, "max_concurrent_jobs": 1}

    monkeypatch.setattr(pipeline_runner, "job_dir_for", lambda _job_id: tmp_path)
    monkeypatch.setattr(pipeline_runner, "_resolve_job_input_source", lambda _job_dir, text, **_kwargs: text)
    monkeypatch.setattr(pipeline_runner, "count_running_workers", lambda: 0)
    monkeypatch.setattr(pipeline_runner, "write_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_runner, "append_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_runner, "record_worker_pid", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_runner.config, "as_dict", lambda: settings)
    monkeypatch.setattr(pipeline_runner.config, "get", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(pipeline_runner.subprocess, "Popen", lambda *_args, **_kwargs: SimpleNamespace(pid=1))

    pipeline_runner.start_worker("正文", job_id="retry-job", resume=True, compose_only=True)

    saved = json.loads(snapshot.read_text(encoding="utf-8"))
    assert saved["video_subtitle_traditional"] is True
