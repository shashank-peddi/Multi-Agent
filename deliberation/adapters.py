"""Thin vendor adapters. API keys are read from the environment at call time."""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx

from deliberation.panel import VENDOR_KEY_ENVS, Panel, lookup_key, model_timeout_seconds


class ModelError(Exception):
    def __init__(self, model_id: str, message: str):
        self.model_id = model_id
        super().__init__(f"{model_id}: {message}")


class _HTTPAdapter:
    vendor = ""

    def __init__(self, model_id: str):
        vendor, _, name = model_id.partition("/")
        if vendor != self.vendor or not name:
            raise ValueError(f"{model_id} is not a {self.vendor} model id")
        self.model_id = model_id
        self.model_name = name

    def resolve_key(self) -> str:
        found = lookup_key(os.environ, self.vendor)
        if not found:
            names = " or ".join(VENDOR_KEY_ENVS[self.vendor])
            raise ModelError(self.model_id, f"{names} is not set")
        return found[1]

    async def _post(self, url: str, headers: dict, payload: dict) -> dict:
        timeout = model_timeout_seconds()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ModelError(self.model_id, "request failed") from exc
        if response.status_code >= 400:
            raise ModelError(self.model_id, f"HTTP {response.status_code}")
        try:
            data = response.json()
        except Exception as exc:
            raise ModelError(self.model_id, "unreadable response") from exc
        if not isinstance(data, dict):
            raise ModelError(self.model_id, "unreadable response")
        return data


class OpenAIAdapter(_HTTPAdapter):
    vendor = "openai"

    async def complete(self, *, system: str, user: str) -> str:
        key = self.resolve_key()
        data = await self._post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {key}"},
            {
                "model": self.model_name,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(self.model_id, "unreadable response") from exc
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text", "")))
                else:
                    parts.append(str(part))
            text = "".join(parts)
        else:
            text = str(content or "")
        if not text.strip():
            raise ModelError(self.model_id, "empty response")
        return text


class AnthropicAdapter(_HTTPAdapter):
    vendor = "anthropic"

    async def complete(self, *, system: str, user: str) -> str:
        key = self.resolve_key()
        data = await self._post(
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            {
                "model": self.model_name,
                "max_tokens": 4096,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        try:
            blocks = data["content"]
        except (KeyError, TypeError) as exc:
            raise ModelError(self.model_id, "unreadable response") from exc
        parts = []
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
        text = "".join(parts).strip()
        if not text:
            raise ModelError(self.model_id, "empty response")
        return text


class GoogleAdapter(_HTTPAdapter):
    vendor = "google"

    async def complete(self, *, system: str, user: str) -> str:
        key = self.resolve_key()
        model = quote(self.model_name, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        data = await self._post(
            url,
            {"x-goog-api-key": key},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                },
            },
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(self.model_id, "unreadable response") from exc
        text = "".join(
            str(part.get("text", "")) for part in parts if isinstance(part, dict)
        ).strip()
        if not text:
            raise ModelError(self.model_id, "empty response")
        return text


_BUILDERS = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "google": GoogleAdapter,
}


def build_adapters(panel: Panel) -> list:
    return [_BUILDERS[spec.vendor](spec.model_id) for spec in panel.models]
