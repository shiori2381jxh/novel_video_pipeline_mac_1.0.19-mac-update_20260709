#!/usr/bin/env python3
"""Build scrubbed macOS or Windows release archives for GitHub Releases."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
COMMON_COPY_FILES = (
    "AGENTS.md",
    "README.md",
    "requirements.txt",
    "update.bat",
)
PLATFORM_COPY_FILES = {
    "macos": (
        "Install_Mac_Dependencies.command",
        "Install_VoxCPM.command",
        "Open_GUI.command",
    ),
    "windows": (
        "Install_Windows_Dependencies.bat",
        "Install_VoxCPM.bat",
        "Chrome调试模式启动.bat",
        "Seedance画布.bat",
        "启动.bat",
        "桌面GUI.bat",
    ),
}
COPY_DIRS = ("app", "assets", "docs", "scripts", "prompts", "vendor", "TTS试听")
IGNORE_DIRS = {"__pycache__", ".git", ".venv", "dist"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}
IGNORE_FILES = {".DS_Store"}


def version() -> str:
    import sys

    sys.path.insert(0, str(ROOT))
    from app.version import VERSION

    return str(VERSION)


def api_key_fields() -> set[str]:
    import sys

    sys.path.insert(0, str(ROOT))
    from app.config import API_KEY_FIELDS

    return set(API_KEY_FIELDS)


def safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-") or "release"


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def scrub_settings(data: dict) -> dict:
    cleaned = dict(data)
    for key in api_key_fields():
        cleaned.pop(key, None)
    for noisy in (
        "dependency_last_report",
        "hardware_autotune_summary",
        "hardware_autotune_signature",
        "hardware_autotune_at",
    ):
        if noisy in cleaned:
            cleaned[noisy] = ""
    return cleaned


def load_default_settings(target_platform: str = "macos") -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    from app.config import fresh_install_settings

    settings = scrub_settings(fresh_install_settings())
    if target_platform == "windows":
        settings["update_manifest_url"] = (
            "https://github.com/shiori2381jxh/"
            "novel_video_pipeline_mac_1.0.19-mac-update_20260709/"
            "releases/latest/download/latest-windows.json"
        )
    return settings


def load_default_profile() -> tuple[str, dict]:
    import sys

    sys.path.insert(0, str(ROOT))
    from app.config import DEFAULT_JAPANESE_PROFILE_NAME, builtin_profile_settings

    profile = builtin_profile_settings(DEFAULT_JAPANESE_PROFILE_NAME)
    if not profile:
        raise RuntimeError("Missing built-in Japanese tweet source profile: 異世界推文1")
    return DEFAULT_JAPANESE_PROFILE_NAME, scrub_settings(profile)


def copy_source(staging: Path, target_platform: str) -> None:
    for rel in COMMON_COPY_FILES + PLATFORM_COPY_FILES[target_platform]:
        src = ROOT / rel
        if src.exists():
            copy_file(src, staging / rel)
    for rel in COPY_DIRS:
        src_dir = ROOT / rel
        if not src_dir.exists():
            continue
        for src in src_dir.rglob("*"):
            if src.is_dir():
                continue
            rel_path = src.relative_to(src_dir)
            if any(part in IGNORE_DIRS for part in rel_path.parts):
                continue
            if src.name in IGNORE_FILES:
                continue
            if src.suffix in IGNORE_SUFFIXES:
                continue
            copy_file(src, staging / rel / rel_path)


def copy_sanitized_data(staging: Path, target_platform: str) -> None:
    """Create clean defaults from the designated recipe, never from live credentials."""
    settings = load_default_settings(target_platform)
    profile_name, profile = load_default_profile()

    settings_dst = staging / "data" / "settings.json"
    settings_dst.parent.mkdir(parents=True, exist_ok=True)
    settings_dst.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

    defaults_dir = staging / "data" / "defaults"
    defaults_dir.mkdir(parents=True, exist_ok=True)
    (defaults_dir / "settings.template.json").write_text(
        json.dumps(load_default_settings(target_platform), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    profiles_dst = staging / "data" / "profiles"
    profiles_dst.mkdir(parents=True, exist_ok=True)
    default_profile = json.dumps(profile, ensure_ascii=False, indent=2)
    (profiles_dst / f"{profile_name}.json").write_text(default_profile, encoding="utf-8")
    (defaults_dir / f"{profile_name}.json").write_text(default_profile, encoding="utf-8")
    (defaults_dir / "profile.template.json").write_text(default_profile, encoding="utf-8")

    for rel in ("data/jobs", "data/projects", "data/runtime", "data/chrome_debug_profiles", "data/updates"):
        (staging / rel).mkdir(parents=True, exist_ok=True)


def chmod_commands(staging: Path) -> None:
    for rel in (
        "Open_GUI.command",
        "Install_Mac_Dependencies.command",
        "Install_VoxCPM.command",
        "scripts/start_gui_macos.command",
        "scripts/start_chrome_debug_macos.command",
        "scripts/start_seedance_canvas_macos.command",
    ):
        path = staging / rel
        if path.exists():
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_zip(staging: Path, zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src in sorted(staging.rglob("*")):
            if src.is_file():
                zf.write(src, src.relative_to(staging.parent))
    h = hashlib.sha256()
    with zip_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_asset_url(repo: str, tag: str, zip_name: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    repo = str(repo or "").strip().strip("/")
    if not repo:
        return ""
    return f"https://github.com/{repo}/releases/download/{tag}/{zip_name}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a scrubbed Windows or macOS release package.")
    parser.add_argument("--output-dir", default=str(DIST))
    parser.add_argument("--platform", choices=("macos", "windows"), default="macos")
    parser.add_argument("--repo", default="1951779219/novel_video_pipeline_mac_release", help="GitHub release repo owner/name")
    parser.add_argument("--asset-url", default="", help="Explicit package download URL")
    parser.add_argument("--notes", default="", help="Release notes for latest.json")
    parser.add_argument("--notes-file", default="", help="Release notes file")
    args = parser.parse_args()

    ver = version()
    tag = f"v{ver}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    platform_slug = "windows" if args.platform == "windows" else "mac"
    package_name = f"novel_video_pipeline_{platform_slug}_{safe_slug(ver)}_{time.strftime('%Y%m%d')}"
    staging = output_dir / package_name
    zip_path = output_dir / f"{package_name}.zip"
    manifest_name = "latest-windows.json" if args.platform == "windows" else "latest.json"
    latest_path = output_dir / manifest_name

    if staging.exists():
        shutil.rmtree(staging)
    if zip_path.exists():
        zip_path.unlink()
    staging.mkdir(parents=True)

    copy_source(staging, args.platform)
    copy_sanitized_data(staging, args.platform)
    if args.platform == "macos":
        chmod_commands(staging)
    digest = make_zip(staging, zip_path)

    notes = args.notes
    if args.notes_file:
        notes_file = Path(args.notes_file)
        if notes_file.exists():
            notes = notes_file.read_text(encoding="utf-8")
    if not notes:
        platform_name = "Windows" if args.platform == "windows" else "macOS"
        notes = f"Novel Video Pipeline {ver} {platform_name} update."

    manifest = {
        "version": ver,
        "url": build_asset_url(args.repo, tag, zip_path.name, args.asset_url),
        "sha256": digest,
        "notes": notes.strip(),
        "mandatory": False,
        "platform": args.platform,
    }
    latest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(zip_path)
    print(latest_path)
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
