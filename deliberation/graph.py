"""Three fixed rounds, then compose. No conditional edge selects a draft."""

from __future__ import annotations

import asyncio
import re

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from deliberation.compose import RULE, compose
from deliberation.prompts import SYSTEM, round1_user, round2_user, round3_user
from deliberation.schemas import Concession, HeldClaim, Stance
from deliberation.transcript import FAILURE_MESSAGE, render_transcript
from deliberation.validate import extract_json, validate_round1, validate_round2, validate_round3


class State(TypedDict, total=False):
    question: str
    panel: list[str]
    round1: dict
    round2: dict
    round3: dict
    failures: list
    client_answer: str | None
    decision_record: dict
    transcript: str


def build_graph(adapters: list):
    by_id = [adapter.model_id for adapter in adapters]

    async def round_1(state: State) -> dict:
        if state.get("failures"):
            return {}
        payloads, errors = await _call_models(
            adapters,
            lambda adapter: round1_user(state["question"]),
            lambda adapter, data: validate_round1(data),
        )
        return {
            "round1": payloads,
            "failures": _failures(state, "round 1", errors),
        }

    async def round_2(state: State) -> dict:
        if state.get("failures") or not _ready(state, "round1"):
            extra = []
            if not state.get("failures") and not _ready(state, "round1"):
                extra = [_incomplete("round 2")]
            return {"failures": _failures(state, "round 2", extra)} if extra else {}

        def user_for(adapter):
            own = state["round1"][adapter.model_id]
            return round2_user(
                state["question"],
                adapter.model_id,
                own["position"],
                own["claims"],
                _foreign_claims(state, adapter.model_id),
            )

        def validate_for(adapter, data):
            return validate_round2(data, adapter.model_id, _foreign_claims(state, adapter.model_id))

        payloads, errors = await _call_models(adapters, user_for, validate_for)
        return {
            "round2": payloads,
            "failures": _failures(state, "round 2", errors),
        }

    async def round_3(state: State) -> dict:
        if state.get("failures") or not _ready(state, "round2"):
            extra = []
            if not state.get("failures") and not _ready(state, "round2"):
                extra = [_incomplete("round 3")]
            return {"failures": _failures(state, "round 3", extra)} if extra else {}

        def user_for(adapter):
            own = state["round1"][adapter.model_id]
            return round3_user(
                state["question"],
                adapter.model_id,
                own["position"],
                own["claims"],
                _critiques(state, adapter.model_id),
                _foreign_claims(state, adapter.model_id),
            )

        def validate_for(adapter, data):
            return validate_round3(
                data,
                adapter.model_id,
                state["round1"][adapter.model_id]["claims"],
                _foreign_claims(state, adapter.model_id),
            )

        payloads, errors = await _call_models(adapters, user_for, validate_for)
        return {
            "round3": payloads,
            "failures": _failures(state, "round 3", errors),
        }

    def compose_node(state: State) -> dict:
        failures = list(state.get("failures") or [])
        complete = _ready(state, "round1") and _ready(state, "round2") and _ready(state, "round3")
        if failures or not complete:
            if not failures:
                failures = [_incomplete("compose")]
            answer = None
            record = failure_record(state.get("panel") or by_id, failures)
        else:
            held, stances, concessions = project_inputs(
                state["panel"], state["round2"], state["round3"]
            )
            answer, record = compose(state["panel"], held, stances, concessions)
        transcript = render_transcript(state, answer, record)
        return {
            "client_answer": answer,
            "decision_record": record,
            "transcript": transcript,
        }

    graph = StateGraph(State)
    graph.add_node("round_1", round_1)
    graph.add_node("round_2", round_2)
    graph.add_node("round_3", round_3)
    graph.add_node("compose", compose_node)
    graph.add_edge(START, "round_1")
    graph.add_edge("round_1", "round_2")
    graph.add_edge("round_2", "round_3")
    graph.add_edge("round_3", "compose")
    graph.add_edge("compose", END)
    return graph.compile()


