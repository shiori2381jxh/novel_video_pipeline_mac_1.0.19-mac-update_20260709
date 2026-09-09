from pathlib import Path

from app import project_manager
from app.config import DEFAULT_SETTINGS
from app.scrapers.qingtian import QingtianAggregateScraper
from app.scrapers.base import NovelChapter
from app import pipeline_runner


def test_new_project_persists_disabled_editable_longform_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "projects")
    project_manager.PROJECTS_DIR.mkdir()

    project = project_manager.create_project("长篇小说")

    assert project["longform"] == {
        "enabled": False,
        "min_final_chars": 22000,
        "max_final_chars": 88000,
        "batch_episode_count": 5,
        "project_name_memory_enabled": False,
        "project_character_lock_enabled": False,
        "rewrite_replacement_categories": ["人名"],
        "source": {},
        "completed_next_chapter": 1,
        "reserved_next_chapter": 1,
        "batches": [],
    }
    assert project_manager.load_project(project["project_id"])["longform"] == project["longform"]


def test_paused_batch_keeps_completed_cursor_and_reserves_its_range(monkeypatch, tmp_path):
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "projects")
    project_manager.PROJECTS_DIR.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("第1章\n正文", encoding="utf-8")
    project = project_manager.create_project("长篇小说")
    project_manager.bind_longform_source(
        project["project_id"], kind="txt", reference=str(source), title="长篇小说"
    )
    batch = project_manager.create_longform_batch(
        project["project_id"],
        [{"start_chapter": 1, "end_chapter": 3}, {"start_chapter": 4, "end_chapter": 6}],
        {"min_minutes": 60, "max_minutes": 240, "batch_episode_count": 2},
    )
    project_manager.attach_longform_batch_jobs(project["project_id"], batch["batch_id"], ["episode-1", "episode-2"])
    project_manager.pause_longform_batch(project["project_id"], batch["batch_id"], "episode-1", "TTS failed")

    saved = project_manager.load_project(project["project_id"])["longform"]
    assert saved["completed_next_chapter"] == 1
    assert saved["reserved_next_chapter"] == 7
    assert saved["batches"][0]["state"] == "paused"
    assert saved["batches"][0]["failed_job_id"] == "episode-1"


def test_longform_defaults_are_part_of_editable_production_settings():
    assert DEFAULT_SETTINGS["longform_default_min_final_chars"] == 22_000
    assert DEFAULT_SETTINGS["longform_default_max_final_chars"] == 88_000
    assert DEFAULT_SETTINGS["longform_default_batch_episode_count"] == 5


def test_old_minute_longform_record_migrates_to_final_character_range():
    settings = project_manager.normalize_longform_settings({"min_minutes": 2, "max_minutes": 3})

    assert settings["min_final_chars"] == 44_000
    assert settings["max_final_chars"] == 66_000


def test_longform_project_normalizes_rewrite_categories():
    settings = project_manager.normalize_longform_settings(
        {"rewrite_replacement_categories": "人名、城市名\n地点、种族名"}
    )

    assert settings["rewrite_replacement_categories"] == ["人名", "地名", "种族名"]


def test_qingtian_range_fetch_reads_only_requested_catalog_entries(monkeypatch):
    scraper = QingtianAggregateScraper.__new__(QingtianAggregateScraper)
    scraper.site_name = "qingtian"
    scraper.source = "番茄"
    scraper.media = "小说"
    monkeypatch.setattr(scraper, "_resolve_book", lambda _ref: {"book_id": "book", "book_name": "书", "source": "番茄", "tab": "小说"})
    monkeypatch.setattr(scraper, "_fetch_catalog", lambda **_kwargs: [{"title": f"第{i}章"} for i in range(1, 6)])
    calls = []
    monkeypatch.setattr(scraper, "_fetch_content", lambda chapter, **_kwargs: calls.append(chapter["title"]) or chapter["title"])

    novel = scraper.fetch_chapter_range("qingtian://book", 2, 3)

    assert [chapter.index for chapter in novel.chapters] == [2, 3]
    assert calls == ["第2章", "第3章"]


