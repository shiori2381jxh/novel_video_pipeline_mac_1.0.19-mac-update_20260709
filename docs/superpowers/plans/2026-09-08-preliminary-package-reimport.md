# 预备分包移除视频并支持重新导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make preliminary-score packages contain no MP4 files and let the normal file/folder importer create a fresh image-regeneration job from a valid package's retained TXT and full narration MP3.

**Architecture:** `pipeline_runner` owns the package manifest, safe validation, and destructive staging. `gui` discovers those manifests before normal TXT/MP3 matching, then invokes the existing queued-job creation and imported-audio attachment path so the existing pipeline skips TTS but creates new image and composition artifacts.

**Tech Stack:** Python 3.12, Tkinter, `pathlib`, `pytest`, existing pipeline runner and GUI import flow.

## Global Constraints

- Do not retain any `.mp4` file, case-insensitively, in a preliminary package.
- Preserve `_source_input`, root `audio_full.mp3`, `cover`, `images`, and all non-MP4 Short files.
- Manifest paths are package-relative and must resolve within the package root.
- Reimport must create a new imported-audio task only; do not reuse prior images, covers, Shorts, status, or settings snapshots.
- A reimported task must call the existing image API path and compose a new main MP4 when run.
- The workspace is not a Git repository; omit commit commands.

---

### Task 1: Package manifest and MP4-safe preliminary staging

**Files:**
- Modify: `app/pipeline_runner.py:97-100,821-892`
- Test: `tests/test_preliminary_packages.py`

**Interfaces:**
- Produces: `PRELIMINARY_PACKAGE_MANIFEST`, `prepare_job_for_preliminary_scoring(job_id: str) -> str`, and `read_preliminary_package(package_dir: str | Path) -> dict`.
- `read_preliminary_package` returns `{"package_dir": Path, "text_path": Path, "audio_path": Path, "title": str}` or raises `ValueError`/`FileNotFoundError` for invalid packages.

- [ ] **Step 1: Write the failing package-content test**

```python
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
    assert not list(package.rglob("*.mp4"))
    assert not list(package.rglob("*.MP4"))
    assert (package / "shorts" / "audio_full.mp3").exists()
    assert (package / "shorts" / "script.txt").read_text(encoding="utf-8") == "Short 文案"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_preliminary_packages.py::test_preliminary_package_excludes_nested_mp4_but_keeps_short_audio_and_text -v`

Expected: FAIL because the existing implementation moves main and Short MP4 files into the package.

- [ ] **Step 3: Implement minimal manifest and staging changes**

```python
PRELIMINARY_PACKAGE_MANIFEST = "preliminary_package.json"
PRELIMINARY_PACKAGE_VERSION = 1

def _move_tree_without_mp4(source: Path, destination: Path) -> None:
    for child in source.rglob("*"):
        if child.is_file() and child.suffix.lower() != ".mp4":
            relative = child.relative_to(source)
            (destination / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(child), str(destination / relative))
```

Use the helper for each retained directory, move only the root audio file, and write a package-relative manifest containing the actual source snapshot TXT and `audio_full.mp3` after all retained assets are staged.

- [ ] **Step 4: Run the package-content test to verify it passes**

Run: `python -m pytest tests/test_preliminary_packages.py::test_preliminary_package_excludes_nested_mp4_but_keeps_short_audio_and_text -v`

Expected: PASS.

- [ ] **Step 5: Write the failing safe-manifest test**

```python
def test_read_preliminary_package_rejects_manifest_path_outside_package(tmp_path):
    package = tmp_path / "预备分_story"
    package.mkdir()
    (package / "preliminary_package.json").write_text(
        json.dumps({"version": 1, "text_path": "../outside.txt", "audio_path": "audio_full.mp3"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="预备分包"):
        pr.read_preliminary_package(package)
```

- [ ] **Step 6: Run the safe-manifest test to verify it fails**

Run: `python -m pytest tests/test_preliminary_packages.py::test_read_preliminary_package_rejects_manifest_path_outside_package -v`

Expected: FAIL because no package reader exists.

- [ ] **Step 7: Implement manifest validation**

```python
def read_preliminary_package(package_dir: str | Path) -> dict:
    root = Path(package_dir).expanduser().resolve()
    data = _read_json(root / PRELIMINARY_PACKAGE_MANIFEST, {})
    if data.get("version") != PRELIMINARY_PACKAGE_VERSION:
        raise ValueError("不是可重新导入的预备分包")
    text_path = _resolve_package_relative_path(root, data.get("text_path"), ".txt")
    audio_path = _resolve_package_relative_path(root, data.get("audio_path"), ".mp3")
    inspect_imported_audio(audio_path)
    return {"package_dir": root, "text_path": text_path, "audio_path": audio_path, "title": str(data.get("title") or text_path.stem)}
```

Validate each relative path is not absolute, is inside `root`, exists as a regular file, and has the expected extension.

- [ ] **Step 8: Run both Task 1 tests**

Run: `python -m pytest tests/test_preliminary_packages.py -v`

Expected: PASS.

### Task 2: Importer recognition and fresh imported-audio task creation

**Files:**
- Modify: `app/gui.py:4232-4260,4475-4550`
- Test: `tests/test_preliminary_packages.py`