async def run_deliberation(question: str, adapters: list) -> dict:
    graph = build_graph(adapters)
    return await graph.ainvoke(
        {
            "question": question,
            "panel": [adapter.model_id for adapter in adapters],
            "round1": {},
            "round2": {},
            "round3": {},
            "failures": [],
        }
    )


def project_inputs(panel: list[str], round2: dict, round3: dict):
    held: list[HeldClaim] = []
    concessions: list[Concession] = []
    for author in panel:
        revision = round3[author]
        for claim in revision["claims"]:
            held.append(
                HeldClaim(
                    author=author,
                    claim_id=claim["id"],
                    sentence=claim["sentence"],
                    claim_type=claim["type"],
                )
            )
        for item in revision["concessions"]:
            concessions.append(
                Concession(reviewer=author, author=item["author"], claim_id=item["claim_id"])
            )
    stances: list[Stance] = []
    for reviewer in panel:
        for item in round2[reviewer]["responses"]:
            stances.append(
                Stance(
                    reviewer=reviewer,
                    author=item["author"],
                    claim_id=item["claim_id"],
                    stance=item["stance"],
                    reason=item["reason"],
                )
            )
    return held, stances, concessions


def failure_record(panel: list[str], failures: list[dict]) -> dict:
    return {
        "failure": True,
        "message": FAILURE_MESSAGE,
        "panel": list(panel),
        "claims": [],
        "failures": failures,
        "rule": RULE,
    }


def _ready(state: State, key: str) -> bool:
    payloads = state.get(key) or {}
    return all(model_id in payloads for model_id in state.get("panel") or [])


def _failures(state: State, round_name: str, errors: list) -> list:
    failures = list(state.get("failures") or [])
    for item in errors:
        if isinstance(item, dict) and "round" in item and "model" in item:
            failures.append(item)
        else:
            model_id, error = item
            failures.append({"model": model_id, "round": round_name, "error": error})
    return failures


def _incomplete(round_name: str) -> dict:
    return {
        "model": "panel",
        "round": round_name,
        "error": "the previous round did not record every model",
    }


def _foreign_claims(state: State, model_id: str) -> list[dict]:
    claims = []
    for other in state["panel"]:
        if other == model_id:
            continue
        for claim in state["round1"][other]["claims"]:
            claims.append(
                {
                    "author": other,
                    "id": claim["id"],
                    "sentence": claim["sentence"],
                    "type": claim["type"],
                }
            )
    return claims


def _critiques(state: State, model_id: str) -> list[dict]:
    rows = []
    for reviewer in state["panel"]:
        if reviewer == model_id:
            continue
        for item in state["round2"][reviewer]["responses"]:
            if item["author"] != model_id:
                continue
            rows.append(
                {
                    "reviewer": reviewer,
                    "claim_id": item["claim_id"],
                    "stance": item["stance"],
                    "reason": item["reason"],
                }
            )
    return rows


async def _call_models(adapters: list, user_for, validate_for):
    async def one(adapter):
        user = user_for(adapter)
        prompt = user
        last_error = "no response"
        for _attempt in range(2):
            try:
                raw = await adapter.complete(system=SYSTEM, user=prompt)
            except Exception as exc:
                last_error = _clean_error(exc)
                prompt = (
                    user
                    + "\n\nYour previous response failed: "
                    + last_error
                    + "\nReturn only the JSON object."
                )
                continue
            try:
                return adapter.model_id, validate_for(adapter, extract_json(raw)), None
            except ValueError as exc:
                last_error = str(exc)
                prompt = (
                    user
                    + "\n\nYour previous response failed validation: "
                    + last_error
                    + "\nReturn only the JSON object."
                )
        return adapter.model_id, None, last_error

    results = await asyncio.gather(*[one(adapter) for adapter in adapters])
    payloads = {}
    errors = []
    for model_id, payload, error in results:
        if error:
            errors.append((model_id, error))
        else:
            payloads[model_id] = payload
    return payloads, errors


def _clean_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[redacted]", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", text)
    text = re.sub(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*)\S+", r"\1[redacted]", text)
    return text[:500]
