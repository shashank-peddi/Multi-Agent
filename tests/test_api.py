from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from deliberation.question import HARD_QUESTION
from tests.fakes import make_adapters
from tests.support import sections


PANEL = "openai/gpt-test,anthropic/claude-test,google/gemini-test"
OPENAI_SENTINEL = "sk-openai-route-sentinel"
ANTHROPIC_SENTINEL = "sk-anthropic-route-sentinel"
GOOGLE_SENTINEL = "google-route-sentinel"


class CountingClient:
    calls = 0

    def __init__(self, *args, **kwargs):
        CountingClient.calls += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        CountingClient.calls += 1
        raise AssertionError("model client called")


def _configure(monkeypatch, panel=PANEL):
    monkeypatch.setenv("PANEL_MODELS", panel)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_SENTINEL)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_SENTINEL)
    monkeypatch.setenv("GOOGLE_API_KEY", GOOGLE_SENTINEL)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_health_reports_the_panel_and_does_not_call_a_model(monkeypatch):
    _configure(monkeypatch)
    CountingClient.calls = 0
    monkeypatch.setattr("deliberation.adapters.httpx.AsyncClient", CountingClient)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["panel_size"] == 3
    assert body["vendor_count"] == 3
    assert body["meets_rule"] is True
    assert body["models"] == [
        "openai/gpt-test",
        "anthropic/claude-test",
        "google/gemini-test",
    ]
    assert body["credentials_present"]["openai/gpt-test"] is True
    assert OPENAI_SENTINEL not in response.text
    assert ANTHROPIC_SENTINEL not in response.text
    assert GOOGLE_SENTINEL not in response.text
    assert CountingClient.calls == 0


def test_unconfigured_panel_is_reported_and_refuses_to_answer(monkeypatch):
    monkeypatch.delenv("PANEL_MODELS", raising=False)
    with TestClient(app) as client:
        health = client.get("/health")
        refused = client.post("/answer", json={"question": "What should the partner say?"})
    assert health.status_code == 200
    assert health.json()["panel_size"] == 0
    assert health.json()["vendor_count"] == 0
    assert health.json()["meets_rule"] is False
    assert refused.status_code == 503
    detail = refused.json()["detail"]
    assert detail["error"] == (
        "The configured panel must include at least three models from at least two vendors. "
        "Refusing to serve."
    )
    assert detail["meets_rule"] is False


def test_malformed_panel_is_not_quietly_trimmed(monkeypatch):
    _configure(monkeypatch, panel=f"{PANEL},notavalid")
    CountingClient.calls = 0
    monkeypatch.setattr("deliberation.adapters.httpx.AsyncClient", CountingClient)

    def forbid(*args, **kwargs):
        raise AssertionError("graph ran")

    monkeypatch.setattr("app.run_deliberation", forbid)
    with TestClient(app) as client:
        response = client.post("/answer", json={"question": "What should the partner say?"})
    assert response.status_code == 503
    assert "notavalid" in response.text
    assert "at least three models" in response.text
    assert "at least two vendors" in response.text
    assert CountingClient.calls == 0
    assert OPENAI_SENTINEL not in response.text


def test_answer_uses_the_posted_question_and_hides_keys(monkeypatch, tmp_path):
    _configure(monkeypatch)
    monkeypatch.setenv("TRANSCRIPT_DIR", str(tmp_path))
    adapters = make_adapters()
    adapters[0].rounds["1"]["position"] = (
        f"{OPENAI_SENTINEL} is not advice. The partner should ask for the unfinished count before speaking."
    )
    monkeypatch.setattr("app.build_adapters", lambda panel: adapters)
    question = "What should the partner say about the unfinished inventory count?"
    with TestClient(app) as client:
        response = client.post("/answer", json={"question": question})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision_record"]["failure"] is False, body["decision_record"]
    assert "transcript_path" not in body
    assert list(tmp_path.iterdir()) == []
    assert sections(body["client_answer"])["Advice"] == (
        "openai/gpt-test `c1`: Do not state that the controls are effective."
    )
    assert OPENAI_SENTINEL not in response.text
    assert ANTHROPIC_SENTINEL not in response.text
    assert GOOGLE_SENTINEL not in response.text
    assert "[redacted]" in body["transcript"]
    assert question in adapters[0].calls[0]["user"]
    assert HARD_QUESTION not in adapters[0].calls[0]["user"]
    assert sum(len(adapter.calls) for adapter in adapters) == 9


def test_hard_question_route_writes_the_transcript(monkeypatch, tmp_path):
    _configure(monkeypatch)
    monkeypatch.setenv("TRANSCRIPT_DIR", str(tmp_path))
    adapters = make_adapters()
    monkeypatch.setattr("app.build_adapters", lambda panel: adapters)
    with TestClient(app) as client:
        response = client.post(
            "/answer/hard-01",
            json={"question": "What is two plus two?"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    path = Path(body["transcript_path"])
    assert path.name == "hard-01.md"
    assert path.resolve().parent == tmp_path.resolve()
    written = path.read_text(encoding="utf-8")
    assert written == body["transcript"]
    assert HARD_QUESTION in written
    assert "What is two plus two?" not in written
    assert "## Round 1 — alone" in written
    assert "## Round 2 — cross-examination" in written
    assert "## Round 3 — revise own answer" in written
    assert "## Decision record" in written
    assert "## Client answer" in written
    assert "No model writes the final answer." in written
    assert body["client_answer"] in written
    assert "What is two plus two?" not in adapters[0].calls[0]["user"]
    assert HARD_QUESTION in adapters[0].calls[0]["user"]
    assert OPENAI_SENTINEL not in response.text
    assert ANTHROPIC_SENTINEL not in response.text
    assert GOOGLE_SENTINEL not in response.text
    assert not Path("transcripts/hard-01.md").exists()


def test_blank_question_is_rejected(monkeypatch):
    _configure(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/answer", json={"question": "   "})
    assert response.status_code == 422


def test_hard_question_text_is_unchanged():
    assert HARD_QUESTION == (
        "A private company wants a comfort letter that its lender can rely on, "
        "three weeks before year-end. Inventory count procedures are incomplete. "
        "Management wants the letter to say the controls are effective. "
        "You advise the engagement partner. What can we say, what must we not say, "
        "and what should we ask for before we answer? Give the advice you would give the partner."
    )
