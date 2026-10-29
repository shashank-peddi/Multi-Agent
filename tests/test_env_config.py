import asyncio
import json
from pathlib import Path

import pytest

from deliberation.adapters import (
    AnthropicAdapter,
    GoogleAdapter,
    ModelError,
    OpenAIAdapter,
)
from deliberation.panel import REQUIREMENT_ERROR, load_panel


KEY_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "PANEL_MODELS",
)


class FakeHTTP:
    def __init__(self, *args, **kwargs):
        FakeHTTP.timeouts.append(kwargs.get("timeout"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        FakeHTTP.posts.append({"url": url, "headers": dict(headers or {}), "json": json})
        if "openai.com" in url:
            body = {"choices": [{"message": {"content": "openai-body"}}]}
        elif "anthropic.com" in url:
            body = {"content": [{"type": "text", "text": "anthropic-body"}]}
        elif "googleapis.com" in url:
            body = {"candidates": [{"content": {"parts": [{"text": "google-body"}]}}]}
        else:
            raise AssertionError(url)
        return FakeResponse(body)


class FakeResponse:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


@pytest.fixture(autouse=True)
def clear_keys(monkeypatch):
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    FakeHTTP.timeouts = []
    FakeHTTP.posts = []
    monkeypatch.setattr("deliberation.adapters.httpx.AsyncClient", FakeHTTP)


def test_requirements_name_the_stack_and_do_not_load_dotenv():
    text = Path("requirements.txt").read_text().lower()
    for name in ("fastapi", "uvicorn", "langgraph"):
        assert name in text
    source = "\n".join(
        Path(path).read_text()
        for path in (
            "app.py",
            "deliberation/panel.py",
            "deliberation/adapters.py",
            "deliberation/graph.py",
            "deliberation/compose.py",
        )
    )
    assert "dotenv" not in source
    assert "load_dotenv" not in source
    assert "dotenv" not in text


def test_panel_and_keys_come_from_the_environment_not_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "PANEL_MODELS=openai/from-file,anthropic/from-file,google/from-file\n"
        "OPENAI_API_KEY=file-key-should-not-load\n"
        "ANTHROPIC_API_KEY=file-key-should-not-load\n"
        "GOOGLE_API_KEY=file-key-should-not-load\n"
    )
    monkeypatch.setenv("PANEL_MODELS", "openai/from-process")
    panel = load_panel(
        environ={
            "PANEL_MODELS": "openai/gpt-a,anthropic/claude-b,google/gemini-c",
            "OPENAI_API_KEY": "env-only-secret",
        }
    )
    assert panel.meets_rule is True
    assert [model.model_id for model in panel.models] == [
        "openai/gpt-a",
        "anthropic/claude-b",
        "google/gemini-c",
    ]
    assert panel.models[0].credential_present is True
    assert panel.models[1].credential_present is False
    assert panel.models[2].credential_present is False
    assert "from-file" not in panel.raw

    monkeypatch.setenv(
        "PANEL_MODELS",
        "openai/gpt-a,anthropic/claude-b,google/gemini-c",
    )
    from_process = load_panel()
    assert from_process.meets_rule is True
    assert all(model.credential_present is False for model in from_process.models)


def test_small_and_single_vendor_panels_do_not_meet_the_rule():
    two = load_panel(environ={"PANEL_MODELS": "openai/a,anthropic/b"})
    assert two.meets_rule is False
    assert len(two.models) == 2
    assert REQUIREMENT_ERROR in two.refusal_message()

    one_vendor = load_panel(environ={"PANEL_MODELS": "openai/a,openai/b,openai/c"})
    assert one_vendor.meets_rule is False
    assert len(one_vendor.models) == 3
    assert len(one_vendor.vendors) == 1

    two_vendors = load_panel(
        environ={"PANEL_MODELS": "openai/a,openai/b,anthropic/c"}
    )
    assert two_vendors.meets_rule is True
    assert len(two_vendors.models) == 3
    assert len(two_vendors.vendors) == 2

    broken = load_panel(
        environ={"PANEL_MODELS": "openai/a,anthropic/b,google/c,notavalid"}
    )
    assert broken.meets_rule is False
    assert len(broken.models) == 3
    assert any("notavalid" in error for error in broken.parse_errors)


def test_api_keys_are_read_from_the_environment_at_call_time(monkeypatch):
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-alpha-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-value")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-primary-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secondary-secret")

    async def call_all():
        openai = OpenAIAdapter("openai/gpt-test")
        anthropic = AnthropicAdapter("anthropic/claude-test")
        google = GoogleAdapter("google/gemini-test")
        first = await openai.complete(system="system", user="question")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-beta-value")
        second = await openai.complete(system="system", user="question")
        anthropic_text = await anthropic.complete(system="system", user="question")
        google_text = await google.complete(system="system", user="question")
        monkeypatch.delenv("GOOGLE_API_KEY")
        gemini_text = await google.complete(system="system", user="question")
        return first, second, anthropic_text, google_text, gemini_text

    first, second, anthropic_text, google_text, gemini_text = asyncio.run(call_all())
    assert (first, second, anthropic_text, google_text, gemini_text) == (
        "openai-body",
        "openai-body",
        "anthropic-body",
        "google-body",
        "google-body",
    )
    assert FakeHTTP.timeouts == [12.5, 12.5, 12.5, 12.5, 12.5]
    headers = [post["headers"] for post in FakeHTTP.posts]
    assert headers[0]["Authorization"] == "Bearer sk-env-alpha-value"
    assert headers[1]["Authorization"] == "Bearer sk-env-beta-value"
    assert headers[2]["x-api-key"] == "sk-ant-env-value"
    assert headers[3]["x-goog-api-key"] == "google-primary-secret"
    assert headers[4]["x-goog-api-key"] == "gemini-secondary-secret"
    for post in FakeHTTP.posts:
        encoded = json.dumps(post["json"])
        assert "sk-env-alpha-value" not in encoded
        assert "sk-env-beta-value" not in encoded
        assert "sk-ant-env-value" not in encoded
        assert "google-primary-secret" not in encoded
        assert "gemini-secondary-secret" not in encoded
        assert "key=" not in post["url"]


def test_missing_key_does_not_call_the_client():
    adapter = OpenAIAdapter("openai/gpt-test")
    with pytest.raises(ModelError, match="OPENAI_API_KEY is not set"):
        asyncio.run(adapter.complete(system="system", user="question"))
    assert FakeHTTP.posts == []
