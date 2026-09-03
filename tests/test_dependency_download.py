import io
import os
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import dependency_manager


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ffmpeg/bin/ffmpeg.exe", b"ffmpeg")
        archive.writestr("ffmpeg/bin/ffprobe.exe", b"ffprobe")
    return buffer.getvalue()


class _Response:
    def __init__(self, chunks, headers, status=200):
        self._chunks = iter(chunks)
        self.headers = headers
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        item = next(self._chunks, b"")
        if isinstance(item, BaseException):
            raise item
        return item


class DependencyDownloadTests(unittest.TestCase):
    def test_ffmpeg_download_resumes_after_read_timeout(self):
        payload = _zip_bytes()
        split = len(payload) // 2
        first = _Response(
            [payload[:split], socket.timeout("stalled")],
            {"Content-Length": str(len(payload))},
        )
        second = _Response(
            [payload[split:], b""],
            {
                "Content-Length": str(len(payload) - split),
                "Content-Range": f"bytes {split}-{len(payload) - 1}/{len(payload)}",
            },
            status=206,
        )
        logs = []
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.dependency_manager.urllib.request.urlopen", side_effect=[first, second]
        ) as opener, patch.dict(os.environ, {"NOVEL_VIDEO_DOWNLOAD_RETRIES": "3"}):
            target = Path(tmp) / "ffmpeg.zip"
            dependency_manager._download_file("https://example.invalid/ffmpeg.zip", target, logs.append)
            self.assertEqual(target.read_bytes(), payload)
            self.assertFalse(target.with_suffix(".zip.part").exists())
            self.assertEqual(opener.call_count, 2)
            range_header = opener.call_args_list[1].args[0].headers.get("Range")
            self.assertEqual(range_header, f"bytes={split}-")
        self.assertTrue(any("下载中断" in line for line in logs))
        self.assertTrue(any("继续下载" in line for line in logs))

    def test_ffmpeg_download_stops_after_configured_retries(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.dependency_manager.urllib.request.urlopen", side_effect=socket.timeout("stalled")
        ) as opener, patch.dict(os.environ, {"NOVEL_VIDEO_DOWNLOAD_RETRIES": "2"}):
            with self.assertRaises(TimeoutError):
                dependency_manager._download_file(
                    "https://example.invalid/ffmpeg.zip",
                    Path(tmp) / "ffmpeg.zip",
                    lambda _message: None,
                )
            self.assertEqual(opener.call_count, 2)


class WindowsBootstrapScriptTests(unittest.TestCase):
    def test_gui_launcher_uses_absolute_venv_path_and_does_not_require_marker(self):
        script = Path("scripts/start_gui_windows.bat").read_text(encoding="utf-8")
        self.assertIn('set "VENV_PYTHON=%PROJECT_ROOT%\\.venv\\Scripts\\python.exe"', script)
        self.assertIn('if not exist "%VENV_PYTHON%"', script)
        self.assertNotIn('if not exist "%SETUP_MARKER%" (\n    powershell.exe', script)
        self.assertLess(script.index('if not exist "%VENV_PYTHON%"'), script.index("首次运行"))

    def test_setup_treats_ffmpeg_failure_as_fatal_before_writing_marker(self):
        script = Path("scripts/setup_windows.ps1").read_text(encoding="utf-8")
        ensure_index = script.index("--ensure-ffmpeg")
        failure_index = script.index('throw "FFmpeg 安装失败')
        marker_index = script.index("Set-Content -LiteralPath $SetupMarker")
        self.assertLess(ensure_index, failure_index)
        self.assertLess(failure_index, marker_index)


if __name__ == "__main__":
    unittest.main()
