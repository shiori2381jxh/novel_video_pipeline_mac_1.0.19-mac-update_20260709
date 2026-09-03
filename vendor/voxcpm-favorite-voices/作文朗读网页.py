"""Dependency-free local browser UI for the installed VoxCPM CLI."""

from __future__ import annotations

from datetime import datetime
import json
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading
import tempfile
from urllib.parse import unquote, urlparse
import uuid
import webbrowser

from reader_helpers import (
    build_command,
    load_voice_settings,
    load_output_directory,
    sanitize_filename,
    save_output_directory,
    save_voice_settings,
)


PRESETS = {
    '温柔女教师': '温柔的女教师，吐字清晰自然，适合朗读作文，语速适中。',
    '沉稳男声': '成熟的男声，沉稳有磁性，吐字清晰，适合朗读。',
    '活泼童声': '活泼开朗的少年声音，明亮自然，语速适中。',
    '情感朗读': '富有感情地朗读，语调自然，有适当停顿，语速适中。',
    '自定义': '',
}
TOOL_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = TOOL_DIR.parent
VOXCPM_EXE = Path(r'C:\姜\小程序各种\.venv-voxcpm\Scripts\voxcpm.exe')
DESKTOP_DIR = Path.home() / 'Desktop'
SETTINGS_PATH = TOOL_DIR / 'settings.json'
FAVORITES_DIR = TOOL_DIR / 'favorite_voices'
FAVORITES_PATH = TOOL_DIR / 'favorite_voices.json'
PREVIEW_CACHE = tempfile.TemporaryDirectory(prefix='voxcpm-preview-')
PREVIEW_DIRECTORY = Path(PREVIEW_CACHE.name)


def current_output_directory() -> Path:
    return load_output_directory(SETTINGS_PATH, DESKTOP_DIR)


def current_voice_settings() -> tuple[str, str]:
    return load_voice_settings(SETTINGS_PATH, PRESETS)


def choose_output_directory() -> tuple[Path | None, str]:
    """Open the native Windows folder picker without relying on broken Tk."""
    command = (
        "$shell = New-Object -ComObject Shell.Application; "
        "$folder = $shell.BrowseForFolder(0, '请选择语音保存文件夹', 0, 0); "
        "if ($folder) { $folder.Self.Path }"
    )
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-STA', '-Command', command],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    selected = Path(result.stdout.strip()) if result.stdout.strip() else None
    if selected is None:
        return None, '没有更改保存位置。'
    if not selected.is_dir():
        return None, '选择的保存位置无效。'
    try:
        save_output_directory(SETTINGS_PATH, selected)
    except OSError as error:
        return None, f'无法保存设置：{error}'
    return selected, f'已设置默认保存位置：{selected}'


LAST_OUTPUT: Path | None = None


