"""Deliberation API.

Serve with:

    uvicorn app:app

Configuration is read only from the environment:

    PANEL_MODELS=openai/<model>,anthropic/<model>,google/<model>
    OPENAI_API_KEY
    ANTHROPIC_API_KEY
    GOOGLE_API_KEY or GEMINI_API_KEY
    TRANSCRIPT_DIR            optional, default transcripts
    MODEL_TIMEOUT_SECONDS     optional, default 120
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from deliberation.adapters import build_adapters
from deliberation.graph import run_deliberation
from deliberation.panel import REQUIREMENT_ERROR, load_panel
from deliberation.question import HARD_QUESTION
from deliberation.redact import configured_secrets, redact_text, redact_value
from deliberation.transcript import write_transcript


logger = logging.getLogger("deliberation")


@asynccontextmanager
async def lifespan(app: FastAPI):
    panel = load_panel()
    if not panel.meets_rule:
        logger.error("%s", redact_text(panel.refusal_message(), configured_secrets()))
    yield


app = FastAPI(title="Panel deliberation", lifespan=lifespan)


class QuestionIn(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def question_is_present(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("question is required")
        return text


@app.get("/health")
def health():
    panel = load_panel()
    return redact_value(panel.health(), configured_secrets())


@app.post("/answer")
async def answer(body: QuestionIn):
    return await run_question(body.question, write_name=None)


@app.post("/answer/hard-01")
async def answer_hard():
    return await run_question(HARD_QUESTION, write_name="hard-01.md")


async def run_question(question: str, *, write_name: str | None) -> dict:
    panel = load_panel()
    if not panel.meets_rule:
        detail = redact_value(_refusal_payload(panel), configured_secrets())
        raise HTTPException(status_code=503, detail=detail)
    result = await run_deliberation(question, build_adapters(panel))
    payload = {
        "client_answer": result.get("client_answer"),
        "decision_record": result.get("decision_record"),
        "transcript": result.get("transcript") or "",
    }
    payload = redact_value(payload, configured_secrets())
    if write_name:
        path = write_transcript(write_name, payload["transcript"])
        payload["transcript_path"] = str(path)
    return payload


def _refusal_payload(panel) -> dict:
    return {
        "error": REQUIREMENT_ERROR,
        "panel_size": len(panel.models),
        "vendor_count": len(panel.vendors),
        "meets_rule": False,
        "reasons": panel.reason_list(),
    }