def test_episode_planner_never_cuts_a_chapter_to_reach_target_characters():
    chapters = [
        NovelChapter(index=1, title="第1章", text="甲" * 4_000),
        NovelChapter(index=2, title="第2章", text="乙" * 4_000),
        NovelChapter(index=3, title="第3章", text="丙" * 4_000),
    ]

    episodes, warnings = pipeline_runner.plan_longform_episodes(
        chapters, min_final_chars=8_000, max_final_chars=10_000, minimum_rewrite_ratio=1.0, count=2
    )

    assert [(episode["start_chapter"], episode["end_chapter"]) for episode in episodes] == [(1, 2), (3, 3)]
    assert warnings == []


def test_queue_selector_keeps_next_episode_behind_earlier_batch_member(monkeypatch):
    project = {"longform": {"batches": [{"batch_id": "batch-a", "state": "queued", "members": [
        {"job_id": "a1", "order": 1}, {"job_id": "a2", "order": 2}
    ]}]}}
    monkeypatch.setattr(pipeline_runner.projects, "load_project", lambda _project_id: project)
    rows = [
        {"job_id": "other", "stage": "queued", "_status": {}},
        {"job_id": "a2", "stage": "queued", "_status": {"project_id": "p", "longform_batch_id": "batch-a", "longform_batch_order": 2}},
        {"job_id": "a1", "stage": "queued", "_status": {"project_id": "p", "longform_batch_id": "batch-a", "longform_batch_order": 1}},
    ]

    assert pipeline_runner.select_next_queued_job(rows) == "a1"


def test_queue_selector_blocks_other_jobs_while_a_batch_member_is_running(monkeypatch):
    project = {"longform": {"batches": [{"batch_id": "batch-a", "state": "running", "members": [
        {"job_id": "a1", "order": 1, "state": "queued"}, {"job_id": "a2", "order": 2, "state": "queued"}
    ]}]}}
    monkeypatch.setattr(pipeline_runner.projects, "load_project", lambda _project_id: project)
    rows = [
        {"job_id": "a1", "stage": "running", "_status": {"worker_alive": True, "project_id": "p", "longform_batch_id": "batch-a", "longform_batch_order": 1}},
        {"job_id": "a2", "stage": "queued", "_status": {"project_id": "p", "longform_batch_id": "batch-a", "longform_batch_order": 2}},
        {"job_id": "other", "stage": "queued", "_status": {}},
    ]

    assert pipeline_runner.select_next_queued_job(rows) is None


def test_failure_helper_pauses_its_longform_batch(monkeypatch):
    monkeypatch.setattr(pipeline_runner, "load_status", lambda _job_id: {"project_id": "p", "longform_batch_id": "batch-a"})
    calls = []
    monkeypatch.setattr(pipeline_runner.projects, "pause_longform_batch", lambda *args: calls.append(args))

    pipeline_runner.pause_longform_batch_for_job("a1", "TTS failed")

    assert calls == [("p", "batch-a", "a1", "TTS failed")]


def test_resuming_paused_batch_only_requeues_its_failed_member(monkeypatch, tmp_path):
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "projects")
    project_manager.PROJECTS_DIR.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("第1章\n正文", encoding="utf-8")
    project = project_manager.create_project("长篇")
    project_manager.bind_longform_source(project["project_id"], kind="txt", reference=str(source), title="长篇")
    batch = project_manager.create_longform_batch(project["project_id"], [{"start_chapter": 1, "end_chapter": 1}, {"start_chapter": 2, "end_chapter": 2}], {})
    project_manager.attach_longform_batch_jobs(project["project_id"], batch["batch_id"], ["a1", "a2"])
    project_manager.pause_longform_batch(project["project_id"], batch["batch_id"], "a1", "failed")

    saved = project_manager.resume_longform_batch(project["project_id"], batch["batch_id"])

    resumed = saved["longform"]["batches"][0]
    assert resumed["state"] == "queued"
    assert [member["state"] for member in resumed["members"]] == ["queued", "queued"]


