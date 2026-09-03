import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from app import config as config_module
from app import pipeline_runner
from app import project_manager
from app.gui import PipelineGUI, _choose_import_folders
from app.character_analysis import normalize_analysis
from app.backends.image import ImageBackend
from app.backends import tts as tts_backend_module
from app.backends.tts import (
    TTSBackend,
    VOXCPM_FAVORITE_VOICES,
    VOXCPM_VOICE_BUNDLE,
    VOXCPM_VOICE_CATALOG,
    edge_voice_choices,
    normalize_voxcpm_voice,
    preferred_available_edge_voice,
    voxcpm_voice_choices,
    voxcpm_voice_display,
)
from app.stages.stage6_compose import _video_encoder_args
from app.storyboard_highlights import parse_json_object
from app.tts_audition import audition_directory, audition_filename, audition_text_for_voice


class ImagePromptRegressionTests(unittest.TestCase):
    def test_repeated_safety_pass_preserves_three_kingdoms_scene(self):
        scene = (
            "Depict mainland Chinese late Han dynasty people and places only; never Japanese samurai or kimono. "
            "Scene-specific Three Kingdoms event: Lu Bu catches Zhang Liao's blade between two fingers."
        )
        prompt = pipeline_runner._policy_safe_image_prompt(scene)
        prompt = pipeline_runner._policy_safe_image_prompt(prompt)
        prompt = pipeline_runner._policy_safe_image_prompt(prompt)

        self.assertIn("Lu Bu catches Zhang Liao's blade", prompt)
        self.assertIn("mainland Chinese late Han dynasty", prompt)
        self.assertEqual(prompt.count("Strict final requirement:"), 1)
        self.assertLessEqual(len(prompt), 1400)

    def test_long_repeated_prompt_keeps_scene_tail(self):
        prefix = "historical illustration, " * 80
        scene = "SCENE_ANCHOR Cao Cao raises a jade bracelet inside a late Han residence."
        prompt = pipeline_runner._policy_safe_image_prompt(prefix + scene)
        prompt = pipeline_runner._policy_safe_image_prompt(prompt)
        self.assertIn("SCENE_ANCHOR", prompt)

    def test_short_reuse_changes_only_explicit_output_size_language(self):
        original = (
            "cinematic horizontal 16:9 composition, Alice in a red coat opens the gate, "
            "wide shot, moonlight, output 1792x1008"
        )
        converted = pipeline_runner._portrait_prompt_from_main(original, 1024, 1792)

        self.assertIn("portrait 9:16 composition", converted)
        self.assertIn("1024x1792", converted)
        self.assertIn("Alice in a red coat opens the gate", converted)
        self.assertIn("wide shot", converted)
        self.assertIn("moonlight", converted)

    def test_short_reuse_adds_size_only_when_main_prompt_has_no_size(self):
        original = "wide shot, Alice opens the gate, watercolor style"
        converted = pipeline_runner._portrait_prompt_from_main(original, 1024, 1792)

        self.assertTrue(converted.startswith(original))
        self.assertIn("Output aspect ratio 9:16", converted)
        self.assertIn("output size 1024x1792", converted)


class ShortScriptRegressionTests(unittest.TestCase):
    def test_marketing_bundle_accepts_prebuilt_short_script(self):
        payload = {
            "titles": ["A", "B", "C"],
            "synopses": ["S1", "S2"],
            "tags": ["#one"],
            "short_script": "开场钩子。冲突升级。最后留下悬念。",
        }
        parsed = pipeline_runner._parse_marketing_candidates(payload)
        self.assertEqual(parsed["short_script"], payload["short_script"])

    def test_prebuilt_short_script_respects_max_chars_at_sentence_boundary(self):
        original = "第一句话。" * 100
        cleaned = pipeline_runner._clean_prebuilt_short_script(original, 350)
        self.assertLessEqual(len(cleaned), 350)
        self.assertTrue(cleaned.endswith("。"))

    def test_default_short_prompt_requires_distillation_not_three_part_summary(self):
        prompt = config_module.DEFAULT_SETTINGS["short_video_script_prompt"]
        self.assertIn("資料の順番どおりに朗読・要約せず", prompt)
        self.assertIn("視聴者を最も引きつける核心", prompt)
        self.assertIn("最初の一文で最も強い対立", prompt)
        self.assertIn("自然な日本語の一段落だけ", prompt)

    def test_short_script_language_guard_rejects_chinese_only_output(self):
        self.assertTrue(pipeline_runner._looks_like_japanese_short_script("彼女が扉を開けると、そこには失踪したはずの兄が立っていた。"))
        self.assertFalse(pipeline_runner._looks_like_japanese_short_script("她推开门后，失踪多年的哥哥竟然站在眼前。"))

    def test_chinese_short_profile_accepts_chinese_and_rejects_japanese(self):
        chinese = "她推开门后，失踪多年的哥哥竟然站在眼前，真正的危机才刚刚开始。"
        japanese = "彼女が扉を開けると、そこには失踪したはずの兄が立っていた。"
        self.assertEqual(pipeline_runner._configured_text_language("只输出自然简体中文旁白"), "zh")
        self.assertTrue(pipeline_runner._looks_like_chinese_short_script(chinese))
        self.assertFalse(pipeline_runner._looks_like_chinese_short_script(japanese))
        bundle = {"short_script": chinese}
        self.assertEqual(
            pipeline_runner._prebuilt_short_script_error(bundle, True, 350, "zh"), ""
        )

    def test_marketing_length_error_identifies_exact_title(self):
        bundle = {
            "titles": ["甲" * 45, "乙" * 39, "丙" * 44],
            "synopses": ["甲" * 90, "乙" * 90],
            "tags": [f"#标签{i}" for i in range(10)],
        }
        error = pipeline_runner._marketing_validation_error(bundle, 40, 70)
        self.assertIn("title2=39", error)

    def test_source_episode_accepts_three_kingdoms_chapter_headings(self):
        self.assertEqual(pipeline_runner._source_episode_from_job_name("《三国演义》第一回"), "一")
        self.assertEqual(pipeline_runner._source_episode_from_job_name("三国群英第12期"), "12")
        self.assertEqual(pipeline_runner._source_episode_from_job_name("三国群英志1_润色"), "1")
        self.assertEqual(
            pipeline_runner._source_episode_label_from_job_name("三国群英志1_润色"), "第1话"
        )
        self.assertEqual(
            pipeline_runner._source_episode_label_from_job_name("三国群英志254-256"),
            "第254话～第256话",
        )
        self.assertEqual(
            pipeline_runner._source_episode_label_from_job_name("没有话数的标题"), ""
        )

    def test_chinese_history_titles_allow_at_most_one_question_hook(self):
        too_many_questions = {
            "titles": [
                "《临江仙》为什么成为三国演义卷首最经典的开篇词？",
                "杨慎与罗贯中相隔百余年，这首词为何仍与三国相连？",
                "毛宗岗父子重订三国演义，让秦汉兴亡之词成为全书总纲",
            ]
        }
        self.assertIn(
            "too many question hooks",
            pipeline_runner._marketing_title_style_error(too_many_questions, "zh"),
        )
        balanced = {
            "titles": [
                "杨慎写秦汉兴亡，毛宗岗父子重订时将《临江仙》置于三国卷首",
                "一首原本概括秦汉盛衰的词，后来成为三国英雄登场前的全书总纲",
                "杨慎与罗贯中相隔百余年，《临江仙》为何最终与三国故事相连？",
            ]
        }
        self.assertEqual(pipeline_runner._marketing_title_style_error(balanced, "zh"), "")

    def test_chinese_history_candidates_do_not_repeat_program_label(self):
        bundle = {"titles": ["三国志完全解说第一话：黄巾之乱拉开汉末群雄序幕"]}
        self.assertIn(
            "fixed series label",
            pipeline_runner._marketing_title_style_error(bundle, "zh"),
        )

    def test_cover_prompt_blocks_unresolved_internal_tokens(self):
        self.assertIn(
            "source_episode_label",
            pipeline_runner._cover_prompt_internal_token_error(
                "Render exact text {source_episode_label}"
            ),
        )
        self.assertIn(
            "_source_input",
            pipeline_runner._cover_prompt_internal_token_error(
                "Do something with _source_input"
            ),
        )
        self.assertEqual(
            pipeline_runner._cover_prompt_internal_token_error(
                "Render exact text 【三国志完全解说】第1话"
            ),
            "",
        )

    def test_cover_text_guard_is_language_neutral_and_forbids_microtext(self):
        prompt = pipeline_runner._policy_safe_image_prompt(
            "Render exact Chinese title 【三国志完全解说】第1话",
            allow_title_text=True,
        )
        self.assertIn("Strict typography whitelist", prompt)
        self.assertIn("Do not invent any additional header strip, microtext", prompt)
        self.assertNotIn("Japanese editorial text", prompt)

    def test_short_timeline_hard_caps_overlong_narration(self):
        segments = [pipeline_runner.Segment(0, "A"), pipeline_runner.Segment(1, "B")]
        kept_segments, durations = pipeline_runner._clip_short_timeline(segments, [40.0, 35.0], 60.0)
        self.assertEqual(len(kept_segments), 2)
        self.assertAlmostEqual(sum(durations), 60.0)


