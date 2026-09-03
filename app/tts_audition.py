"""Generate provider-separated TTS audition files for the desktop GUI."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from app.backends.tts import (
    EDGE_MULTI_VOICES,
    TTSBackend,
    normalize_voxcpm_voice,
    voxcpm_voice_display,
    voxcpm_voice_entries,
)
from app.config import ROOT


AUDITION_ROOT = ROOT / "TTS试听"
AUDITION_DISABLED_PROVIDERS = {"voicevox", "silent"}


def _safe_filename_component(value: object, fallback: str = "default") -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    return text[:120] or fallback


def audition_directory(provider: str) -> Path:
    name = str(provider or "").strip().lower()
    if not name:
        raise ValueError("TTS Provider 不能为空")
    if name in AUDITION_DISABLED_PROVIDERS:
        if name == "voicevox":
            raise ValueError("VOICEVOX 请直接在 VOICEVOX 软件中试听，本程序不重复生成试听文件。")
        raise ValueError(f"{name} 不生成试听文件")
    directory = AUDITION_ROOT / _safe_filename_component(name, "unknown")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def audition_text_for_voice(provider: str, voice: str) -> str:
    provider = str(provider or "").lower()
    voice = str(voice or "").lower()
    if provider == "voxcpm":
        return "你好，这是本地 VoxCPM 收藏音色试听。愿故事里的每一个人物，都拥有自然清晰的声音。"
    if voice.startswith("ja-"):
        return "こんにちは。これは音声サンプルです。物語の世界を、自然で聞き取りやすい声でお届けします。"
    if voice.startswith(("zh-hk", "zh-tw")):
        return "你好，這是一段語音試聽。接下來，我會用自然清晰的聲音為你講述故事。"
    if voice.startswith("zh-"):
        return "你好，这是一段语音试听。接下来，我会用自然清晰的声音为你讲述故事。"
    if voice.startswith("ko-"):
        return "안녕하세요. 이것은 음성 미리 듣기입니다. 자연스럽고 또렷한 목소리로 이야기를 들려드리겠습니다."
    if voice.startswith("es-"):
        return "Hola. Esta es una muestra de voz clara y natural para narrar historias."
    if voice.startswith("fr-"):
        return "Bonjour. Voici un échantillon de voix naturelle et claire pour raconter des histoires."
    if voice.startswith("de-"):
        return "Hallo. Dies ist eine natürliche und deutliche Stimmprobe zum Erzählen von Geschichten."
    if voice.startswith("en-"):
        return "Hello. This is a natural and clear voice sample for bringing stories to life."
    return "こんにちは。これはTTS音声の試聴です。自然で聞き取りやすい声で物語をお届けします。"


def audition_filename(provider: str, voice: str, model: str = "") -> str:
    provider = str(provider or "").strip().lower()
    voice = str(voice or "").strip()
    if provider == "voxcpm":
        stable_name = normalize_voxcpm_voice(voice)
        for index, (label, catalog_name) in enumerate(voxcpm_voice_entries(), start=1):
            if voice == label or stable_name == catalog_name:
                return f"{index:02d}_{_safe_filename_component(label)}.mp3"
    choices = EDGE_MULTI_VOICES if provider == "edge" else []
    if voice in choices:
        return f"{choices.index(voice) + 1:02d}_{_safe_filename_component(voice)}.mp3"
    model_suffix = f"__{_safe_filename_component(model)}" if model else ""
    return f"{_safe_filename_component(voice)}{model_suffix}.mp3"


def generate_audition(
    *,
    provider: str,
    voice: str,
    rate: str = "+0%",
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    emotion: str = "",
    volume: float | str = 1.0,
    extra: dict | None = None,
    text: str = "",
) -> tuple[Path, float]:
    provider = str(provider or "").strip().lower()
    if provider == "voxcpm":
        voice = voxcpm_voice_display(voice)
    directory = audition_directory(provider)
    out_path = directory / audition_filename(provider, voice, model)
    options = dict(extra or {})
    options.update({"model": model, "emotion": emotion, "timeout_seconds": 1800})
    backend = TTSBackend(
        provider=provider,
        voice=voice,
        rate=rate,
        api_key=api_key,
        base_url=base_url,
        extra=options,
        volume=volume,
    )
    duration = backend.synth(text or audition_text_for_voice(provider, voice), out_path)
    manifest_path = directory / "试听记录.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    if provider == "voxcpm":
        prefix = out_path.name.split("_", 1)[0] + "_"
        manifest = {name: row for name, row in manifest.items() if not name.startswith(prefix)}
    manifest[out_path.name] = {
        "provider": provider,
        "voice": voice,
        "model": model,
        "duration": round(float(duration), 3),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path, float(duration)
