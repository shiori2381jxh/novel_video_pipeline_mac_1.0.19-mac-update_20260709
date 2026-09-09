from pathlib import Path


def test_operator_docs_describe_task_local_rewrite_localization():
    root = Path(__file__).parents[1]
    guide = (root / "docs" / "module_prompt_editing_guide.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    for text in (guide, readme):
        assert "专名本地化" in text
        assert "text_rewrite_replacements.json" in text
        assert "任务内" in text
