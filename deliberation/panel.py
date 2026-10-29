"""Panel configuration is read from the process environment and nowhere else."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


REQUIREMENT_ERROR = (
    "The configured panel must include at least three models from at least two vendors. "
    "Refusing to serve."
)

VENDORS = ("openai", "anthropic", "google")

VENDOR_KEY_ENVS = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}


@dataclass(frozen=True)
class ModelSpec:
    vendor: str
    model_name: str
    model_id: str
    credential_present: bool


@dataclass(frozen=True)
class Panel:
    raw: str
    models: tuple[ModelSpec, ...]
    parse_errors: tuple[str, ...]

    @property
    def vendors(self) -> set[str]:
        return {model.vendor for model in self.models}

    @property
    def meets_rule(self) -> bool:
        return (
            not self.parse_errors
            and len(self.models) >= 3
            and len(self.vendors) >= 2
        )

    def reason_list(self) -> list[str]:
        reasons: list[str] = []
        if not self.raw:
            reasons.append("PANEL_MODELS is not set.")
        else:
            reasons.append(
                "PANEL_MODELS currently lists "
                f"{len(self.models)} model(s) from {len(self.vendors)} vendor(s)."
            )
        if self.raw and len(self.models) < 3 and not self.parse_errors:
            reasons.append("At least three models are required.")
        if self.raw and len(self.vendors) < 2 and not self.parse_errors:
            reasons.append("At least two vendors are required.")
        reasons.extend(self.parse_errors)
        return reasons

    def refusal_message(self) -> str:
        hint = (
            "Set PANEL_MODELS to a comma-separated list of vendor/model ids "
            "using at least two of these vendors: openai, anthropic, google. "
            "Put API keys only in OPENAI_API_KEY, ANTHROPIC_API_KEY, and "
            "GOOGLE_API_KEY or GEMINI_API_KEY."
        )
        return " ".join([REQUIREMENT_ERROR, *self.reason_list(), hint])

    def health(self) -> dict:
        vendors = sorted(self.vendors)
        return {
            "panel_size": len(self.models),
            "vendor_count": len(vendors),
            "meets_rule": self.meets_rule,
            "models": [model.model_id for model in self.models],
            "vendors": vendors,
            "credentials_present": {
                model.model_id: model.credential_present for model in self.models
            },
            "error": None if self.meets_rule else self.refusal_message(),
        }


def lookup_key(environ: Mapping[str, str], vendor: str) -> tuple[str, str] | None:
    for name in VENDOR_KEY_ENVS[vendor]:
        value = environ.get(name, "")
        if isinstance(value, str) and value.strip():
            return name, value.strip()
    return None


def _show_token(token: str) -> str:
    if len(token) <= 80:
        return token
    return token[:80] + "..."


def load_panel(environ: Mapping[str, str] | None = None) -> Panel:
    env = os.environ if environ is None else environ
    raw = env.get("PANEL_MODELS", "")
    if not isinstance(raw, str):
        raw = ""
    raw = raw.strip()
    if not raw:
        return Panel(raw="", models=(), parse_errors=())

    models: list[ModelSpec] = []
    errors: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        vendor, separator, name = token.partition("/")
        vendor = vendor.strip().lower()
        name = name.strip()
        if not separator or vendor not in VENDOR_KEY_ENVS or not name or "/" in name:
            errors.append(
                f"Invalid panel entry {_show_token(token)!r}. Expected vendor/model."
            )
            continue
        model_id = f"{vendor}/{name}"
        if model_id in seen:
            errors.append(f"Duplicate model {model_id}.")
            continue
        seen.add(model_id)
        models.append(
            ModelSpec(
                vendor=vendor,
                model_name=name,
                model_id=model_id,
                credential_present=lookup_key(env, vendor) is not None,
            )
        )
    return Panel(raw=raw, models=tuple(models), parse_errors=tuple(errors))


def model_timeout_seconds(environ: Mapping[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    raw = env.get("MODEL_TIMEOUT_SECONDS", "120")
    if not isinstance(raw, str):
        return 120.0
    try:
        value = float(raw.strip())
    except ValueError:
        return 120.0
    if value <= 0:
        return 120.0
    return value


def transcript_directory(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = env.get("TRANSCRIPT_DIR", "transcripts")
    if not isinstance(raw, str) or not raw.strip():
        return "transcripts"
    return raw.strip()
