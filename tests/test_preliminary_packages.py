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
    for name in (
        "novel.json",
        "segments.json",
        "story_visual_context.json",
        "character_profiles.json",
    ):
        (job / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pr, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(pr, "PRELIMINARY_JOBS_DIR", package_root)
    monkeypatch.setattr(pr, "is_worker_running", lambda _job_id: False)

    pr.prepare_job_for_preliminary_scoring("story")

    package = package_root / "预备分_story"
    assert not [path for path in package.rglob("*") if path.suffix.lower() == ".mp4"]
    assert (package / "shorts" / "audio_full.mp3").exists()
    assert (package / "shorts" / "script.txt").read_text(encoding="utf-8") == "Short 文案"
    manifest = json.loads((package / pr.PRELIMINARY_PACKAGE_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["reusable_json"] == {
        "novel.json": "novel.json",
        "segments.json": "segments.json",
        "story_visual_context.json": "story_visual_context.json",
        "character_profiles.json": "character_profiles.json",
    }


def test_read_preliminary_package_rejects_manifest_path_outside_package(tmp_path):
    package = tmp_path / "预备分_story"
    package.mkdir()
    (package / "preliminary_package.json").write_text(
        json.dumps({"version": 1, "text_path": "../outside.txt", "audio_path": "audio_full.mp3"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="预备分包"):
        pr.read_preliminary_package(package)


def test_read_preliminary_package_rejects_invalid_reusable_json(monkeypatch, tmp_path):
    package = tmp_path / "预备分_story"
    source = package / "_source_input" / "story.txt"
    source.parent.mkdir(parents=True)
    source.write_text("正文", encoding="utf-8")
    (package / "audio_full.mp3").write_bytes(b"audio")
    (package / "novel.json").write_text("not json", encoding="utf-8")
    (package / pr.PRELIMINARY_PACKAGE_MANIFEST).write_text(
        json.dumps(
            {
                "version": 1,
                "text_path": "_source_input/story.txt",
                "audio_path": "audio_full.mp3",
                "reusable_json": {"novel.json": "novel.json"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pr, "inspect_imported_audio", lambda _path: None)

    with pytest.raises(ValueError, match="预备分包中的 novel.json 无效"):
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
    reusable = tmp_path / "reusable"
    reusable.mkdir()
    (reusable / "novel.json").write_text("{}", encoding="utf-8")
    package = {
        "package_dir": tmp_path / "预备分_story",
        "text_path": tmp_path / "story.txt",
        "audio_path": tmp_path / "audio_full.mp3",
        "title": "story",
        "reusable_json": {"novel.json": reusable / "novel.json"},
    }
    calls = []
    app = object.__new__(gui.PipelineGUI)
    monkeypatch.setattr(
        app,
        "_create_queued_job",
        lambda title, text, **kwargs: calls.append((title, text, kwargs)) or "story",
    )
    job_dir = tmp_path / "jobs" / "story"
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(gui.pr, "job_dir_for", lambda _job_id: job_dir)

    created, errors = app._create_jobs_from_preliminary_packages([package])

    assert created == 1
    assert errors == []
    assert calls == [
        ("story", str(package["text_path"]), {"imported_audio_path": str(package["audio_path"])})
    ]
    assert (job_dir / "novel.json").read_text(encoding="utf-8") == "{}"
    assert "restored reusable text/story/character JSON" in (job_dir / "log.txt").read_text(encoding="utf-8")


def test_reimported_package_removes_task_when_reusable_json_copy_fails(monkeypatch, tmp_path):
    package = {
        "package_dir": tmp_path / "预备分_story",
        "text_path": tmp_path / "story.txt",
        "audio_path": tmp_path / "audio_full.mp3",
        "title": "story",
        "reusable_json": {"novel.json": tmp_path / "missing.json"},
    }
    app = object.__new__(gui.PipelineGUI)
    monkeypatch.setattr(app, "_create_queued_job", lambda *_args, **_kwargs: "story")
    monkeypatch.setattr(gui.pr, "job_dir_for", lambda _job_id: tmp_path / "jobs" / "story")
    deleted = []
    monkeypatch.setattr(gui.pr, "delete_job", lambda job_id: deleted.append(job_id))

    created, errors = app._create_jobs_from_preliminary_packages([package])

    assert created == 0
    assert deleted == ["story"]
    assert errors


def test_preliminary_confirmation_copy_says_mp4_is_not_retained():
    source = Path(gui.__file__).read_text(encoding="utf-8")

    assert "不保留任何 MP4" in source
    assert "正文分段、故事背景和人物设定 JSON" in source
    assert "标题、配图和视频会重新制作" in source


def test_windows_file_import_chooser_opens_file_dialog_without_prompt(monkeypatch, tmp_path):
    """The file entry must not add an intermediate choice prompt on Windows."""
    text_path = tmp_path / "story.txt"
    text_path.write_text("正文", encoding="utf-8")
    monkeypatch.setattr(gui.sys, "platform", "win32")
    monkeypatch.setattr(
        gui.messagebox,
        "askyesnocancel",
        lambda *_args, **_kwargs: pytest.fail("file import must not show an intermediate prompt"),
    )
    monkeypatch.setattr(gui.filedialog, "askopenfilenames", lambda **_kwargs: (str(text_path),))

    assert gui._choose_import_files_and_folders() == [text_path]


def test_windows_folder_import_chooser_returns_selected_folder(monkeypatch, tmp_path):
    """The folder entry returns the confirmed folder for recursive scanning."""
    folder = tmp_path / "novel"
    folder.mkdir()
    monkeypatch.setattr(gui.sys, "platform", "win32")
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **_kwargs: str(folder))

    assert gui._choose_import_folders() == [folder]
