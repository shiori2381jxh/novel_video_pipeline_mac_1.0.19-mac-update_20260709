# 小说项目页滚动与折叠 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让“小说项目”标签页在小窗口中可独立纵向滚动，并让两个大型设置分组可折叠。

**Architecture:** 在 `app/gui.py` 中增加小型、通用的 ttk 滚动容器和折叠分组构造方法，再把“小说项目”页现有控件挂到新的内容容器中。外层滚动只在指针位于项目页且没有位于项目树时接管滚轮；折叠只改变内容 Frame 的布局状态。

**Tech Stack:** Python 3、Tkinter/ttk、unittest/pytest

## Global Constraints

- 只调整 `app/gui.py` 中“小说项目”标签页的布局和滚轮绑定。
- 不改变书库导入、文件导入、任务分类、右侧配置页及流水线业务逻辑。
- 沿用现有 Tkinter/ttk 控件风格，不引入新依赖。
- 当前工作目录不是 Git 仓库，因此计划中的阶段性提交步骤不可执行；用文件差异和完整验证结果作为交付记录。

---

### Task 1: 可测试的折叠分组与滚轮单位换算

**Files:**
- Modify: `app/gui.py:20-120`
- Create: `tests/test_gui_scroll_collapse.py`

**Interfaces:**
- Produces: `_mousewheel_units(delta: int, platform: str) -> int`
- Produces: `CollapsibleSection(ttk.Frame)`，公开属性 `content`、`expanded` 和方法 `toggle()`。
- `CollapsibleSection` 构造参数：`parent`、`title: str`、`expanded: bool`、`on_layout_changed: Callable[[], None] | None`。

- [ ] **Step 1: 写滚轮换算的失败测试**

```python
from app.gui import _mousewheel_units


def test_mousewheel_units_supports_windows_and_macos_deltas():
    assert _mousewheel_units(120, "win32") == -1
    assert _mousewheel_units(-120, "win32") == 1
    assert _mousewheel_units(1, "darwin") == -1
    assert _mousewheel_units(-1, "darwin") == 1
```

- [ ] **Step 2: 运行测试并确认因符号不存在而失败**

Run: `python -m pytest tests/test_gui_scroll_collapse.py::test_mousewheel_units_supports_windows_and_macos_deltas -v`

Expected: FAIL，提示无法从 `app.gui` 导入 `_mousewheel_units`。

- [ ] **Step 3: 添加最小滚轮换算函数**

```python
def _mousewheel_units(delta: int, platform: str) -> int:
    if not delta:
        return 0
    units = -delta if platform == "darwin" else -int(delta / 120)
    return units or (-1 if delta > 0 else 1)
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m pytest tests/test_gui_scroll_collapse.py::test_mousewheel_units_supports_windows_and_macos_deltas -v`

Expected: PASS。

- [ ] **Step 5: 写折叠分组的失败测试**

```python
import tkinter as tk

import pytest

from app.gui import CollapsibleSection


def test_collapsible_section_toggles_content_without_destroying_children():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()
    try:
        section = CollapsibleSection(root, title="测试", expanded=True)
        child = tk.Entry(section.content)
        child.pack()
        assert section.expanded is True
        assert section.content.winfo_manager() == "pack"

        section.toggle()
        assert section.expanded is False
        assert section.content.winfo_manager() == ""
        assert child.winfo_exists() == 1

        section.toggle()
        assert section.expanded is True
        assert section.content.winfo_manager() == "pack"
        assert child.winfo_exists() == 1
    finally:
        root.destroy()
```

- [ ] **Step 6: 运行测试并确认因符号不存在而失败**

Run: `python -m pytest tests/test_gui_scroll_collapse.py::test_collapsible_section_toggles_content_without_destroying_children -v`

Expected: FAIL，提示无法从 `app.gui` 导入 `CollapsibleSection`。

- [ ] **Step 7: 实现最小折叠分组控件**

```python
class CollapsibleSection(ttk.Frame):
    def __init__(self, parent, *, title, expanded=False, on_layout_changed=None):
        super().__init__(parent)
        self.expanded = bool(expanded)
        self._on_layout_changed = on_layout_changed
        header = ttk.Frame(self, relief=tk.RIDGE, borderwidth=1, padding=(9, 5))
        header.pack(fill=tk.X)
        label = ttk.Label(header, text=title, font=(UI_FONT, UI_HEADING_FONT_SIZE, "bold"), cursor="hand2")
        label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.arrow = ttk.Label(header, text="▼" if self.expanded else "▶", width=3, anchor=tk.CENTER, cursor="hand2")
        self.arrow.pack(side=tk.RIGHT)
        self.content = ttk.Frame(self, padding=(8, 4, 4, 4))
        for widget in (header, label, self.arrow):
            widget.bind("<Button-1>", self.toggle)
        if self.expanded:
            self.content.pack(fill=tk.X)

    def toggle(self, _event=None):
        self.expanded = not self.expanded
        if self.expanded:
            self.content.pack(fill=tk.X)
            self.arrow.configure(text="▼")
        else:
            self.content.pack_forget()
            self.arrow.configure(text="▶")
        if self._on_layout_changed is not None:
            self.after_idle(self._on_layout_changed)
        return "break"
```

- [ ] **Step 8: 运行 Task 1 全部测试**

Run: `python -m pytest tests/test_gui_scroll_collapse.py -v`

Expected: 2 passed；无图形显示环境时只有 Tk 控件测试为 skipped，滚轮换算测试仍为 passed。

---

### Task 2: 小说项目页独立滚动与分组接入

**Files:**
- Modify: `app/gui.py:623-1055`
- Modify: `tests/test_gui_scroll_collapse.py`

