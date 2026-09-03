import unittest

from app import config as config_module
from scripts import apply_update, build_release_package


class WindowsReleaseTests(unittest.TestCase):
    def test_windows_release_contains_operator_entrypoints(self):
        files = set(build_release_package.PLATFORM_COPY_FILES["windows"])
        self.assertIn("启动.bat", files)
        self.assertIn("Install_Windows_Dependencies.bat", files)
        self.assertIn("Chrome调试模式启动.bat", files)

    def test_windows_defaults_use_platform_specific_manifest(self):
        settings = build_release_package.load_default_settings("windows")
        self.assertTrue(settings["update_manifest_url"].endswith("/latest-windows.json"))

    def test_updater_copies_windows_launchers(self):
        files = set(apply_update.COPY_FILES)
        self.assertIn("启动.bat", files)
        self.assertIn("Install_Windows_Dependencies.bat", files)
        self.assertIn("Install_VoxCPM.bat", files)

    def test_update_channel_is_not_part_of_production_profiles(self):
        self.assertIn("update_manifest_url", config_module.PROFILE_LOCAL_FIELDS)

    def test_shared_version_has_no_platform_suffix(self):
        version = build_release_package.version()
        self.assertNotIn("windows", version.lower())
        self.assertNotIn("mac", version.lower())


if __name__ == "__main__":
    unittest.main()
