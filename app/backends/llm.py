"""LLM backend：用于把日语小说段落转换为 SD 文生图 prompt。
所有 provider 都走 OpenAI 兼容接口（绝大多数都支持），ollama 也支持 /v1。
"""
from __future__ import annotations

from app.utils.http import http_post
from app.utils.secrets import clean_api_key, redact_secret_text


class LLMBackend:
    def __init__(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        style_suffix: str = "",
        temperature: float = 0.7,
        max_tokens: int = 200,
        timeout: float = 60.0,
    ):
        self.provider = str(provider or "openai").strip().lower()
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = clean_api_key(api_key)
        self.model = str(model or "").strip()
        self.system_prompt = str(system_prompt or "")
        self.style_suffix = str(style_suffix or "")
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.timeout = float(timeout)

    def storyboard(self, segment_text: str) -> str:
        """输入一段小说文本，返回一个英文 SD prompt。"""
        return self.complete(self.system_prompt, segment_text)

    def complete(
        self,
        system_prompt: str,
        user_text: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Generic chat completion used by rewrite, title, storyboard, and analysis."""
        if self.provider == "claude":
            return self._claude_complete(system_prompt, user_text, max_tokens=max_tokens, temperature=temperature)
        return self._openai_compat_complete(system_prompt, user_text, max_tokens=max_tokens, temperature=temperature)

    def _openai_compat_complete(
        self,
        system_prompt: str,
        user_text: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": str(system_prompt or "")},
                {"role": "user", "content": str(user_text or "")},
            ],
            "temperature": self.temperature if temperature is None else float(temperature),
            "max_tokens": self.max_tokens if max_tokens is None else int(max_tokens),
        }
        try:
            r = http_post(url, json=payload, headers=headers, timeout=self.timeout)
            r.raise_for_status()
        except Exception as exc:
            raise RuntimeError(redact_secret_text(exc)) from exc
        data = r.json()
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content")
        # Reasoning-capable models can spend the entire max_tokens allowance
        # before emitting visible content.  Returning an empty string hides
        # that condition and makes every structured caller report a misleading
        # JSON parse error, so preserve the gateway's completion reason here.
        if content is None or not str(content).strip():
            finish_reason = str(choice.get("finish_reason") or "unknown")
            usage = data.get("usage") if isinstance(data, dict) else None
            completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
            detail = f", completion_tokens={completion_tokens}" if completion_tokens is not None else ""
            raise RuntimeError(
                f"Text API returned empty assistant content (finish_reason={finish_reason}{detail})"
            )
        prompt = str(content).strip()
        if self.style_suffix and self.style_suffix.lower() not in prompt.lower():
            prompt = f"{prompt}, {self.style_suffix}"
        return prompt

    def _claude_complete(
        self,
        system_prompt: str,
        user_text: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens if max_tokens is None else int(max_tokens),
            "system": str(system_prompt or ""),
            "messages": [{"role": "user", "content": str(user_text or "")}],
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        try:
            r = http_post(url, json=payload, headers=headers, timeout=self.timeout)
            r.raise_for_status()
        except Exception as exc:
            raise RuntimeError(redact_secret_text(exc)) from exc
        data = r.json()
        prompt = data["content"][0]["text"].strip()
        if self.style_suffix and self.style_suffix.lower() not in prompt.lower():
            prompt = f"{prompt}, {self.style_suffix}"
        return prompt
