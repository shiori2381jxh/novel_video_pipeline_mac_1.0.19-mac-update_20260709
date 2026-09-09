import tkinter as tk
from tkinter import ttk

import pytest

from app.gui import CollapsibleSection, PipelineGUI, _mousewheel_units


def test_mousewheel_units_supports_windows_and_macos_deltas():
    assert _mousewheel_units(120, "win32") == -1
    assert _mousewheel_units(-120, "win32") == 1
    assert _mousewheel_units(1, "darwin") == -1
    assert _mousewheel_units(-1, "darwin") == 1


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
