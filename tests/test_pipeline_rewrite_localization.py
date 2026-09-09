import json

import pytest

from app import pipeline_runner
from app.config import config


class FakeLLM:
    replies: list[str] = []
    requests: list[str] = []

    def __init__(self, **_kwargs):
        pass

    def storyboard(self, request: str) -> str:
        type(self).requests.append(request)
        return type(self).replies.pop(0)


@pytest.fixture
def configured_rewrite(monkeypatch):
    values = dict(config._data)
    values.update(
        {
            "ai_rewrite_enabled": True,
            "ai_rewrite_proper_noun_localization_enabled": True,
            "ai_rewrite_batch_chars": 800,
            "ai_rewrite_min_length_ratio": 0.01,
            "ai_rewrite_max_length_ratio": 10.0,
            "ai_rewrite_prompt": "保留事件，只改写表达。",
            "ai_api_enabled": False,
            "llm_provider": "openai",
            "llm_base_url": "https://example.invalid/v1",
            "llm_api_key": "test-key",
            "llm_model": "test-model",
        }
    )
    monkeypatch.setattr(config, "_data", values)
    FakeLLM.replies = []
    FakeLLM.requests = []
    monkeypatch.setattr(pipeline_runner, "LLMBackend", FakeLLM)
    return FakeLLM


def _reply(text: str, replacements: list[dict]) -> str:
    return json.dumps(
        {
            "rewritten_text": text,
            "new_replacements": replacements,
            "warnings": [],
        },
        ensure_ascii=False,
    )


def test_structured_rewrite_passes_prior_mapping_to_next_batch(
    configured_rewrite, tmp_path
):
    first_source = "旧名进入房间。" * 60
    second_source = "旧名离开房间。" * 60
    configured_rewrite.replies = [
        _reply(
            first_source,
            [{"category": "人名", "source": "旧名", "target": "陈舟", "notes": ""}],
        ),
        _reply(second_source, []),
    ]

    result = pipeline_runner._rewrite_story_text(
        f"{first_source}\n\n{second_source}", job_dir=tmp_path
    )

    assert result == f"{first_source.replace('旧名', '陈舟')}\n\n{second_source.replace('旧名', '陈舟')}"
    assert "陈舟" in configured_rewrite.requests[1]
    replacement_report = json.loads(
        (tmp_path / "text_rewrite_replacements.json").read_text(encoding="utf-8")
    )
    assert replacement_report["replacements"][0]["source"] == "旧名"
    assert replacement_report["replacements"][0]["target"] == "陈舟"
    assert not (tmp_path / "text_rewrite_checkpoint.json").exists()


def test_invalid_structured_reply_retries_then_falls_back_without_final_artifacts(
    configured_rewrite, tmp_path
):
    configured_rewrite.replies = ["not json", "still not json"]
    source = "田中は駅へ向かった。彼は雨を見た。"

    assert pipeline_runner._rewrite_story_text(source, job_dir=tmp_path) == source
    assert len(configured_rewrite.requests) == 2
    assert not (tmp_path / "text_rewritten.txt").exists()
    assert not (tmp_path / "text_rewrite_replacements.json").exists()
    assert not (tmp_path / "text_rewrite_checkpoint.json").exists()


def test_structured_rewrite_retry_includes_the_validator_failure(
    configured_rewrite, tmp_path
):
    source = "林一走进旧城区。" * 120
    configured_rewrite.replies = [
        _reply(
            source,
            [{"category": "场景", "source": "旧城区", "target": "临川区", "notes": ""}],
        ),
        _reply(source, []),
    ]

    assert pipeline_runner._rewrite_story_text(source, job_dir=tmp_path) == source
    assert "上一轮失败原因：专名映射类别无效：场景" in configured_rewrite.requests[1]


def test_near_name_retry_failure_uses_local_fallback_and_records_it(
    configured_rewrite, tmp_path
):
    source = "林一走进房间。" * 120
    invalid_name = _reply(
        source,
        [{"category": "人名", "source": "林一", "target": "林二", "notes": ""}],
    )
    configured_rewrite.replies = [invalid_name, invalid_name]

    result = pipeline_runner._rewrite_story_text(source, job_dir=tmp_path)

    report = json.loads(
        (tmp_path / "text_rewrite_replacements.json").read_text(encoding="utf-8")
    )
    mapping = report["replacements"][0]
    assert mapping["source"] == "林一"
    assert mapping["target"] != "林一"
    assert mapping["target"] in result
    assert "自动兜底" in mapping["notes"]


def test_near_name_then_empty_mapping_still_uses_local_fallback(
    configured_rewrite, tmp_path
):
    source = "林一走进房间。" * 120
    invalid_name = _reply(
        source,
        [{"category": "人名", "source": "林一", "target": "林二", "notes": ""}],
    )
    configured_rewrite.replies = [invalid_name, _reply(source, [])]

    result = pipeline_runner._rewrite_story_text(source, job_dir=tmp_path)

    report = json.loads(
        (tmp_path / "text_rewrite_replacements.json").read_text(encoding="utf-8")
    )
    assert report["replacements"][0]["source"] == "林一"
    assert report["replacements"][0]["target"] in result


