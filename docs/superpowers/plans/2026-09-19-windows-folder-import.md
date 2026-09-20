# Windows 文件夹导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Windows 的“导入文件 / 文件夹…”入口可明确选择文件夹并递归导入其内容。

**Architecture:** 保留 macOS 的 AppKit 文件/目录混选面板。将 Windows 的选择流程提取为一个可测试的选择器：先让用户选择导入类型，再分别调用 Tk 的 `askopenfilenames` 或 `askdirectory`；已有 `_import_files_or_folders` 继续统一扫描和导入返回的 `Path` 列表。

**Tech Stack:** Python 3、Tkinter、pytest、monkeypatch。

## Global Constraints

- 不更改 macOS 的混选体验。
- Windows 文件夹选择必须使用原生目录选择器。
- 取消任何选择器不得创建任务或显示错误。
- 不改变 TXT/MP3 扫描、去重、配对或创建任务的规则。

---

### Task 1: Windows 导入类型选择器与回归测试

**Files:**
- Modify: `app/gui.py:285-336`
- Modify: `tests/test_preliminary_packages.py`

**Interfaces:**
- Produces: `_choose_import_files_and_folders() -> list[Path]`，在 Windows 中返回文件列表、单个文件夹列表或空列表。
- Consumes: `tkinter.messagebox.askyesnocancel`, `tkinter.filedialog.askopenfilenames`, `tkinter.filedialog.askdirectory`。

- [ ] **Step 1: 写入失败的 Windows 文件夹选择测试**

在 `tests/test_preliminary_packages.py` 加入：

```python
def test_windows_import_chooser_returns_selected_folder(monkeypatch, tmp_path):
    folder = tmp_path / "novel"
    folder.mkdir()
    calls = []
    monkeypatch.setattr(gui.sys, "platform", "win32")
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        gui.filedialog,
        "askdirectory",
        lambda **_kwargs: calls.append("folder") or str(folder),
    )
    monkeypatch.setattr(
        gui.filedialog,
        "askopenfilenames",
        lambda **_kwargs: calls.append("files") or (),
    )

    assert gui._choose_import_files_and_folders() == [folder]
    assert calls == ["folder"]
```

- [ ] **Step 2: 运行测试，确认当前实现失败**

Run: `python -m pytest tests/test_preliminary_packages.py::test_windows_import_chooser_returns_selected_folder -v`

Expected: FAIL；当前实现直接调用 `askopenfilenames`，断言会显示 `calls == ['files']`。

- [ ] **Step 3: 以最小改动实现 Windows 分支**

在 `app/gui.py` 的 `_choose_import_files_and_folders` 中，在 macOS 分支之后添加 Windows 分支：

```python
if sys.platform == "win32":
    choice = messagebox.askyesnocancel(
        "导入内容",
        "要导入文件夹吗？\n\n选择“是”：选择文件夹并递归导入。\n选择“否”：选择 TXT/MP3 文件。\n选择“取消”：不导入。",
        icon=messagebox.QUESTION,
    )
    if choice is None:
        return []
    if choice:
        selected = filedialog.askdirectory(title="选择包含小说 TXT 的文件夹")
        return [Path(selected).expanduser()] if selected else []
```

保留随后既有的 `askopenfilenames` 代码作为“否”时的文件导入分支。

- [ ] **Step 4: 运行针对性测试，确认通过**

Run: `python -m pytest tests/test_preliminary_packages.py::test_windows_import_chooser_returns_selected_folder -v`

Expected: PASS。

- [ ] **Step 5: 增加文件选项的行为测试**

在同一测试文件加入：

```python
def test_windows_import_chooser_returns_selected_files(monkeypatch, tmp_path):
    text_path = tmp_path / "story.txt"
    text_path.write_text("正文", encoding="utf-8")
    monkeypatch.setattr(gui.sys, "platform", "win32")
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(gui.filedialog, "askopenfilenames", lambda **_kwargs: (str(text_path),))

    assert gui._choose_import_files_and_folders() == [text_path]
```

- [ ] **Step 6: 运行文件选项测试，确认它在实现后通过**

Run: `python -m pytest tests/test_preliminary_packages.py::test_windows_import_chooser_returns_selected_files -v`

Expected: PASS；此测试保护原有 Windows 文件导入回退行为。

- [ ] **Step 7: 运行导入测试文件并提交实现**

Run: `python -m pytest tests/test_preliminary_packages.py -v`

Expected: PASS。

```bash
git add app/gui.py tests/test_preliminary_packages.py
git commit -m "fix: enable Windows folder import"
```

### Task 2: 验证应用可编译且核心导入入口仍可加载

**Files:**
- Verify: `app/gui.py`

**Interfaces:**
- Consumes: 已完成的 `_choose_import_files_and_folders() -> list[Path]`。
- Produces: 可启动且语法正确的 GUI 模块。

- [ ] **Step 1: 编译 GUI 模块**

Run: `python -m py_compile app/gui.py`

Expected: PASS，且无输出。

- [ ] **Step 2: 执行项目安全验证中的导入检查**

Run:

```bash
python -c "from app import gui; print(gui._choose_import_files_and_folders.__name__)"
```

Expected: 输出 `_choose_import_files_and_folders`。

- [ ] **Step 3: 检查提交范围**

Run: `git status --short`

Expected: 本次实现仅影响 `app/gui.py` 和 `tests/test_preliminary_packages.py`；不暂存或覆盖原有用户改动。