def test_completed_member_advances_cursor_only_when_batch_finishes(monkeypatch, tmp_path):
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "projects")
    project_manager.PROJECTS_DIR.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("第1章\n正文", encoding="utf-8")
    project = project_manager.create_project("长篇")
    project_manager.bind_longform_source(project["project_id"], kind="txt", reference=str(source), title="长篇")
    batch = project_manager.create_longform_batch(project["project_id"], [{"start_chapter": 1, "end_chapter": 2}, {"start_chapter": 3, "end_chapter": 4}], {})
    project_manager.attach_longform_batch_jobs(project["project_id"], batch["batch_id"], ["a1", "a2"])

    project_manager.complete_longform_member(project["project_id"], batch["batch_id"], "a1")
    assert project_manager.load_project(project["project_id"])["longform"]["completed_next_chapter"] == 1
    project_manager.complete_longform_member(project["project_id"], batch["batch_id"], "a2")
    saved = project_manager.load_project(project["project_id"])["longform"]
    assert saved["completed_next_chapter"] == 5
    assert saved["batches"][0]["state"] == "completed"


def test_planner_uses_reserved_cursor_and_freezes_its_settings(monkeypatch):
    project = {
        "project_id": "p",
        "name": "长篇",
        "jobs": [],
        "longform": {
            "enabled": True,
            "min_final_chars": 22_000,
            "max_final_chars": 88_000,
            "batch_episode_count": 5,
            "reserved_next_chapter": 3,
            "source": {"kind": "txt", "reference": "C:/novel.txt", "title": "长篇"},
        },
    }
    chapters = [NovelChapter(index=index, title=f"第{index}章", text="甲" * 5000) for index in range(1, 5)]
    monkeypatch.setattr(pipeline_runner.projects, "load_project", lambda _id: project)
    monkeypatch.setattr(pipeline_runner, "_local_longform_chapters", lambda _path: chapters)
    monkeypatch.setattr(Path, "is_file", lambda _path: True)
    captured = {}
    monkeypatch.setattr(pipeline_runner.projects, "create_longform_batch", lambda _id, episodes, settings: captured.update(episodes=episodes, settings=settings) or {"batch_id": "b", "members": [{"order": 1}]})
    monkeypatch.setattr(pipeline_runner, "create_longform_jobs_from_episodes", lambda *_args: ["job"])

    pipeline_runner.create_next_longform_local_batch("p")

    assert captured["episodes"][0]["start_chapter"] == 3
    assert captured["settings"]["min_final_chars"] == 22_000


def test_project_name_ledger_keeps_first_canonical_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "projects")
    project_manager.PROJECTS_DIR.mkdir()
    project = project_manager.create_project("长篇")

    project_manager.merge_project_name_ledger(project["project_id"], [{"source": "林晚", "target": "早川澪"}])
    ledger = project_manager.merge_project_name_ledger(project["project_id"], [{"source": "林晚", "target": "别的名字"}])

    assert ledger["mappings"]["林晚"]["target"] == "早川澪"


def test_disabled_longform_character_lock_does_not_merge_project_profiles(monkeypatch, tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    pipeline_runner._write_json(job_dir / "status.json", {"project_id": "p"})
    monkeypatch.setattr(pipeline_runner, "series_animation_enabled_for_job", lambda _job: True)
    monkeypatch.setattr(pipeline_runner.projects, "load_project", lambda _id: {"longform": {"source": {"kind": "book"}, "project_character_lock_enabled": False}})
    merged = []
    monkeypatch.setattr(pipeline_runner.projects, "merge_character_profiles", lambda *_args: merged.append(True))

    result = pipeline_runner.share_series_character_analysis(job_dir, {"enabled": True, "characters": [{"name": "林晚"}]})

    assert result["characters"][0]["name"] == "林晚"
    assert merged == []


def test_txt_longform_source_is_copied_into_project_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "projects")
    project_manager.PROJECTS_DIR.mkdir()
    source = tmp_path / "novel.txt"
    source.write_text("第1章\n正文", encoding="utf-8")
    project = project_manager.create_project("长篇")

    saved = project_manager.bind_longform_source(project["project_id"], kind="txt", reference=str(source), title="长篇")

    ref = saved["longform"]["source"]["reference"]
    assert ref != str(source)
    assert Path(ref).read_text(encoding="utf-8") == "第1章\n正文"
