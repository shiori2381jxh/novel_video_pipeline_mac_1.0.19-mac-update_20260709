import json
from pathlib import Path

import pytest

from app import pipeline_runner as pr
from app import gui


def test_preliminary_package_excludes_nested_mp4_but_keeps_short_audio_and_text(monkeypatch, tmp_path):
    jobs_dir = tmp_path / "jobs"
    package_root = tmp_path / "预备分"
    job = jobs_dir / "story"
    (job / "_source_input").mkdir(parents=True)
    (job / "_source_input" / "story.txt").write_text("正文", encoding="utf-8")
    (job / "audio_full.mp3").write_bytes(b"audio")
    (job / "shorts" / "nested").mkdir(parents=True)
    (job / "story.mp4").write_bytes(b"main")
    (job / "shorts" / "short.mp4").write_bytes(b"short")
    (job / "shorts" / "nested" / "clip.MP4").write_bytes(b"nested")
    (job / "shorts" / "audio_full.mp3").write_bytes(b"short-audio")
    (job / "shorts" / "script.txt").write_text("Short 文案", encoding="utf-8")
    monkeypatch.setattr(pr, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(pr, "PRELIMINARY_JOBS_DIR", package_root)
    monkeypatch.setattr(pr, "is_worker_running", lambda _job_id: False)

    pr.prepare_job_for_preliminary_scoring("story")

    package = package_root / "预备分_story"
    assert not [path for path in package.rglob("*") if path.suffix.lower() == ".mp4"]
    assert (package / "shorts" / "audio_full.mp3").exists()
    assert (package / "shorts" / "script.txt").read_text(encoding="utf-8") == "Short 文案"


def test_read_preliminary_package_rejects_manifest_path_outside_package(tmp_path):
    package = tmp_path / "预备分_story"
    package.mkdir()
    (package / "preliminary_package.json").write_text(
        json.dumps({"version": 1, "text_path": "../outside.txt", "audio_path": "audio_full.mp3"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="预备分包"):
        pr.read_preliminary_package(package)


def test_preliminary_package_folder_is_removed_from_normal_txt_mp3_scan(monkeypatch, tmp_path):
    package = tmp_path / "预备分_story"
    package.mkdir()
    (package / pr.PRELIMINARY_PACKAGE_MANIFEST).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        gui.pr,
        "read_preliminary_package",
        lambda path: {
            "package_dir": package,
            "text_path": package / "_source_input" / "story.txt",
            "audio_path": package / "audio_full.mp3",
            "title": "story",
        },
    )

    packages, remaining = gui._split_preliminary_package_imports([package])

    assert packages[0]["title"] == "story"
    assert remaining == []


def test_reimported_package_creates_imported_audio_task(monkeypatch, tmp_path):
    package = {
        "package_dir": tmp_path / "预备分_story",
        "text_path": tmp_path / "story.txt",
        "audio_path": tmp_path / "audio_full.mp3",
        "title": "story",
    }
    calls = []
    app = object.__new__(gui.PipelineGUI)
    monkeypatch.setattr(
        app,
        "_create_queued_job",
        lambda title, text, **kwargs: calls.append((title, text, kwargs)) or "story",
    )

    created, errors = app._create_jobs_from_preliminary_packages([package])

    assert created == 1
    assert errors == []
    assert calls == [
        ("story", str(package["text_path"]), {"imported_audio_path": str(package["audio_path"])})
    ]


def test_preliminary_confirmation_copy_says_mp4_is_not_retained():
    source = Path(gui.__file__).read_text(encoding="utf-8")

    assert "不保留任何 MP4" in source
    assert "重新导入" in source
