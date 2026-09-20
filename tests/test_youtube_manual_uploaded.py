from app import gui
from app import script_publish_scheduler as scheduler


def test_youtube_context_column_detection_uses_visible_tree_column():
    class Tree:
        def identify_column(self, _x):
            return "#3"

        def column(self, column, option):
            assert (column, option) == ("#3", "id")
            return "youtube"

    app = object.__new__(gui.PipelineGUI)
    app.job_tree = Tree()

    assert app._is_youtube_context_column(type("Event", (), {"x": 30})()) is True


def test_manual_uploaded_status_is_displayed_without_a_youtube_url(monkeypatch, tmp_path):
    app = object.__new__(gui.PipelineGUI)
    monkeypatch.setattr(gui.pr, "job_dir_for", lambda _job_id: tmp_path / "job")

    assert app._youtube_queue_status("story", {"youtube_manually_marked_uploaded": True}) == "✓ 上传成功"


def test_mark_selected_jobs_uploaded_persists_status_and_log(monkeypatch, tmp_path):
    app = object.__new__(gui.PipelineGUI)
    monkeypatch.setattr(app, "_selected_job_ids", lambda: ["story", "story_2"])
    monkeypatch.setattr(gui.pr, "job_dir_for", lambda job_id: tmp_path / job_id)
    writes = []
    logs = []
    refreshed = []
    monkeypatch.setattr(gui.pr, "write_status", lambda path, **values: writes.append((path, values)))
    monkeypatch.setattr(gui.pr, "append_log", lambda path, message: logs.append((path, message)))
    monkeypatch.setattr(app, "_refresh_jobs", lambda: refreshed.append(True))

    app._mark_selected_jobs_youtube_uploaded()

    assert [values for _path, values in writes] == [
        {"youtube_manually_marked_uploaded": True, "upload_error": ""},
        {"youtube_manually_marked_uploaded": True, "upload_error": ""},
    ]
    assert len(logs) == 2
    assert refreshed == [True]


def test_script_scheduler_skips_manually_marked_uploaded_jobs():
    rows = scheduler._ordered_candidates(
        [
            ("uploaded", {"youtube_manually_marked_uploaded": True}),
            ("pending", {"title": "待上传"}),
        ]
    )

    assert [job_id for job_id, *_rest in rows] == ["pending"]