class EncoderQualityRegressionTests(unittest.TestCase):
    def test_videotoolbox_inverts_crf_style_quality_scale(self):
        args_20 = _video_encoder_args("h264_videotoolbox", quality=20)
        args_30 = _video_encoder_args("h264_videotoolbox", quality=30)
        q20 = int(args_20[args_20.index("-q:v") + 1])
        q30 = int(args_30[args_30.index("-q:v") + 1])
        self.assertEqual(q20, 62)
        self.assertGreater(q20, q30)

    def test_x264_keeps_crf_value(self):
        args = _video_encoder_args("libx264", quality=20)
        self.assertEqual(args[args.index("-crf") + 1], "20")


class EdgeVoiceDiscoveryRegressionTests(unittest.TestCase):
    def test_discovered_voices_follow_curated_choices_without_hiding_retired_voices(self):
        choices = edge_voice_choices(
            ["ja-JP-NanamiNeural", "xx-YY-NewVoiceNeural"],
            "ja-JP-AoiNeural",
        )

        self.assertIn("ja-JP-AoiNeural", choices)
        self.assertIn("ja-JP-NanamiNeural", choices)
        self.assertIn("xx-YY-NewVoiceNeural", choices)
        self.assertLess(choices.index("ja-JP-NanamiNeural"), choices.index("xx-YY-NewVoiceNeural"))

    def test_retired_japanese_voice_falls_back_to_available_japanese_voice(self):
        replacement = preferred_available_edge_voice(
            "ja-JP-AoiNeural",
            ["en-US-AriaNeural", "ja-JP-KeitaNeural", "ja-JP-NanamiNeural"],
        )

        self.assertEqual(replacement, "ja-JP-NanamiNeural")

    def test_existing_available_voice_is_preserved(self):
        self.assertEqual(
            preferred_available_edge_voice(
                "ja-JP-KeitaNeural",
                ["ja-JP-KeitaNeural", "ja-JP-NanamiNeural"],
            ),
            "ja-JP-KeitaNeural",
        )


class JsonCompatibilityRegressionTests(unittest.TestCase):
    def test_extracts_first_object_with_trailing_commentary(self):
        self.assertEqual(parse_json_object('Result: {"action": "ride"}\nDone.'), {"action": "ride"})

    def test_accepts_double_encoded_object(self):
        self.assertEqual(parse_json_object('"{\\"action\\": \\"ride\\"}"'), {"action": "ride"})

    def test_empty_upload_description_survives_config_migration(self):
        data = dict(config_module.DEFAULT_SETTINGS)
        data["youtube_description"] = ""
        config_module._apply_compat_migrations(data, {"settings_schema_version": 1})
        self.assertEqual(data["youtube_description"], "")

    def test_cover_prompt_fields_survive_config_migration_verbatim(self):
        saved = {
            "settings_schema_version": 1,
            "cover_prompt_template": "custom 1280x720 cover template",
            "cover_custom_prompt": "my deliberate high contrast direction",
            "cover_ai_analysis_prompt": "my analysis method",
            "cover_poster_method_prompt": "my complete poster method",
            "cover_prompt_max_tokens": 420,
        }
        data = dict(config_module.DEFAULT_SETTINGS)
        data.update(saved)

        config_module._apply_compat_migrations(data, saved)

        for key, value in saved.items():
            if key.startswith("cover_"):
                self.assertEqual(data[key], value)


class ImportDialogRegressionTests(unittest.TestCase):
    def test_folder_dialog_is_parented_and_uses_standard_existing_folder_picker(self):
        parent = object()
        with patch("app.gui.filedialog.askdirectory", return_value="/tmp/novel") as chooser:
            selected = _choose_import_folders(parent)

        self.assertEqual(selected, [Path("/tmp/novel")])
        chooser.assert_called_once_with(
            parent=parent,
            title="选择包含小说 TXT 的文件夹",
            mustexist=True,
        )

    def test_cancelled_folder_dialog_returns_no_selection(self):
        with patch("app.gui.filedialog.askdirectory", return_value=""):
            self.assertEqual(_choose_import_folders(object()), [])