**Interfaces:**
- Consumes: `pr.read_preliminary_package(package_dir) -> dict` from Task 1.
- Produces: a GUI helper that imports each selected valid package by calling `_create_queued_job(title, text_path, imported_audio_path=audio_path)` exactly once.

- [ ] **Step 1: Write the failing importer-discovery test**

```python
def test_preliminary_package_folder_is_removed_from_normal_txt_mp3_scan(monkeypatch, tmp_path):
    package = tmp_path / "预备分_story"
    package.mkdir()
    monkeypatch.setattr(gui.pr, "read_preliminary_package", lambda path: {"package_dir": package, "text_path": package / "_source_input" / "story.txt", "audio_path": package / "audio_full.mp3", "title": "story"})

    packages, remaining = gui._split_preliminary_package_imports([package])

    assert packages[0]["title"] == "story"
    assert remaining == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_preliminary_packages.py::test_preliminary_package_folder_is_removed_from_normal_txt_mp3_scan -v`

Expected: FAIL because the package splitting helper does not exist.

- [ ] **Step 3: Implement the focused import helper and wire both folder entry points**

```python
def _split_preliminary_package_imports(paths: list[Path]) -> tuple[list[dict], list[Path]]:
    packages, remaining = [], []
    for path in paths:
        if path.is_dir() and (path / pr.PRELIMINARY_PACKAGE_MANIFEST).is_file():
            packages.append(pr.read_preliminary_package(path))
        else:
            remaining.append(path)
    return packages, remaining
```

In both `_import_files_or_folders` and `_import_folder`, process returned packages first by calling `_create_queued_job` with the manifest text/audio paths. Do not include package contents in normal recursive matching, so their `shorts` audio/text cannot create duplicate tasks. Show a single completion/error report alongside existing imports.

- [ ] **Step 4: Run the importer-discovery test to verify it passes**

Run: `python -m pytest tests/test_preliminary_packages.py::test_preliminary_package_folder_is_removed_from_normal_txt_mp3_scan -v`

Expected: PASS.

- [ ] **Step 5: Write the failing reimport-creation test**

```python
def test_reimported_package_creates_imported_audio_task(monkeypatch, tmp_path):
    package = {"text_path": tmp_path / "story.txt", "audio_path": tmp_path / "audio_full.mp3", "title": "story"}
    calls = []
    app = object.__new__(gui.PipelineGUI)
    monkeypatch.setattr(app, "_create_queued_job", lambda title, text, **kwargs: calls.append((title, text, kwargs)) or "story")

    app._create_jobs_from_preliminary_packages([package])

    assert calls == [("story", str(package["text_path"]), {"imported_audio_path": str(package["audio_path"])})]
```

- [ ] **Step 6: Run the reimport-creation test to verify it fails**

Run: `python -m pytest tests/test_preliminary_packages.py::test_reimported_package_creates_imported_audio_task -v`

Expected: FAIL because the package-task creation method does not exist.

- [ ] **Step 7: Implement the package task-creation method**

```python
def _create_jobs_from_preliminary_packages(self, packages: list[dict]) -> tuple[int, list[str]]:
    created, errors = 0, []
    for package in packages:
        try:
            job_id = self._create_queued_job(
                str(package["title"]), str(package["text_path"]),
                imported_audio_path=str(package["audio_path"]),
            )
            created += int(bool(job_id))
        except Exception as exc:
            errors.append(f"{package['package_dir'].name}: {exc}")
    return created, errors
```

- [ ] **Step 8: Run all preliminary-package tests**

Run: `python -m pytest tests/test_preliminary_packages.py -v`

Expected: PASS.

### Task 3: Operator text and final validation

**Files:**
- Modify: `app/gui.py:6702-6734`
- Modify: `README.md` (preliminary-score package behavior, if documented)
- Test: `tests/test_preliminary_packages.py`

**Interfaces:**
- Consumes: package behavior from Tasks 1–2.
- Produces: confirmation copy that accurately describes no-video retention and reimport behavior.

- [ ] **Step 1: Write the failing confirmation-copy assertion**

```python
def test_preliminary_confirmation_copy_says_mp4_is_not_retained():
    source = Path(gui.__file__).read_text(encoding="utf-8")
    assert "不保留任何 MP4" in source
    assert "重新导入" in source
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_preliminary_packages.py::test_preliminary_confirmation_copy_says_mp4_is_not_retained -v`

Expected: FAIL because current confirmation text says it keeps main and Short MP4.

- [ ] **Step 3: Update GUI and README wording**

```python
message = (
    f"将把 {len(ids)} 个任务整理为预备分包，不保留任何 MP4。\n\n"
    "保留原文、正片 audio_full.mp3、cover、images，以及 shorts 中的音频和文字资料。\n"
    "以后可从“导入文件 / 文件夹”选择该预备分包，调用图片 API 重新生图并合成正片。\n\n"
    "其余文件会永久删除，原任务不能继续运行。"
)
```

- [ ] **Step 4: Run the confirmation-copy test to verify it passes**

Run: `python -m pytest tests/test_preliminary_packages.py::test_preliminary_confirmation_copy_says_mp4_is_not_retained -v`

Expected: PASS.

- [ ] **Step 5: Run focused tests and project safety checks**

Run: `python -m pytest tests/test_preliminary_packages.py -v; python -m py_compile app/gui.py app/pipeline_runner.py; python -m compileall app`

Expected: all tests pass; compilation exits with code 0.
