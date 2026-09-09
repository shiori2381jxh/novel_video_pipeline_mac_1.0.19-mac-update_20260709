from pathlib import Path


def test_windows_file_selection_prefers_browser_input(monkeypatch, tmp_path):
    """The native picker must not run when Chrome accepts the local file path."""
    from app.vendor import stage5_upload_browser as upload

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    calls = []

    monkeypatch.setattr(upload.os, "name", "nt")
    monkeypatch.setattr(
        upload,
        "_select_file_with_playwright",
        lambda *_args: calls.append("browser") or True,
    )
    monkeypatch.setattr(
        upload,
        "_try_select_file_once",
        lambda *_args: calls.append("native") or True,
    )

    assert upload._select_file_via_dialog(object(), video, lambda _message: None, 1_000)
    assert calls == ["browser"]


def test_windows_file_selection_falls_back_to_native_picker(monkeypatch, tmp_path):
    """A browser-side failure must retain the established Windows fallback."""
    from app.vendor import stage5_upload_browser as upload

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    calls = []

    monkeypatch.setattr(upload.os, "name", "nt")
    monkeypatch.setattr(
        upload,
        "_select_file_with_playwright",
        lambda *_args: calls.append("browser") or False,
    )
    monkeypatch.setattr(
        upload,
        "_try_select_file_once",
        lambda *_args: calls.append("native") or True,
    )

    assert upload._select_file_via_dialog(object(), video, lambda _message: None, 1_000)
    assert calls == ["browser", "native"]