class NovelProjectRegressionTests(unittest.TestCase):
    def test_new_project_locks_manual_shared_novel_title_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"):
                project = project_manager.create_project(
                    "内部管理名",
                    series_video_settings={
                        "shared_novel_title": "人工统一小说名",
                    },
                )
                loaded = project_manager.load_project(project["project_id"])

        settings = loaded["series_video_settings"]
        self.assertEqual(settings["shared_novel_title"], "人工统一小说名")
        self.assertTrue(settings["shared_novel_title_locked"])

    def test_locked_shared_title_skips_series_name_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            jobs.mkdir()
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"), patch.object(
                pipeline_runner, "JOBS_DIR", jobs
            ):
                project = project_manager.create_project(
                    "内部管理名",
                    series_video_settings={
                        "shared_novel_title": "人工统一小说名",
                        "shared_novel_title_locked": True,
                    },
                )
                job_dir = jobs / "episode_1"
                pipeline_runner.write_status(
                    job_dir,
                    project_id=project["project_id"],
                    series_title="人工统一小说名",
                    series_episode=1,
                )
                with patch.object(
                    pipeline_runner,
                    "_can_call_text_llm",
                    side_effect=AssertionError("不应检查或调用系列名 AI"),
                ):
                    result = pipeline_runner._series_short_name_from_existing_titles(
                        job_dir,
                        ["每集标题"],
                        lambda _message: None,
                    )

        self.assertEqual(result, "人工统一小说名")

    def test_series_title_and_cover_templates_use_manual_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            jobs.mkdir()
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"), patch.object(
                pipeline_runner, "JOBS_DIR", jobs
            ):
                project = project_manager.create_project(
                    "内部管理名",
                    series_video_settings={
                        "shared_novel_title": "人工统一小说名",
                        "shared_novel_title_locked": True,
                        "episode_label_style": "第{episode}集",
                        "upload_title_template": "{series_title}｜{episode_label}｜{ai_title}",
                        "cover_label_template": "{series_title}【{episode_label}】",
                    },
                )
                job_dir = jobs / "episode_2"
                pipeline_runner.write_status(
                    job_dir,
                    project_id=project["project_id"],
                    series_title="人工统一小说名",
                    series_episode=2,
                )
                result = pipeline_runner.apply_series_presentation(
                    {
                        "titles": ["这一集发生了重大逆转"],
                        "short_title": "这一集发生了重大逆转",
                    },
                    job_dir,
                )

        self.assertEqual(result["series_upload_prefix"], "人工统一小说名｜第2集｜")
        self.assertEqual(result["series_cover_label"], "人工统一小说名【第2集】")
        self.assertEqual(
            result["series_display_title"],
            "人工统一小说名｜第2集｜这一集发生了重大逆转",
        )

    def test_forced_project_import_assigns_sequence_from_configured_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "甲.txt"
            second = root / "乙.txt"
            first.write_text("正文", encoding="utf-8")
            second.write_text("正文", encoding="utf-8")
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"):
                project = project_manager.create_project(
                    "预建项目",
                    series_video_settings={
                        "shared_novel_title": "统一小说名",
                        "episode_start": 5,
                    },
                )
                gui = PipelineGUI.__new__(PipelineGUI)
                assignments = gui._project_assignments_for_forced_import(
                    project["project_id"],
                    [second, first],
                )

        self.assertEqual(
            {
                assignments[str(first.resolve(strict=False))]["episode"],
                assignments[str(second.resolve(strict=False))]["episode"],
            },
            {5, 6},
        )

    def test_disabling_ai_episode_titles_uses_local_fallback_without_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            jobs.mkdir()
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"), patch.object(
                pipeline_runner, "JOBS_DIR", jobs
            ):
                project = project_manager.create_project(
                    "预建项目",
                    series_video_settings={
                        "shared_novel_title": "人工统一小说名",
                        "shared_novel_title_locked": True,
                        "ai_episode_title_enabled": False,
                    },
                )
                job_dir = jobs / "episode_1"
                pipeline_runner.write_status(
                    job_dir,
                    project_id=project["project_id"],
                    series_title="人工统一小说名",
                    series_episode=1,
                )
                novel = pipeline_runner.Novel(
                    site="local",
                    novel_id="episode-1",
                    title="原始标题",
                    author="",
                    description="",
                    chapters=[
                        pipeline_runner.NovelChapter(
                            index=1,
                            title="正文",
                            text=(
                                "主人公在会议上公开证据，局势发生逆转。所有人终于发现真正的幕后人物。"
                                "她随后说明证据的来源，并揭开多年前被隐藏的约定。"
                                "昔日的同伴重新站到她身边，反对者也不得不承认事实。"
                            ),
                        )
                    ],
                )
                segments = [
                    pipeline_runner.Segment(
                        index=0,
                        text=(
                            "主人公在会议上公开证据，局势发生逆转。所有人终于发现真正的幕后人物。"
                            "她随后说明证据的来源，并揭开多年前被隐藏的约定。"
                            "昔日的同伴重新站到她身边，反对者也不得不承认事实。"
                        ),
                    )
                ]
                with patch.object(
                    pipeline_runner,
                    "_can_call_text_llm",
                    side_effect=AssertionError("关闭后不应检查或调用标题 LLM"),
                ):
                    metadata = pipeline_runner.stage_metadata(
                        novel,
                        job_dir,
                        segments=segments,
                    )
                generation_attempts = json.loads(
                    (job_dir / "marketing_candidates.json").read_text(encoding="utf-8")
                )["generation_attempts"]

        self.assertTrue(metadata["titles"])
        self.assertEqual(generation_attempts, 0)

    def test_character_analysis_keeps_relationship_records(self):
        normalized = normalize_analysis({
            "characters": [{"name": "林月"}, {"name": "周宁"}],
            "relationships": [{
                "from": "林月",
                "to": "周宁",
                "relation": "同伴",
            }],
        })
        self.assertEqual(
            normalized["relationships"],
            [{"from": "林月", "to": "周宁", "relation": "同伴", "record_status": "auto"}],
        )

    def test_import_detection_groups_common_episode_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / "长篇小说_01.txt",
                root / "长篇小说_02.txt",
                root / "长篇小说_03.txt",
            ]
            for path in paths:
                path.write_text("正文", encoding="utf-8")
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"):
                groups = project_manager.detect_import_groups(paths)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "长篇小说")
        self.assertEqual(
            [groups[0]["episodes"][str(path)] for path in paths],
            [1, 2, 3],
        )

    def test_existing_project_is_suggested_for_later_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            later = source / "银河物语_06.txt"
            later.write_text("正文", encoding="utf-8")
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"):
                created = project_manager.create_project(
                    "银河物语",
                    source_directories=[source],
                )
                groups = project_manager.detect_import_groups([later])

        self.assertEqual(len(groups), 1)
        self.assertEqual(
            groups[0]["existing_project"]["project_id"],
            created["project_id"],
        )
        self.assertEqual(groups[0]["episodes"][str(later)], 6)

    def test_confirmed_character_profile_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"):
                project = project_manager.create_project("人物锁测试")
                project_id = project["project_id"]
                project_manager.merge_character_profiles(
                    project_id,
                    {
                        "enabled": True,
                        "characters": [{
                            "name": "林月",
                            "aliases": ["月月"],
                            "hair": "black",
                            "record_status": "confirmed",
                        }],
                    },
                )
                merged = project_manager.merge_character_profiles(
                    project_id,
                    {
                        "enabled": True,
                        "characters": [{
                            "name": "月月",
                            "hair": "red",
                            "eye_color": "brown",
                        }],
                    },
                )
                registry = json.loads(
                    (project_manager.project_dir(project_id) / "name_registry.json").read_text(
                        encoding="utf-8"
                    )
                )

        character = merged["characters"][0]
        self.assertEqual(character["hair"], "black")
        self.assertNotIn("eye_color", character)
        self.assertEqual(registry["names"][0]["name"], "林月")

    def test_character_reference_is_saved_once_in_project_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"):
                project = project_manager.create_project("共享人设图")
                project_id = project["project_id"]
                analysis = {
                    "enabled": True,
                    "visual_theme": {},
                    "protagonists": ["林月"],
                    "characters": [{
                        "name": "林月",
                        "trigger": "lin_yue",
                        "importance": "protagonist",
                        "visual_prompt_en": "adult woman, black hair, blue coat",
                        "reference_prompt_en": "full body adult woman, black hair, blue coat",
                    }],
                }
                paths = []
                with patch.dict(
                    pipeline_runner.config._data,
                    {
                        "ai_api_enabled": False,
                        "character_reference_enabled": True,
                        "character_reference_provider": "same_as_image",
                        "image_provider": "placeholder",
                    },
                ):
                    for number in (1, 2):
                        job_dir = root / f"job_{number}"
                        pipeline_runner.write_status(job_dir, project_id=project_id)
                        result = pipeline_runner.stage_character_references(
                            json.loads(json.dumps(analysis)),
                            job_dir,
                        )
                        paths.append(Path(result["characters"][0]["reference_image"]))

        self.assertEqual(paths[0], paths[1])
        self.assertIn(project_id, paths[0].parts)

    def test_legacy_series_migration_copies_reference_without_deleting_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            jobs.mkdir()
            reference = jobs / "old_1" / "characters" / "hero.png"
            reference.parent.mkdir(parents=True)
            Image.new("RGB", (32, 32), "blue").save(reference)
            for number in (1, 2):
                job_dir = jobs / f"old_{number}"
                job_dir.mkdir(parents=True, exist_ok=True)
                (job_dir / "status.json").write_text(
                    json.dumps({
                        "job_id": job_dir.name,
                        "series_group_key": "legacy-group",
                        "series_title": "旧系列",
                        "series_episode": number,
                        "source_directory": str(root / "source"),
                    }),
                    encoding="utf-8",
                )
            (jobs / ".series_character_profiles.json").write_text(
                json.dumps({
                    "legacy-group": {
                        "enabled": True,
                        "characters": [{
                            "name": "主角",
                            "trigger": "hero",
                            "reference_image": str(reference),
                        }],
                    }
                }),
                encoding="utf-8",
            )

            def write_status(job_dir, **updates):
                path = job_dir / "status.json"
                current = json.loads(path.read_text(encoding="utf-8"))
                current.update(updates)
                path.write_text(json.dumps(current), encoding="utf-8")

            with patch.object(project_manager, "PROJECTS_DIR", root / "projects"), patch.object(
                project_manager, "JOBS_DIR", jobs
            ):
                created = project_manager.migrate_legacy_series(
                    write_job_status=write_status
                )
                migrated_profile = project_manager.load_character_profiles(
                    created[0]["project_id"]
                )
                migrated_reference = Path(
                    migrated_profile["characters"][0]["reference_image"]
                )
                reference_copied = migrated_reference.is_file()
                job_preserved = (jobs / "old_1").exists()

        self.assertEqual(len(created), 1)
        self.assertTrue(reference_copied)
        self.assertTrue(job_preserved)