def favorites() -> dict[str, dict]:
    try:
        data = json.loads(FAVORITES_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def favorite_audio(name: str) -> Path | None:
    item = favorites().get(name, {})
    path = FAVORITES_DIR / item.get('file', '')
    return path if path.is_file() and path.suffix.lower() == '.wav' else None


def generate(
    text: str, control: str, filename: str, preview_only: bool = False, favorite: str = '',
) -> tuple[Path | None, str]:
    if not text.strip():
        return None, '请先粘贴或输入要朗读的内容。'
    if not control.strip():
        return None, '请选择语气预设，或填写自定义语气描述。'
    if not VOXCPM_EXE.is_file():
        return None, f'找不到 VoxCPM 程序：{VOXCPM_EXE}'
    safe_name = sanitize_filename(filename)
    if not safe_name.lower().endswith('.wav'):
        safe_name += '.wav'
    output = (
        PREVIEW_DIRECTORY / f'preview_{uuid.uuid4().hex}.wav'
        if preview_only else current_output_directory() / safe_name
    )
    reference_audio = favorite_audio(favorite)
    result = subprocess.run(
        build_command(VOXCPM_EXE, text.strip(), control.strip(), output, reference_audio),
        capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    if result.returncode or not output.is_file():
        return None, (result.stderr or result.stdout or '没有生成音频文件。')[-2500:]
    global LAST_OUTPUT
    LAST_OUTPUT = output
    mode_message = f'已使用收藏音色：{favorite}。' if reference_audio else '已使用语气描述设计声音。'
    if preview_only:
        return output, f'{mode_message} 试听生成完成；音频只保存在临时缓存中，关闭工具后会自动清理。'
    return output, f'{mode_message} 生成完成，已保存到桌面：{output.name}'


PAGE = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>作文朗读工具</title>
<style>body{{font:16px "Microsoft YaHei",sans-serif;background:#f5f7fb;margin:0}}main{{max-width:780px;margin:32px auto;background:#fff;padding:28px;border-radius:14px;box-shadow:0 4px 18px #0002}}textarea,input,select,button{{box-sizing:border-box;width:100%;font:16px inherit;padding:10px;margin:6px 0 16px}}textarea{{height:260px;resize:vertical}}button{{background:#2368c4;color:white;border:0;border-radius:8px;font-weight:bold;cursor:pointer}}#status{{white-space:pre-wrap;color:#245f2b}}#runtime-log{{box-sizing:border-box;width:100%;min-height:120px;max-height:240px;overflow:auto;white-space:pre-wrap;background:#18212b;color:#d8f3dc;border-radius:8px;padding:12px;font:13px Consolas,"Microsoft YaHei",monospace}}</style>
<main><h1>作文朗读工具</h1><p>粘贴作文，选择语气后生成音频。</p>
<label>朗读内容</label><textarea id="text" placeholder="在这里粘贴作文……"></textarea>
<label>语气预设</label><select id="preset">{''.join(f'<option>{x}</option>' for x in PRESETS)}</select>
<label>语气描述（可修改）</label><input id="control" value="{PRESETS['温柔女教师']}">
<label><input id="preview-only" type="checkbox" style="width:auto;margin-right:8px">仅试听（不保存文件）</label>
<div id="save-fields"><label>保存文件名</label><input id="filename" value="作文朗读_{datetime.now():%Y%m%d_%H%M%S}.wav">
<label>当前保存位置</label><input id="folder" readonly><button id="choose" type="button">更改保存位置</button></div>
<button id="go">生成语音</button><p id="status"></p><audio id="audio" controls style="width:100%"></audio><h2>运行日志</h2><button id="clear-log" type="button">清空日志</button><div id="runtime-log" aria-live="polite"></div></main>
<script>const presets={json.dumps(PRESETS, ensure_ascii=False)};const p=document.querySelector('#preset'),c=document.querySelector('#control'),f=document.querySelector('#folder'),s=document.querySelector('#status'),preview=document.querySelector('#preview-only'),saveFields=document.querySelector('#save-fields'),go=document.querySelector('#go'),log=document.querySelector('#runtime-log');function appendLog(message){{const time=new Date().toLocaleTimeString('zh-CN',{{hour12:false}});log.textContent+=`[${{time}}] ${{message}}\n`;log.scrollTop=log.scrollHeight}}document.querySelector('#clear-log').onclick=()=>{{log.textContent='';appendLog('日志已清空。')}};async function saveVoiceSettings(){{await fetch('/settings',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{preset:p.value,voice_description:c.value}})}})}}p.onchange=async()=>{{c.value=presets[p.value];await saveVoiceSettings();appendLog('已切换语气预设。')}};c.oninput=saveVoiceSettings;preview.onchange=()=>{{saveFields.hidden=preview.checked;go.textContent=preview.checked?'生成试听':'生成语音';appendLog(preview.checked?'已启用仅试听模式。':'已切换为保存文件模式。')}};async function refreshSettings(){{let d=await (await fetch('/settings')).json();f.value=d.output_directory;p.value=d.preset;c.value=d.voice_description}}refreshSettings().then(()=>appendLog('页面准备完成。')).catch(e=>appendLog('读取设置失败：'+e));document.querySelector('#choose').onclick=async()=>{{let b=document.querySelector('#choose');b.disabled=true;s.textContent='请在弹出的窗口选择文件夹……';appendLog('正在选择保存位置。');try{{let d=await (await fetch('/choose-output-directory',{{method:'POST'}})).json();s.textContent=d.message;if(d.output_directory)f.value=d.output_directory;appendLog(d.message)}}catch(e){{s.textContent='选择失败：'+e;appendLog('选择失败：'+e)}}finally{{b.disabled=false}}}};go.onclick=async()=>{{let b=go;b.disabled=true;s.textContent='正在生成，请耐心等待……';appendLog(preview.checked?'正在生成试听。':'正在生成并保存语音。');try{{let r=await fetch('/generate',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{text:text.value,control:c.value,filename:filename.value,preview_only:preview.checked}})}});let d=await r.json();s.textContent=d.message;appendLog(d.message);if(d.audio){{audio.src=d.audio;audio.play()}}}}catch(e){{s.textContent='连接失败：'+e;appendLog('连接失败：'+e)}}finally{{b.disabled=false}}}};</script></html>'''


def audio_target(filename: str) -> Path | None:
    """Return an existing WAV from a server-controlled output directory."""
    for directory in (PREVIEW_DIRECTORY, current_output_directory()):
        candidate = directory / filename
        if candidate.is_file() and candidate.suffix.lower() == '.wav':
            return candidate
    return None


PAGE = PAGE.replace('</main>', '<h2>收藏音色</h2><select id="favorite"><option value="">不使用收藏音色</option></select><button id="delete-favorite" type="button">删除所选收藏</button><input id="favorite-name" placeholder="收藏名称"><button id="save-favorite" type="button">收藏当前音色</button></main>')
PAGE = PAGE.replace('preview_only:preview.checked', 'preview_only:preview.checked,favorite:fav.value')
PAGE = PAGE.replace('</script>', '''const fav=document.querySelector('#favorite');async function loadFavorites(){let d=await (await fetch('/favorites')).json();fav.innerHTML='<option value="">不使用收藏音色</option>'+d.items.map(x=>'<option>'+x+'</option>').join('')}loadFavorites();document.querySelector('#save-favorite').onclick=async()=>{let name=document.querySelector('#favorite-name').value;let d=await (await fetch('/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,description:c.value})})).json();appendLog(d.message);await loadFavorites();fav.value=name};document.querySelector('#delete-favorite').onclick=async()=>{if(!fav.value)return;let d=await (await fetch('/favorites/'+encodeURIComponent(fav.value),{method:'DELETE'})).json();appendLog(d.message);loadFavorites()};</script>''')


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == '/':
            raw = PAGE.encode('utf-8'); self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path == '/settings':
            preset, voice_description = current_voice_settings()
            self.send_json({
                'output_directory': str(current_output_directory()),
                'preset': preset,
                'voice_description': voice_description,
            }); return
        if path == '/favorites':
            self.send_json({'items': list(favorites())}); return
        if path.startswith('/audio/'):
            target = audio_target(Path(path).name)
            if target is not None:
                raw = target.read_bytes(); self.send_response(200); self.send_header('Content-Type', 'audio/wav'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == '/favorites':
            global LAST_OUTPUT
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
                name = sanitize_filename(str(body.get('name', ''))).removesuffix('.wav')
                if not name or LAST_OUTPUT is None or not LAST_OUTPUT.is_file(): raise ValueError('请先成功生成音频，再输入收藏名称。')
                FAVORITES_DIR.mkdir(exist_ok=True); target = FAVORITES_DIR / f'{name}.wav'; shutil.copy2(LAST_OUTPUT, target)
                data = favorites(); data[name] = {'file': target.name, 'description': body.get('description', '')}; FAVORITES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                self.send_json({'message': f'已收藏音色：{name}'})
            except Exception as error: self.send_json({'message': f'收藏失败：{error}'})
            return
        if self.path == '/choose-output-directory':
            output, message = choose_output_directory()
            self.send_json({'message': message, 'output_directory': str(output) if output else None}); return
        if self.path == '/settings':
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
                preset = body.get('preset')
                voice_description = body.get('voice_description')
                if preset not in PRESETS or not isinstance(voice_description, str):
                    raise ValueError('语气设置无效。')
                save_voice_settings(SETTINGS_PATH, preset, voice_description)
                self.send_json({'message': '已保存声音设置。'})
            except Exception as error:
                self.send_json({'message': f'无法保存声音设置：{error}'})
            return
        if self.path != '/generate': self.send_error(404); return
        try:
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
            output, message = generate(
                body.get('text', ''), body.get('control', ''), body.get('filename', ''),
                bool(body.get('preview_only')),
                body.get('favorite', ''),
            )
            self.send_json({'message': message, 'audio': '/audio/' + output.name if output else None})
        except Exception as error:
            self.send_json({'message': f'发生错误：{error}', 'audio': None})

    def do_DELETE(self) -> None:
        if not self.path.startswith('/favorites/'):
            self.send_error(404); return
        name = unquote(self.path.removeprefix('/favorites/'))
        data = favorites(); item = data.pop(name, None)
        if item is None:
            self.send_json({'message': '收藏不存在。'}); return
        target = FAVORITES_DIR / item.get('file', '')
        if target.is_file(): target.unlink()
        FAVORITES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        self.send_json({'message': f'已删除收藏：{name}'})

    def log_message(self, _format: str, *_args: object) -> None: pass


def main() -> None:
    server = ThreadingHTTPServer(('127.0.0.1', 7860), Handler)
    threading.Timer(0.2, webbrowser.open, args=('http://127.0.0.1:7860',)).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
