# Windows Personal Configuration Attachment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put `personal_config_windows_20260903` into Windows release archives as a separate, manually imported configuration attachment.

**Architecture:** Extend the release builder's Windows-only inputs with the attachment directory. Copy it into the staging root before archive creation, while leaving `copy_sanitized_data()` as the exclusive writer of the release `data/` directory.

**Tech Stack:** Python standard library (`pathlib`, `shutil`, `zipfile`), PowerShell validation.

## Global Constraints

- Include the attachment only for `--platform windows`.
- Preserve all attachment contents and paths below `personal_config_windows_20260903/`.
- Do not copy the attachment into the root `data/` directory.
- macOS packages must neither include nor require the attachment.
- A missing attachment directory must fail a Windows build with a clear error.

---

### Task 1: Copy the Windows-only attachment

**Files:**
- Modify: `scripts/build_release_package.py`
- Test: PowerShell ZIP-content inspection against a generated Windows archive

**Interfaces:**
- Consumes: `ROOT`, `copy_file()`, and `copy_source(staging, target_platform)`.
- Produces: A staged `personal_config_windows_20260903/` directory only for Windows builds.

- [ ] **Step 1: Add a Windows-only attachment constant**

Add `WINDOWS_CONFIG_ATTACHMENT_DIR = "personal_config_windows_20260903"` near
the release copy constants. Its value is relative to `ROOT`.

- [ ] **Step 2: Add a reusable directory-copy helper**

Add a helper that verifies the source is a directory, raises
`RuntimeError(f"Missing required Windows configuration attachment: {src}")`
when absent, then recursively copies files to the destination with the
existing `IGNORE_DIRS`, `IGNORE_FILES`, and `IGNORE_SUFFIXES` filters.

- [ ] **Step 3: Copy the attachment conditionally**

At the end of `copy_source()`, when `target_platform == "windows"`, invoke
the helper with `ROOT / WINDOWS_CONFIG_ATTACHMENT_DIR` and
`staging / WINDOWS_CONFIG_ATTACHMENT_DIR`.

- [ ] **Step 4: Compile the changed package builder**

Run: `python -m py_compile scripts/build_release_package.py`

Expected: exit code 0.

### Task 2: Build and inspect a Windows package

**Files:**
- Test: A temporary output directory under `dist/`

**Interfaces:**
- Consumes: `scripts/build_release_package.py` from Task 1.
- Produces: Evidence that the archive has the separate manual-import folder and sanitized root data.

- [ ] **Step 1: Build a Windows archive**

Run: `python scripts/build_release_package.py --platform windows --output-dir dist/config-attachment-check`

Expected: a ZIP archive and manifest are reported under the selected output directory.

- [ ] **Step 2: Inspect required attachment paths**

Run PowerShell to open the generated ZIP and assert it contains:

```text
personal_config_windows_20260903/Import_My_Config_Windows.bat
personal_config_windows_20260903/Import_My_Config_Windows.ps1
personal_config_windows_20260903/config_payload/data/settings.json
personal_config_windows_20260903/config_payload/data/youtube_channel_bindings.json
```

Expected: every required entry is present.

- [ ] **Step 3: Inspect root settings isolation**

Open both archived JSON files and confirm the root release
`data/settings.json` does not equal the attachment settings payload.

Expected: the release keeps fresh-install settings separate from the manual
configuration payload.

- [ ] **Step 4: Run the required validation bundle**

Run the project's Python compile and import checks from `AGENTS.md`.

Expected: all commands exit successfully.