class PronunciationDictionaryRegressionTests(unittest.TestCase):
    def test_uploaded_dictionary_prepares_voicevox_text_without_mutating_subtitles(self):
        segments = [pipeline_runner.Segment(index=0, text="董卓と呂布が対峙した。")]
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / pipeline_runner.TTS_PRONUNCIATION_DICTIONARY).write_text(
                "董卓=とうたく\n呂布=りょふ\n",
                encoding="utf-8",
            )
            narration, counts, entries, dictionary_hash = pipeline_runner._prepare_tts_pronunciation(
                segments,
                job_dir,
                "voicevox",
            )
            subtitle = job_dir / "subtitle.srt"
            pipeline_runner.build_srt([(0.0, 2.0, segments[0].text)], subtitle)

            self.assertEqual(narration, ["とうたくとりょふが対峙した。"])
            self.assertEqual(counts, [2])
            self.assertEqual(len(entries), 2)
            self.assertTrue(dictionary_hash)
            self.assertEqual(segments[0].text, "董卓と呂布が対峙した。")
            self.assertIn("董卓と呂布", subtitle.read_text(encoding="utf-8"))
            self.assertNotIn("とうたく", subtitle.read_text(encoding="utf-8"))

    def test_uploaded_dictionary_stays_disabled_for_unrelated_tts_providers(self):
        segments = [pipeline_runner.Segment(index=0, text="董卓")]
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / pipeline_runner.TTS_PRONUNCIATION_DICTIONARY).write_text("董卓=とうたく\n", encoding="utf-8")
            narration, counts, entries, dictionary_hash = pipeline_runner._prepare_tts_pronunciation(
                segments,
                job_dir,
                "openai",
            )

        self.assertEqual(narration, ["董卓"])
        self.assertEqual(counts, [0])
        self.assertEqual(entries, [])
        self.assertEqual(dictionary_hash, "")


class VoxCPMRegressionTests(unittest.TestCase):
    def test_favorite_voice_catalog_resolves_every_reference_audio(self):
        self.assertIn("男｜自然情感", VOXCPM_FAVORITE_VOICES)
        self.assertGreaterEqual(len(VOXCPM_FAVORITE_VOICES), 5)
        for row in VOXCPM_VOICE_CATALOG.values():
            self.assertTrue((VOXCPM_VOICE_BUNDLE / "favorite_voices" / row["file"]).is_file())

    def test_voxcpm_ignores_subprocess_isolation_to_reuse_loaded_model(self):
        backend = TTSBackend("voxcpm", "男｜自然情感")
        with (
            patch.dict(pipeline_runner.config._data, {"tts_subprocess_isolation": True}),
            patch.object(backend, "synth", return_value=1.25) as synth,
            patch.object(pipeline_runner, "_synth_tts_subprocess") as isolated,
        ):
            duration = pipeline_runner._synth_tts_segment(backend, "测试", Path("out.mp3"), 180)

        self.assertEqual(duration, 1.25)
        synth.assert_called_once()
        isolated.assert_not_called()

    def test_audition_files_are_grouped_by_provider(self):
        self.assertEqual(audition_directory("edge").name, "edge")
        self.assertEqual(audition_filename("edge", "zh-CN-XiaoxiaoNeural"), "01_zh-CN-XiaoxiaoNeural.mp3")
        self.assertEqual(audition_filename("voxcpm", "男｜自然情感"), "02_男｜自然情感.mp3")

    def test_legacy_voxcpm_names_map_to_the_new_clear_labels(self):
        self.assertEqual(normalize_voxcpm_voice("1"), "男｜沉稳磁性")
        self.assertEqual(normalize_voxcpm_voice("2"), "男｜自然情感")
        self.assertEqual(normalize_voxcpm_voice("女声2"), "女｜大气情感")

    def test_voxcpm_audition_filename_renames_sync_back_to_voice_picker(self):
        with tempfile.TemporaryDirectory() as tmp:
            audition_dir = Path(tmp) / "TTS试听" / "voxcpm"
            audition_dir.mkdir(parents=True)
            (audition_dir / "01_我喜欢的男声.mp3").write_bytes(b"test")
            with patch.object(tts_backend_module, "ROOT", Path(tmp)):
                self.assertEqual(voxcpm_voice_choices()[0], "我喜欢的男声")
                self.assertEqual(voxcpm_voice_display("朗读音频"), "我喜欢的男声")
                self.assertEqual(normalize_voxcpm_voice("我喜欢的男声"), "男｜沉稳磁性")
                self.assertEqual(audition_filename("voxcpm", "我喜欢的男声"), "01_我喜欢的男声.mp3")

    def test_voicevox_audition_is_deliberately_skipped(self):
        with self.assertRaisesRegex(ValueError, "VOICEVOX"):
            audition_directory("voicevox")

    def test_audition_text_follows_voice_language(self):
        self.assertIn("こんにちは", audition_text_for_voice("edge", "ja-JP-NanamiNeural"))
        self.assertIn("你好", audition_text_for_voice("voxcpm", "2"))


