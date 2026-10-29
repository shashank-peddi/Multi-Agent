"""Strip configured secrets from anything the API returns."""

from __future__ import annotations

import os
from collections.abc import Mapping

from deliberation.panel import VENDOR_KEY_ENVS


def configured_secrets(environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    secrets: list[str] = []
    for names in VENDOR_KEY_ENVS.values():
        for name in names:
            value = env.get(name, "")
            if isinstance(value, str) and len(value.strip()) >= 8:
                secret = value.strip()
                if secret not in secrets:
                    secrets.append(secret)
    return secrets


def redact_text(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text


def redact_value(value, secrets: list[str]):
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    return value
