from pathlib import Path


def test_voxcpm_installer_is_ascii_only_for_windows_cmd():
    """cmd parses a .bat before its chcp command can switch to UTF-8."""
    installer = Path(__file__).parents[1] / "Install_VoxCPM.bat"
    installer.read_bytes().decode("ascii")