class LocalSourceSafetyRegressionTests(unittest.TestCase):
    def test_missing_local_txt_never_reaches_network_scraper(self):
        with patch.object(pipeline_runner, "_build_scraper") as build_scraper:
            with self.assertRaisesRegex(FileNotFoundError, "不会把本地路径交给"):
                pipeline_runner.stage_scrape(
                    "/tmp/definitely-missing-novel-input.txt",
                    site="qingtian",
                )
        build_scraper.assert_not_called()

    def test_moved_local_source_is_relinked_and_snapshotted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "job"
            original = root / "library" / "716" / "story" / "story_01.txt"
            moved = root / "library" / "story" / original.name
            original.parent.mkdir(parents=True)
            moved.parent.mkdir(parents=True, exist_ok=True)
            job_dir.mkdir()
            original.write_text("これは正しい小説本文です。", encoding="utf-8")
            pipeline_runner.write_status(
                job_dir,
                input=str(original),
                source_path=str(original),
                source_kind="local_text",
            )
            pipeline_runner._resolve_job_input_source(job_dir, str(original))
            original.replace(moved)

            resolved = Path(pipeline_runner._resolve_job_input_source(job_dir, str(original)))
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))

            self.assertEqual(resolved, moved.resolve())
            self.assertEqual(Path(status["source_path"]), moved.resolve())
            self.assertEqual(
                Path(status["source_snapshot_path"]).read_text(encoding="utf-8"),
                "これは正しい小説本文です。",
            )

    def test_local_task_rejects_cached_network_novel(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            pipeline_runner.write_status(
                job_dir,
                source_path="/tmp/story.txt",
                source_kind="local_text",
            )
            wrong = pipeline_runner.Novel(
                site="qingtian",
                novel_id="wrong-book",
                title="unrelated",
                author="",
                description="",
                chapters=[
                    pipeline_runner.NovelChapter(index=1, title="chapter", text="別の本"),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "正文来源不一致"):
                pipeline_runner._validate_job_novel_source(job_dir, wrong)


class NarrationPunctuationRegressionTests(unittest.TestCase):
    def test_voicevox_preserves_authored_japanese_punctuation_and_line_endings(self):
        source = "「待って……！」\n彼女は――静かに、笑った〜。\n本当に？　はい！\n余韻—"
        with patch.dict(pipeline_runner.config._data, {"tts_provider": "voicevox"}):
            cleaned = pipeline_runner._clean_rewritten_narration_text(source)

        self.assertEqual(
            cleaned,
            source,
        )

    def test_voicevox_preserves_repeated_and_single_dashes(self):
        source = "彼女は---言葉を失った。単独の—は残す。"
        with patch.dict(pipeline_runner.config._data, {"tts_provider": "voicevox"}):
            cleaned = pipeline_runner._clean_rewritten_narration_text(source)
        self.assertEqual(cleaned, source)

    def test_edge_keeps_aggressive_punctuation_normalization(self):
        source = "「待って……！」彼女は――静かに、笑った〜。"
        with patch.dict(pipeline_runner.config._data, {"tts_provider": "edge"}):
            cleaned = pipeline_runner._clean_rewritten_narration_text(source)

        self.assertNotIn("「", cleaned)
        self.assertNotIn("」", cleaned)
        self.assertNotIn("――", cleaned)
        self.assertNotIn("〜", cleaned)
        self.assertIn("。", cleaned)
        self.assertIn("，", cleaned)


class WorkerQueueRegressionTests(unittest.TestCase):
    def test_capacity_limit_queues_without_raising_or_launching(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch.object(pipeline_runner, "JOBS_DIR", jobs_dir),
                patch.object(pipeline_runner, "count_running_workers", return_value=1),
                patch.object(pipeline_runner.subprocess, "Popen") as popen,
            ):
                job_id, pid = pipeline_runner.start_worker(
                    "saved input",
                    job_id="waiting-job",
                    resume=True,
                    compose_only=True,
                )

            status = json.loads((jobs_dir / job_id / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(pid, 0)
            self.assertEqual(status["stage"], "queued")
            self.assertEqual(status["input"], "saved input")
            self.assertTrue(status["queued_compose_only"])
            popen.assert_not_called()

    def test_auto_start_preserves_queued_compose_only_mode(self):
        queued_status = {
            "job_id": "waiting-job",
            "stage": "queued",
            "input": "saved input",
            "worker_alive": False,
            "queued_compose_only": True,
        }
        with (
            patch.object(pipeline_runner, "count_running_workers", return_value=0),
            patch.object(pipeline_runner, "list_jobs", return_value=[queued_status]),
            patch.object(pipeline_runner, "load_status", return_value=queued_status),
            patch.object(pipeline_runner, "start_worker", return_value=("waiting-job", 1234)) as start,
        ):
            self.assertEqual(pipeline_runner.start_next_queued_job(), ("waiting-job", 1234))

        start.assert_called_once_with(
            "saved input",
            job_id="waiting-job",
            resume=True,
            compose_only=True,
            marketing_cover_only=False,
            preprocess_only=False,
        )

    def test_fill_available_worker_slots_starts_idle_queue_to_capacity(self):
        with (
            patch.object(pipeline_runner.config, "get", return_value=2),
            patch.object(pipeline_runner, "count_running_workers", side_effect=[0, 1, 2]),
            patch.object(
                pipeline_runner,
                "start_next_queued_job",
                side_effect=[("first-job", 101), ("second-job", 102)],
            ) as start_next,
        ):
            started = pipeline_runner.fill_available_worker_slots(only_explicitly_queued=True)

        self.assertEqual(started, [("first-job", 101), ("second-job", 102)])
        self.assertEqual(start_next.call_count, 2)
        start_next.assert_called_with(on_log=pipeline_runner._noop, only_explicitly_queued=True)

    def test_idle_queue_recovery_ignores_fresh_imports(self):
        imported = {
            "job_id": "fresh-import",
            "stage": "queued",
            "input": "saved input",
            "worker_alive": False,
        }
        explicitly_queued = {
            **imported,
            "job_id": "requested-job",
            "queued_at": "2026-08-05 12:00:00",
        }
        with (
            patch.object(pipeline_runner, "count_running_workers", return_value=0),
            patch.object(pipeline_runner, "list_jobs", return_value=[imported, explicitly_queued]),
            patch.object(pipeline_runner, "load_status", side_effect=[imported, explicitly_queued]),
            patch.object(
                pipeline_runner, "start_worker", return_value=("requested-job", 1234)
            ) as start,
        ):
            result = pipeline_runner.start_next_queued_job(only_explicitly_queued=True)

        self.assertEqual(result, ("requested-job", 1234))
        start.assert_called_once()


class MarketingCandidateRegressionTests(unittest.TestCase):
    def test_fallback_generation_warning_requires_human_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "marketing_candidates.json").write_text(
                json.dumps({
                    "titles": ["a" * 40, "b" * 40, "c" * 40],
                    "validation_warning": "LLM did not return a JSON object",
                    "attention_required": True,
                }),
                encoding="utf-8",
            )
            error = pipeline_runner._marketing_attention_error({}, job_dir)

        self.assertIn("JSON object", error)

    def test_validated_local_fallback_diagnostic_does_not_block_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "marketing_candidates.json").write_text(
                json.dumps({
                    "titles": ["a" * 40, "b" * 40, "c" * 40],
                    "synopses": ["あ" * 79 + "。"],
                    "generation_warning": "LLM did not return a JSON object",
                    "fallback_used": True,
                    "validation_warning": "",
                    "attention_required": False,
                }),
                encoding="utf-8",
            )

            error = pipeline_runner._marketing_attention_error({}, job_dir)

        self.assertEqual(error, "")

    def test_youtube_column_exposes_attention_and_preserves_planned_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "marketing_candidates.json").write_text(
                json.dumps({"validation_warning": "The read operation timed out"}),
                encoding="utf-8",
            )
            with patch("app.gui.pr.job_dir_for", return_value=job_dir):
                text = PipelineGUI._youtube_queue_status(
                    SimpleNamespace(),
                    "job-1",
                    {"publish_scheduled_at": "2026-08-14T18:00"},
                )

        self.assertIn("需人工干预", text)
        self.assertIn("2026-08-14 18:00", text)

    def test_three_kingdoms_fallback_tags_never_use_isekai_romance_defaults(self):
        novel = SimpleNamespace(
            title="三国群英志第19期",
            full_text="曹操と呂布が兗州で対峙し、陳宮が計略を巡らせる。",
        )
        bundle = pipeline_runner._fallback_marketing_candidates(novel, novel.full_text, 70)
        self.assertIn("#三国志", bundle["tags"])
        self.assertNotIn("#異世界", bundle["tags"])
        self.assertNotIn("#恋愛", bundle["tags"])

    def test_local_fallback_never_cuts_synopsis_mid_sentence(self):
        novel = SimpleNamespace(
            title="魔王の召喚獣になりました",
            full_text=(
                "私はごく普通の学生だった。"
                "友達と駅前にオープンしたばかりの店へ行き、そこで見つけた不思議な品を手に取った瞬間、"
                "見慣れた景色が消えて知らない世界へ運ばれ、目の前に現れた魔王から思いがけない契約を求められることになった。"
                "元の世界へ戻る方法を探すうち、隠されていた真実が明らかになる。"
            ),
        )

        bundle = pipeline_runner._fallback_marketing_candidates(novel, novel.full_text, 70)

        self.assertEqual(pipeline_runner._marketing_validation_error(bundle, 40, 70), "")
        self.assertLessEqual(len(bundle["synopses"][0]), 160)
        self.assertIn(bundle["synopses"][0][-1], "。！？!?」』…")

    def test_local_fallback_handles_long_text_without_punctuation(self):
        novel = SimpleNamespace(title="長い物語", full_text="あ" * 500)

        bundle = pipeline_runner._fallback_marketing_candidates(novel, novel.full_text, 70)

        self.assertEqual(pipeline_runner._marketing_validation_error(bundle, 40, 70), "")
        self.assertEqual(len(set(bundle["titles"])), 3)

    def test_local_fallback_removes_chapter_heading_and_dialogue_wrappers(self):
        novel = SimpleNamespace(
            title="鳥籠王子",
            full_text=(
                "第1話 「ここから逃げられると思っているのか」と王子は静かに問いかけ、閉ざされた扉の前で彼女の返事を待った。"
                "彼女は恐れながらも真実を確かめるため、自分の意志で宮殿の奥へ進むことを選んだ。"
                "二人の過去が重なったとき、長く隠されていた約束の意味が明らかになる。"
            ),
        )

        bundle = pipeline_runner._fallback_marketing_candidates(novel, novel.full_text, 70)

        self.assertEqual(pipeline_runner._marketing_validation_error(bundle, 40, 70), "")
        self.assertFalse(bundle["titles"][0].startswith("第1話"))
        self.assertFalse(bundle["synopses"][0].startswith("第1話"))

    def test_upload_repairs_legacy_three_kingdoms_wrong_tags(self):
        tags = pipeline_runner._safe_generated_tags_for_upload(
            ["#小説", "#異世界", "#恋愛", "#ざまぁ", "#貴族令嬢"],
            "三国志完全解説第19席", "曹操と呂布の戦い",
        )
        self.assertIn("#三国志", tags)
        self.assertNotIn("#異世界", tags)
        self.assertNotIn("#恋愛", tags)

    def test_language_name_tags_are_filtered_from_every_profile_result(self):
        tags = pipeline_runner._candidate_tags([
            "#異世界", "#日本語", "#日语", "#Japanese", "#Japanese-Language", "#物語",
        ])
        self.assertEqual(tags, ["#異世界", "#物語"])

    def test_generic_fallback_never_adds_a_language_name_tag(self):
        novel = SimpleNamespace(title="魔法学院の秘密", full_text="学院で不思議な事件が起き、主人公が真相を追う。")
        bundle = pipeline_runner._fallback_marketing_candidates(novel, novel.full_text, 70)
        self.assertNotIn("#日本語", bundle["tags"])
        self.assertIn("#創作", bundle["tags"])

    def test_structured_candidates_preserve_ad_punctuation(self):
        payload = {
            "titles": [
                "愛さないと言った旦那様、私が姿を消した途端に今さら必死で探し始めました……",
                "妹を選んだ侯爵に捨てられた妻、真実が判明したら溺愛されてももう戻りません（笑）",
                "【ざまぁ】悪女扱いされた私が屋敷を去った翌日、偽りを信じた夫の人生が狂い始める",
            ],
            "synopses": [
                "妹を愛していると夫から突き放された妻。悪女の噂を信じる侯爵に見切りをつけ、真実を知る侍女と屋敷を去るが、彼女の不在をきっかけに隠されていた過去の事実が静かに動き始める……",
                "聖女と呼ばれる妹ばかりを信じ、妻を拒絶した侯爵。しかし地味な令嬢と忠実な侍女が姿を消した後、治癒をめぐる過去と社交界に広がった噂に思わぬ大きな綻びが生まれていく――",
            ],
            "tags": [
                "#恋愛", "#ざまぁ", "#婚約", "#令嬢", "#後悔",
                "#聖女", "#秘密", "#逆転", "#女性向け", "#ノベル",
            ],
        }
        bundle = pipeline_runner._parse_marketing_candidates(payload)
        self.assertIn("……", bundle["titles"][0])
        self.assertIn("（笑）", bundle["titles"][1])
        self.assertIn("【ざまぁ】", bundle["titles"][2])
        self.assertEqual(len(bundle["tags"]), 10)
        self.assertNotIn("【朗読・小説】", bundle["tag_line"])
        self.assertEqual(pipeline_runner._marketing_validation_error(bundle, 35, 70), "")

    def test_internal_source_labels_can_never_become_title_candidates(self):
        bundle = pipeline_runner._parse_marketing_candidates({
            "titles": [
                "标题：三国群英志30-35 简介：local text input [开头] 第30話。",
                "董卓は死んだ後も王允の政変は終わらず、呂布を巡る戦局が再び大きく動き始める",
                "曹操が虎牢関で敗走する一方、孫堅は井戸から伝国の玉璽を見つけてしまう",
            ],
            "synopses": ["a" * 80, "b" * 80],
            "tags": [f"#tag{i}" for i in range(10)],
        })
        self.assertEqual(len(bundle["titles"]), 2)
        self.assertFalse(pipeline_runner._metadata_has_valid_marketing_titles({
            "titles": [
                "标题：三国群英志30-35 简介：local text input [开头] 第30話。",
                "董卓は死んだ後も王允の政変は終わらず、呂布を巡る戦局が再び大きく動き始める",
                "曹操が虎牢関で敗走する一方、孫堅は井戸から伝国の玉璽を見つけてしまう",
            ]
        }))

    def test_upload_template_gets_generated_tags_only_when_they_fit(self):
        context = {
            "candidate_title": "曹操が七宝刀を手に董卓へ迫るも暗殺に失敗し、陳宮と逃亡を始める",
            "short_title": "曹操が七宝刀を手に董卓へ迫るも暗殺に失敗し、陳宮と逃亡を始める",
            "tags": "",
        }
        rendered = pipeline_runner._format_template("{candidate_title}{tags}", context)
        upload_title = pipeline_runner._append_generated_tags_to_upload_title(
            rendered,
            ["#三国志", "#歴史物語", "【朗読・小説】", "#朗読・小説", "#赤陽の勧めるノベル"],
            100,
        )
        self.assertNotIn("【朗読・小説】", upload_title)
        self.assertNotIn("赤陽の勧めるノベル", upload_title)
        self.assertIn("#三国志", upload_title)
        self.assertIn("#歴史物語", upload_title)
        self.assertLessEqual(len(upload_title), 100)

    def test_retired_channel_tag_is_removed_from_template_upload_text(self):
        self.assertEqual(
            pipeline_runner._remove_disallowed_upload_tag("説明 #赤陽の勧めるノベル #三国志"),
            "説明 #三国志",
        )

    def test_language_name_tags_are_removed_from_legacy_upload_text(self):
        self.assertEqual(
            pipeline_runner._remove_disallowed_upload_tag(
                "説明 #日本語 #日语 #Japanese #Japanese-Language #異世界"
            ),
            "説明 #異世界",
        )

    def test_cover_prompt_is_not_clipped_at_old_1400_character_limit(self):
        prompt = pipeline_runner._normalize_cover_prompt("event and typography " * 100)
        prompt = pipeline_runner._policy_safe_image_prompt(prompt, allow_title_text=True)
        self.assertGreater(len(prompt), 1400)
        self.assertLessEqual(len(prompt), 6000)
        self.assertNotIn("1280x720", prompt)
        self.assertNotIn("3:2", prompt)


    def test_only_policy_errors_request_a_new_prompt(self):
        self.assertEqual(
            pipeline_runner._cover_error_kind("HTTP 400: content policy violation: prompt blocked"),
            "policy",
        )
        self.assertEqual(pipeline_runner._cover_error_kind("HTTP 503: service unavailable"), "transient")
        self.assertEqual(pipeline_runner._cover_error_kind("unknown model"), "other")

    def test_incomplete_cover_planner_output_is_rejected_before_image_generation(self):
        short_prompt = (
            "Premium Three Kingdoms key visual. Two commanders face each other in a dusty city. "
            "Use dramatic lighting and a wide composition."
        )
        error = pipeline_runner._cover_planner_quality_error(short_prompt)
        self.assertIn("too short", error)
        self.assertIn("no exact Japanese poster copy", error)
        self.assertIn("missing text layer: main title", error)

    def test_direct_cover_prompt_requires_four_text_layers_and_clean_art(self):
        prompt = (
            "One finished horizontal manga advertisement. The heroine hands a signed document to her former fiance, "
            "who recoils in shock beside the engagement ring. Clean elegant anime rendering, smooth color fields, "
            "soft controlled light, moderate contrast. Main title exact text:『婚約は終わりです』. "
            "Highlight exact text:『完全決着』. Subtitle exact text:『彼が真実を知った日』. "
            "Corner badge exact text:『もう戻らない』. Give every line a position, outline and size hierarchy."
        )
        self.assertEqual(pipeline_runner._cover_planner_quality_error(prompt), "")
        self.assertIn(
            "unsafe anatomical focal point",
            pipeline_runner._cover_planner_quality_error(prompt + " A severed monstrous hand fills the foreground."),
        )
        self.assertIn(
            "noisy micro-detail direction",
            pipeline_runner._cover_planner_quality_error(prompt + " Countless glowing particles scatter across the image."),
        )

    def test_fixed_render_rules_are_added_before_cover_planner_validation(self):
        planner_output = (
            "One finished horizontal manga advertisement. The heroine holds a glowing saber toward a restrained enemy, "
            "who reacts with a sorrowful human expression. Clean elegant anime rendering with soft blue and silver light. "
            "Main title exact text:『獣化兵の禁忌』. Highlight exact text:『悲しき真実』. "
            "Subtitle exact text:『この怪物は人間だった』. Corner badge exact text:『異世界戦記』. "
            "Give every line a position, outline and size hierarchy."
        )
        self.assertIn(
            "no clean moderate-contrast art direction",
            pipeline_runner._cover_planner_quality_error(planner_output),
        )
        completed = pipeline_runner._complete_cover_render_rules(planner_output)
        self.assertEqual(pipeline_runner._cover_planner_quality_error(completed), "")

    def test_cover_package_uses_one_direct_planner_call_and_saved_method(self):
        output = (
            "One finished horizontal manga advertisement. Center, the heroine hands a sealed letter to the prince; "
            "Right, he recoils in visible shock while holding the broken engagement ring. Clean elegant anime rendering, "
            "smooth color fields, soft controlled lighting, moderate contrast, simple background. Main title exact text: "
            "『婚約は終わりです』 at bottom left in large white Mincho with black outline. Highlight exact text: 『完全決着』 "
            "in oversized crimson lettering. Subtitle exact text: 『真実を知った彼はもう遅い』 in a small dark panel. "
            "Side copy exact text: 『私は前へ進む』 along the right edge. Keep text clear of faces and the letter."
        )

        class FakeLLM:
            def __init__(self, **kwargs):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return output

        fake_config = SimpleNamespace(
            llm_image_style_suffix="high contrast, detailed costumes and weapons",
            get=lambda key, default=None: {
                "cover_custom_prompt": "high contrast, golden dust particles",
                "cover_ai_analysis_prompt": "Return one direct prompt only.",
                "cover_poster_method_prompt": "SAVED COMPACT METHOD",
                "cover_prompt_max_tokens": 1600,
            }.get(key, default),
        )
        instances = []

        def make_llm(**kwargs):
            instance = FakeLLM(**kwargs)
            instances.append(instance)
            return instance

        metadata = {
            "titles": ["婚約者へ最後の書類を渡した日"],
            "synopses": ["令嬢は婚約解消書を差し出し、王子は指輪を握ったまま言葉を失う。"],
        }
        with (
            patch.object(pipeline_runner, "config", fake_config),
            patch.object(pipeline_runner, "_can_call_text_llm", return_value=True),
            patch.object(pipeline_runner, "_llm_route_settings", return_value={
                "provider": "openai", "base_url": "https://example.invalid/v1", "api_key": "test", "model": "test-model",
            }),
            patch.object(pipeline_runner, "LLMBackend", side_effect=make_llm),
            patch.object(pipeline_runner, "external_api_slot", side_effect=lambda **kwargs: nullcontext()),
        ):
            self.assertEqual(pipeline_runner._full_cover_poster_method_prompt(), "SAVED COMPACT METHOD")
            prompt, plan, attempts = pipeline_runner._build_cover_package(
                SimpleNamespace(), [], metadata=metadata
            )

        self.assertEqual(instances[0].calls, 1)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(plan["mode"], "single_call_direct_complete_prompt")
        self.assertIn("Side copy exact text", prompt)
        self.assertNotIn("golden dust particles", prompt)
        self.assertNotIn("detailed costumes and weapons", prompt)

    def test_source_wrapper_text_is_not_accepted_as_a_marketing_title(self):
        bundle = {
            "titles": [
                "标题：三国群英志20-24 简介：local text input [开头] 第20話の運命が動き出す瞬間です",
                "関羽が曹操に刃を向けた日、義を選ぶか野望を選ぶか天下を分ける決断が始まった",
                "張遼の一言が太師府の兵を止めたとき、怪物・呂布との圧倒的な武力差が明らかになる",
            ],
            "synopses": ["あ" * 90, "い" * 90],
            "tags": [f"#タグ{i}" for i in range(10)],
        }
        error = pipeline_runner._marketing_validation_error(bundle, 40, 70)
        self.assertIn("source-wrapper text", error)


class CoverCanvasRegressionTests(unittest.TestCase):
    def test_provider_source_is_preserved_before_cover_adaptation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "provider.png"
            backend = ImageBackend(provider="openai", model="gpt-image-1", preserve_source=True)
            provider_image = Image.new("RGB", (1536, 1024), (20, 30, 40))
            with patch.object(backend, "_post_openai_image", return_value=provider_image):
                backend.generate("cover", "", output, width=1280, height=720)
            with Image.open(output) as saved:
                self.assertEqual(saved.size, (1536, 1024))

    def test_provider_cover_is_normalized_to_exact_16_9_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            adapted = Path(tmp) / "adapted.png"
            image = Image.new("RGB", (1536, 1024), (0, 220, 0))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 1535, 79), fill=(255, 0, 0))
            draw.rectangle((0, 944, 1535, 1023), fill=(0, 0, 255))
            image.save(source)

            pipeline_runner._fit_provider_cover_to_16_9(source, adapted, 1280, 720)

            with Image.open(adapted).convert("RGB") as result:
                self.assertEqual(result.size, (1280, 720))
                top = result.getpixel((640, 8))
                bottom = result.getpixel((640, 711))
                left = result.getpixel((8, 360))
                right = result.getpixel((1271, 360))
            for pixel in (top, bottom, left, right):
                self.assertGreater(pixel[1], 170)
                self.assertLess(pixel[0], 70)
                self.assertLess(pixel[2], 70)


