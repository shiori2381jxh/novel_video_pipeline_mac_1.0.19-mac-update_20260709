from pathlib import Path
import json
import re


def sanitize_filename(value: str) -> str:
    """Return a safe Windows filename, preserving a supplied .wav suffix."""
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', value.strip())
    cleaned = cleaned.rstrip('. ')
    return cleaned or '朗读音频.wav'


def build_command(executable: Path, text: str, control: str, output: Path, reference_audio: Path | None = None) -> list[str]:
    command = [
        str(executable),
        'clone' if reference_audio is not None else 'design',
        '--text', text,
        '--control', control,
        '--output', str(output),
    ]
    if reference_audio is not None:
        command.extend(['--reference-audio', str(reference_audio)])
    return command


def load_output_directory(settings_path: Path, desktop_path: Path) -> Path:
    """Load a valid saved directory, falling back to the Desktop."""
    try:
        data = json.loads(settings_path.read_text(encoding='utf-8'))
        candidate = Path(data['output_directory'])
        return candidate if candidate.is_dir() else desktop_path
    except (OSError, ValueError, KeyError, TypeError):
        return desktop_path


def _load_settings_data(settings_path: Path) -> dict:
    try:
        data = json.loads(settings_path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_settings_data(settings_path: Path, data: dict) -> None:
    settings_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8',
    )


def save_output_directory(settings_path: Path, output_directory: Path) -> None:
    """Persist an existing directory for future output files."""
    if not output_directory.is_dir():
        raise ValueError('保存位置必须是已存在的文件夹。')
    data = _load_settings_data(settings_path)
    data['output_directory'] = str(output_directory)
    _save_settings_data(settings_path, data)


def load_voice_settings(settings_path: Path, presets: dict[str, str]) -> tuple[str, str]:
    """Load a valid saved voice preset and its Chinese description."""
    default_preset = '温柔女教师' if '温柔女教师' in presets else next(iter(presets))
    data = _load_settings_data(settings_path)
    preset = data.get('preset')
    if preset not in presets:
        preset = default_preset
    description = data.get('voice_description')
    if not isinstance(description, str) or not description.strip():
        description = presets[preset]
    return preset, description


def save_voice_settings(settings_path: Path, preset: str, voice_description: str) -> None:
    """Persist the selected voice preset without replacing output settings."""
    if not isinstance(preset, str) or not isinstance(voice_description, str):
        raise ValueError('语气设置无效。')
    data = _load_settings_data(settings_path)
    data['preset'] = preset
    data['voice_description'] = voice_description
    _save_settings_data(settings_path, data)
