import ctypes
import json

from app import pipeline_runner


def test_write_status_retries_transient_windows_access_denied(monkeypatch, tmp_path):
    """A momentary lock on status.json must not fail the running job."""
    real_replace = pipeline_runner.os.replace
    attempts = 0

    def replace_with_one_transient_lock(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ctypes.WinError(5)
        return real_replace(source, destination)

    monkeypatch.setattr(pipeline_runner.os, "replace", replace_with_one_transient_lock)
    monkeypatch.setattr(pipeline_runner.time, "sleep", lambda _seconds: None)

    pipeline_runner.write_status(tmp_path, stage="tts", progress=0.5)

    assert attempts == 2
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["stage"] == "tts"