class FullRetryRegressionTests(unittest.TestCase):
    def test_full_retry_clears_generated_files_but_preserves_user_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            job = jobs / "sample"
            source = root / "source" / "novel.txt"
            source.parent.mkdir(parents=True)
            source.write_text("正しい原文", encoding="utf-8")
            (job / "images").mkdir(parents=True)
            (job / "audio").mkdir()
            (job / "images" / "old.png").write_bytes(b"old")
            (job / "audio" / pipeline_runner.IMPORTED_AUDIO_FILENAME).write_bytes(b"mp3")
            (job / "audio" / "seg_00000.mp3").write_bytes(b"generated")
            (job / pipeline_runner.IMPORTED_AUDIO_MANIFEST).write_text(
                json.dumps({"path": f"audio/{pipeline_runner.IMPORTED_AUDIO_FILENAME}"}), encoding="utf-8"
            )
            (job / pipeline_runner.TTS_PRONUNCIATION_DICTIONARY).write_text("吕布=りょふ", encoding="utf-8")
            (job / "settings_snapshot.json").write_text("{}", encoding="utf-8")
            (job / "prompts.json").write_text("[]", encoding="utf-8")
            (job / "marketing_candidates.json").write_text("{}", encoding="utf-8")
            (job / "タイトル・あらすじ候補.txt").write_text("新候補", encoding="utf-8")
            (job / "タイトル・あらすじ・タグ候補.txt").write_text("候補", encoding="utf-8")
            (job / "upload_title_selection.json").write_text("{}", encoding="utf-8")
            (job / "status.json").write_text(
                json.dumps({
                    "job_id": "sample",
                    "input": str(source),
                    "source_path": str(source),
                    "source_kind": "local_text",
                }),
                encoding="utf-8",
            )

            with patch.object(pipeline_runner, "JOBS_DIR", jobs):
                pipeline_runner.reset_full_job("sample")

            self.assertFalse((job / "images").exists())
            self.assertFalse((job / "prompts.json").exists())
            self.assertFalse((job / "settings_snapshot.json").exists())
            self.assertFalse((job / "marketing_candidates.json").exists())
            self.assertFalse((job / "タイトル・あらすじ候補.txt").exists())
            self.assertFalse((job / "タイトル・あらすじ・タグ候補.txt").exists())
            self.assertFalse((job / "upload_title_selection.json").exists())
            self.assertFalse((job / "audio" / "seg_00000.mp3").exists())
            self.assertTrue((job / "audio" / pipeline_runner.IMPORTED_AUDIO_FILENAME).exists())
            self.assertTrue((job / pipeline_runner.IMPORTED_AUDIO_MANIFEST).exists())
            self.assertTrue((job / pipeline_runner.TTS_PRONUNCIATION_DICTIONARY).exists())
            status = json.loads((job / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["input"], str(source.resolve()))
            self.assertEqual(status["stage"], "queued")


class ManualCoverRegenerationTests(unittest.TestCase):
    def test_regenerates_only_cover_and_restores_completed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp)
            job = jobs / "sample"
            (job / "cover").mkdir(parents=True)
            (job / "cover" / "cover.jpg").write_bytes(b"old-cover")
            (job / "audio").mkdir()
            (job / "audio" / "seg_00000.mp3").write_bytes(b"audio-kept")
            (job / "images").mkdir()
            (job / "images" / "img_00000.png").write_bytes(b"image-kept")
            (job / "final.mp4").write_bytes(b"video-kept")
            (job / "novel.json").write_text(
                json.dumps({
                    "site": "text",
                    "id": "sample",
                    "title": "Title",
                    "chapters": [{"index": 1, "title": "", "text": "Story text"}],
                }),
                encoding="utf-8",
            )
            (job / "segments.json").write_text(
                json.dumps([{"i": 0, "text": "Story text"}]), encoding="utf-8"
            )
            (job / "metadata.json").write_text("{}", encoding="utf-8")
            (job / "status.json").write_text(
                json.dumps({"job_id": "sample", "stage": "completed", "progress": 1.0}), encoding="utf-8"
            )

            def fake_stage_cover(_novel, _segments, job_dir, **kwargs):
                self.assertTrue(kwargs["force"])
                self.assertEqual(len(kwargs["metadata"]["titles"]), 3)
                self.assertEqual(len(kwargs["metadata"]["synopses"]), 1)
                cover = job_dir / "cover" / "cover.jpg"
                cover.parent.mkdir(parents=True)
                cover.write_bytes(b"new-cover")
                return cover

            generated_metadata = {
                "titles": [
                    "婚約解消書を差し出した令嬢に王子が言葉を失い、取り返せない真実を初めて知る運命の日",
                    "王宮の祝宴で令嬢が別れを告げた瞬間、傲慢な婚約者の運命と立場が完全に逆転し始める",
                    "すべてを奪われた令嬢が最後の証拠を公開し、嘘を重ねた王子が大勢の貴族の前で崩れ落ちる",
                ],
                "synopses": [
                    "長年耐えてきた令嬢は王宮の祝宴で婚約解消書と隠されていた証拠を差し出す。余裕を見せていた王子は真実を知って言葉を失い、周囲の貴族たちも二人の関係が完全に逆転したことを悟る。"
                ],
                "generated_tags": [f"#タグ{i}" for i in range(10)],
            }

            with (
                patch.object(pipeline_runner, "JOBS_DIR", jobs),
                patch.object(pipeline_runner, "is_worker_running", return_value=False),
                patch.object(pipeline_runner, "stage_metadata", return_value=generated_metadata) as metadata_stage,
                patch.object(pipeline_runner, "stage_cover", side_effect=fake_stage_cover),
            ):
                cover = pipeline_runner.regenerate_job_cover("sample")

            metadata_stage.assert_called_once()
            self.assertEqual(cover.read_bytes(), b"new-cover")
            self.assertEqual((job / "audio" / "seg_00000.mp3").read_bytes(), b"audio-kept")
            self.assertEqual((job / "images" / "img_00000.png").read_bytes(), b"image-kept")
            self.assertEqual((job / "final.mp4").read_bytes(), b"video-kept")
            status = json.loads((job / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["stage"], "completed")
            self.assertEqual(status["progress"], 1.0)
            self.assertEqual(status["cover"], str(cover))


class BrowserUploadProfileRegressionTests(unittest.TestCase):
    def test_single_channel_upload_forces_selected_chrome_profile_launch(self):
        profile = {
            "name": "三国 千夜一席",
            "enabled": True,
            "chrome_profile": "Account-2",
            "flow": "simple",
            "visibility": "PRIVATE",
        }
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            job_dir.mkdir()
            video = job_dir / "video.mp4"
            video.write_bytes(b"video")
            lock_path = job_dir / ".upload.lock"
            with (
                patch.object(pipeline_runner, "_selected_upload_profiles", return_value=[profile]),
                patch.object(pipeline_runner, "_ensure_upload_dependencies"),
                patch.object(pipeline_runner, "_acquire_upload_lock", return_value=lock_path),
                patch.object(pipeline_runner, "_release_upload_lock"),
                patch("app.upload.upload_to_youtube", return_value="video-id") as upload_mock,
            ):
                pipeline_runner.stage_upload(
                    video,
                    "测试标题",
                    None,
                    job_dir,
                    force=True,
                    schedule_enabled_override=False,
                )

        self.assertEqual(upload_mock.call_args.kwargs["chrome_profile"], "Account-2")
        self.assertTrue(upload_mock.call_args.kwargs["force_profile_launch"])


class ShareableProfileRegressionTests(unittest.TestCase):
    def test_builtin_japanese_profile_is_sanitized_and_preserves_live_connections(self):
        name = config_module.DEFAULT_JAPANESE_PROFILE_NAME
        data = config_module.builtin_profile_settings(name)
        self.assertIsNotNone(data)
        self.assertFalse(set(data) & config_module.PROFILE_CONNECTION_FIELDS)
        self.assertFalse(any(str(key).lower().endswith("api_key") for key in data))
        self.assertEqual(data["active_profile"], name)
        self.assertEqual(data["browser_chrome_profile"], "Default")
        self.assertNotIn("kinkokyo2381", data["browser_profiles"])
        self.assertFalse(data["upload_enabled"])

        isolated = config_module.Config()
        isolated.set("ai_api_base_url", "https://example.invalid/v1")
        isolated.set("ai_api_key", "test-key")
        isolated.set("image_base_url", "https://images.example.invalid/v1")
        isolated.load_profile(name)
        self.assertEqual(isolated.get("ai_api_base_url"), "https://example.invalid/v1")
        self.assertEqual(isolated.get("ai_api_key"), "test-key")
        self.assertEqual(isolated.get("image_base_url"), "https://images.example.invalid/v1")

    def test_fresh_install_selects_japanese_tweet_default(self):
        settings = config_module.fresh_install_settings()
        self.assertEqual(settings["active_profile"], config_module.DEFAULT_JAPANESE_PROFILE_NAME)
        self.assertEqual(settings["tts_voice"], "ja-JP-NanamiNeural")
        self.assertFalse(settings["upload_enabled"])


if __name__ == "__main__":
    unittest.main()