def test_plain_rewrite_keeps_legacy_non_json_protocol(monkeypatch, tmp_path):
    values = dict(config._data)
    values.update(
        {
            "ai_rewrite_enabled": True,
            "ai_rewrite_proper_noun_localization_enabled": False,
            "ai_rewrite_batch_chars": 800,
            "ai_api_enabled": False,
            "llm_provider": "openai",
            "llm_base_url": "https://example.invalid/v1",
            "llm_api_key": "test-key",
            "llm_model": "test-model",
        }
    )
    monkeypatch.setattr(config, "_data", values)
    FakeLLM.replies = ["改写后的正文：陈舟走进了房间。"]
    FakeLLM.requests = []
    monkeypatch.setattr(pipeline_runner, "LLMBackend", FakeLLM)

    result = pipeline_runner._rewrite_story_text("旧名走进了房间。", job_dir=tmp_path)

    assert result == "陈舟走进了房间。"
    assert not (tmp_path / "text_rewrite_replacements.json").exists()
    assert not (tmp_path / "text_rewrite_checkpoint.json").exists()


def test_structured_rewrite_recovers_only_the_remaining_batches_from_checkpoint(
    configured_rewrite, tmp_path
):
    first_source = "旧名进入房间。" * 60
    second_source = "旧名离开房间。" * 60
    source = f"{first_source}\n\n{second_source}"
    pipeline_runner._write_json(
        tmp_path / "text_rewrite_checkpoint.json",
        {
            "source_hash": pipeline_runner._text_hash(source),
            "prompt_hash": pipeline_runner._text_hash("保留事件，只改写表达。"),
            "batch_count": 2,
            "rewritten_parts": [first_source],
            "replacements": [
                {
                    "category": "人名",
                    "source": "旧名",
                    "target": "陈舟",
                    "notes": "",
                    "batch": 1,
                    "local_replace_safe": True,
                }
            ],
            "warnings": [],
            "batches": [{"batch": 1, "chars_before": len(first_source), "chars_after": len(first_source)}],
        },
    )
    configured_rewrite.replies = [_reply(second_source, [])]

    result = pipeline_runner._rewrite_story_text(source, job_dir=tmp_path)

    assert result == f"{first_source.replace('旧名', '陈舟')}\n\n{second_source.replace('旧名', '陈舟')}"
    assert len(configured_rewrite.requests) == 1
    assert "陈舟" in configured_rewrite.requests[0]
    assert not (tmp_path / "text_rewrite_checkpoint.json").exists()


def test_structured_rewrite_report_counts_final_text_after_local_replacement(
    configured_rewrite, tmp_path
):
    source = "旧名进入房间。" * 120
    configured_rewrite.replies = [
        _reply(
            source,
            [{"category": "人名", "source": "旧名", "target": "东方晨", "notes": ""}],
        )
    ]

    result = pipeline_runner._rewrite_story_text(source, job_dir=tmp_path)
    report = json.loads((tmp_path / "text_rewrite_report.json").read_text(encoding="utf-8"))

    assert report["chars_after_model"] == len(source)
    assert report["chars_after"] == len(result)
    assert report["chars_after"] > report["chars_after_model"]


def test_reset_from_clean_removes_rewrite_localization_artifacts(monkeypatch, tmp_path):
    image = tmp_path / "images" / "scene.png"
    image.parent.mkdir()
    image.write_bytes(b"image")
    for name in (
        "text_rewrite_replacements.json",
        "text_rewrite_checkpoint.json",
        "text_rewritten.txt",
        "text_rewrite_report.json",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pipeline_runner, "is_worker_running", lambda _job_id: False)
    monkeypatch.setattr(pipeline_runner, "_safe_job_path", lambda _job_id: tmp_path)
    monkeypatch.setattr(pipeline_runner, "load_status", lambda *_args, **_kwargs: {"input": "source.txt"})
    monkeypatch.setattr(pipeline_runner, "_resolve_job_input_source", lambda *_args, **_kwargs: "source.txt")
    monkeypatch.setattr(pipeline_runner, "_valid_scene_images", lambda _job_dir: [image])
    monkeypatch.setattr(pipeline_runner, "write_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_runner, "append_log", lambda *_args, **_kwargs: None)

    pipeline_runner.reset_from_clean_reuse_images("job-1")

    for name in (
        "text_rewrite_replacements.json",
        "text_rewrite_checkpoint.json",
        "text_rewritten.txt",
        "text_rewrite_report.json",
    ):
        assert not (tmp_path / name).exists()