**Interfaces:**
- Consumes: `_mousewheel_units(delta: int, platform: str) -> int`
- Consumes: `CollapsibleSection(...).content`
- Produces: `self._project_canvas`、`self._project_scrollbar`、`self._project_series_section`、`self._project_longform_section`，供运行期刷新和测试检查。

- [ ] **Step 1: 写项目页布局的失败集成测试**

```python
def test_source_panel_builds_scrollable_collapsible_project_page():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()
    try:
        app = PipelineGUI.__new__(PipelineGUI)
        app.root = root
        app._left_pane = None
        app._refresh_jobs = lambda *args, **kwargs: None
        parent = ttk.Frame(root)
        parent.pack(fill=tk.BOTH, expand=True)
        app._build_source_panel(parent)
        root.update_idletasks()

        assert app._project_canvas.winfo_exists() == 1
        assert str(app._project_scrollbar.cget("orient")) == tk.VERTICAL
        assert app._project_series_section.expanded is True
        assert app._project_longform_section.expanded is False
    finally:
        root.destroy()
```

- [ ] **Step 2: 运行测试并确认缺少项目页滚动属性而失败**

Run: `python -m pytest tests/test_gui_scroll_collapse.py::test_source_panel_builds_scrollable_collapsible_project_page -v`

Expected: FAIL，提示 `_project_canvas` 不存在。

- [ ] **Step 3: 把项目页改成 Canvas + 内容 Frame + 纵向 Scrollbar**

在 `project_tab` 中保留 Notebook 页本身，只加入 `project_scroll_host`。创建 `project_canvas`、`project_scrollbar` 和 `project_body`，将当前项目页所有控件的父级从 `project_tab` 改为 `project_body`。用 `<Configure>` 更新 `scrollregion`，用 Canvas 的 `<Configure>` 把 `project_body` 窗口宽度同步到可视宽度，并保存：

```python
self._project_canvas = project_canvas
self._project_scrollbar = project_scrollbar
```

- [ ] **Step 4: 用两个折叠分组替换原 LabelFrame**

```python
self._project_series_section = CollapsibleSection(
    project_body,
    title="当前项目的统一名称与分集规则",
    expanded=True,
    on_layout_changed=refresh_project_scrollregion,
)
series_settings = self._project_series_section.content

self._project_longform_section = CollapsibleSection(
    project_body,
    title="长篇连续制作（手动开启，书库和 TXT 通用）",
    expanded=False,
    on_layout_changed=refresh_project_scrollregion,
)
longform_settings = self._project_longform_section.content
```

现有表单变量、按钮命令和 grid/pack 布局保持不变。

- [ ] **Step 5: 接入跨平台滚轮并保护项目树自身滚动**

为项目 Canvas 和其非 Treeview 子控件绑定 `<MouseWheel>`、`<Button-4>`、`<Button-5>`。处理函数调用 `_mousewheel_units`；若事件目标位于 `self.project_tree` 内则返回 `None`，否则滚动 `project_canvas` 并返回 `"break"`。

- [ ] **Step 6: 调整 Notebook 高度策略**

`resize_source_notebook` 对 `project_tab` 不再使用完整内容请求高度，而使用当前左侧上半区的可用高度；其他三个标签页继续保持现有按请求高度调整的行为。切换到项目页后调用 `refresh_project_scrollregion()`，避免折叠或首次显示时滚动范围陈旧。

- [ ] **Step 7: 运行项目页集成测试**

Run: `python -m pytest tests/test_gui_scroll_collapse.py -v`

Expected: 3 passed；无图形显示环境时 Tk 控件测试可跳过。

---

### Task 3: 回归与操作验证

**Files:**
- Verify: `app/gui.py`
- Verify: `tests/test_gui_scroll_collapse.py`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的完整实现。
- Produces: 可交付、经验证的 GUI 行为。

- [ ] **Step 1: 运行新增测试**

Run: `python -m pytest tests/test_gui_scroll_collapse.py -v`

Expected: 全部通过，或仅因无 Tk 显示而跳过明确标注的 UI 测试。

- [ ] **Step 2: 运行项目安全验证包**

```powershell
python -m py_compile app/config.py app/gui.py app/pipeline_runner.py app/upload.py app/vendor/stage5_upload_browser.py app/youtube_ad_suitability.py app/updater.py app/update_tab.py scripts/apply_update.py scripts/build_release_package.py
python -m compileall app
python -c "from app import upload; mod=upload._load(); print(mod.__name__, hasattr(mod, 'upload_via_browser'), hasattr(mod, '_select_file_with_playwright')); from app.config import config; print(config.get('settings_schema_version'), config.get('browser_chrome_profile')); from app.utils.secrets import redact_secret_text; print(redact_secret_text('Bearer sk-example1234567890'))"
```

Expected: 命令退出码为 0；上传函数属性均为 `True`；密钥输出被遮盖。

- [ ] **Step 3: 启动 GUI 做人工验收**

Run: `python app/gui.py`

检查：

1. 打开“小说项目”页，把上方和下方分隔条拖到较小高度。
2. 页面右侧有纵向滚动条，鼠标位于普通设置控件上时可滚到项目列表。
3. 项目树和任务表格仍使用各自滚轮，不带动外层页面。
4. “统一名称与分集规则”默认展开；“长篇连续制作”默认折叠。
5. 两个标题栏点击后可以展开/收起，输入内容不丢失。
6. 书库导入、文件导入、任务分类和右侧配置页布局未变化。

- [ ] **Step 4: 检查最终差异**

Run: `git diff -- app/gui.py tests/test_gui_scroll_collapse.py`（若之后初始化了 Git）；当前非 Git 目录则用 `Get-Content` 检查新增测试和修改区域。

Expected: 只包含计划范围内的 GUI、测试和设计/计划文档变更。
