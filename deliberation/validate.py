"""Schema checks for the three rounds. These checks do not call a model."""

from __future__ import annotations

import json
import re

from deliberation.schemas import CLAIM_TYPES, STANCES


_BLANKET = {
    "i agree",
    "i agree with the others",
    "i agree with the other models",
    "i agree with the other",
    "agreed",
    "concede",
    "conceded",
    "yes",
    "ok",
    "okay",
}


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def sentence_count(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    pieces = [piece for piece in re.split(r"[.!?]+(?:\s+|$)", cleaned) if piece.strip()]
    return len(pieces)


def extract_json(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("response was not a JSON object")
        try:
            value = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("response was not a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("response was not a JSON object")
    return value


def _one_line(text: str, label: str) -> str:
    if not isinstance(text, str):
        raise ValueError(f"{label} must be a string")
    cleaned = text.strip()
    if not cleaned:
        raise ValueError(f"{label} is empty")
    if "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} must be one line")
    return cleaned


def _words_between(text: str, low: int, high: int, label: str) -> None:
    count = word_count(text)
    if count < low or count > high:
        raise ValueError(f"{label} must be {low} to {high} words, not {count}")


def _claim_id(value, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"c[1-9][0-9]*", value):
        raise ValueError(f"{label} must be an id such as c1")
    return value


def _claim_type(value) -> str:
    if not isinstance(value, str):
        raise ValueError("claim type must be a string")
    lowered = value.strip().lower()
    if lowered not in CLAIM_TYPES:
        allowed = ", ".join(CLAIM_TYPES)
        raise ValueError(f"claim type must be one of: {allowed}")
    return lowered


def _reason(text: str, label: str) -> str:
    cleaned = _one_line(text, label)
    _words_between(cleaned, 3, 80, label)
    count = sentence_count(cleaned)
    if count < 1 or count > 2:
        raise ValueError(f"{label} must be one or two sentences")
    norm = re.sub(r"\s+", " ", cleaned.lower()).rstrip(".! ")
    if norm in _BLANKET:
        raise ValueError(f"{label} must address the named claim")
    return cleaned


def _position(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("position must be a string")
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("position is empty")
    _words_between(cleaned, 1, 180, "position")
    return cleaned


def _claim_sentence(text: str) -> str:
    cleaned = _one_line(text, "claim sentence")
    _words_between(cleaned, 1, 40, "claim sentence")
    return cleaned


def validate_round1(data: dict) -> dict:
    position = _position(data.get("position"))
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    if not 3 <= len(claims) <= 7:
        raise ValueError("claims must contain 3 to 7 items")
    normalized = []
    seen: set[str] = set()
    for index, item in enumerate(claims, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"claim {index} must be an object")
        claim_id = _claim_id(item.get("id"), f"claim {index} id")
        if claim_id in seen:
            raise ValueError(f"duplicate claim id {claim_id}")
        seen.add(claim_id)
        normalized.append(
            {
                "id": claim_id,
                "sentence": _claim_sentence(item.get("sentence")),
                "type": _claim_type(item.get("type")),
            }
        )
    return {"position": position, "claims": normalized}


def validate_round2(data: dict, reviewer: str, foreign_claims: list[dict]) -> dict:
    responses = data.get("responses")
    if not isinstance(responses, list):
        raise ValueError("responses must be a list")
    expected = {(claim["author"], claim["id"]) for claim in foreign_claims}
    found: dict[tuple[str, str], dict] = {}
    for index, item in enumerate(responses, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"response {index} must be an object")
        author = item.get("author")
        if not isinstance(author, str) or not author.strip():
            raise ValueError(f"response {index} is missing the author")
        author = author.strip()
        claim_id = _claim_id(item.get("claim_id"), f"response {index} claim_id")
        stance = item.get("stance")
        if not isinstance(stance, str):
            raise ValueError(f"response {index} is missing a stance")
        stance = stance.strip().lower()
        if stance not in STANCES:
            raise ValueError(f"response {index} stance must be concede, rebut, or clarify")
        reason = _reason(item.get("reason"), f"response {index} reason")
        key = (author, claim_id)
        if key in found:
            raise ValueError(f"duplicate response for {author} {claim_id}")
        if key not in expected:
            raise ValueError(f"unexpected claim {author} {claim_id}")
        found[key] = {
            "claim_id": claim_id,
            "author": author,
            "stance": stance,
            "reason": reason,
        }
    missing = expected - set(found)
    if missing:
        shown = ", ".join(f"{author} {claim_id}" for author, claim_id in sorted(missing))
        raise ValueError(f"missing stances for: {shown}")
    ordered = [found[(claim["author"], claim["id"])] for claim in foreign_claims]
    return {"responses": ordered}


def validate_round3(
    data: dict,
    author: str,
    own_claims: list[dict],
    foreign_claims: list[dict],
) -> dict:
    position = _position(data.get("position"))
    own_by_id = {claim["id"]: claim for claim in own_claims}
    foreign_keys = {(claim["author"], claim["id"]) for claim in foreign_claims}
    claims = data.get("claims")
    withdrawn = data.get("withdrawn", [])
    concessions = data.get("concessions", [])
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    if not isinstance(withdrawn, list):
        raise ValueError("withdrawn must be a list")
    if not isinstance(concessions, list):
        raise ValueError("concessions must be a list")

    kept = []
    kept_ids: set[str] = set()
    for index, item in enumerate(claims, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"claim {index} must be an object")
        claim_id = _claim_id(item.get("id"), f"claim {index} id")
        if claim_id not in own_by_id:
            raise ValueError(f"claim {claim_id} was not in this model's round 1")
        if claim_id in kept_ids:
            raise ValueError(f"duplicate claim id {claim_id}")
        kept_ids.add(claim_id)
        sentence = _claim_sentence(item.get("sentence"))
        claim_type = _claim_type(item.get("type"))
        original = own_by_id[claim_id]
        text_changed = sentence != original["sentence"] or claim_type != original["type"]
        if "changed" not in item:
            changed = text_changed
        else:
            if not isinstance(item.get("changed"), bool):
                raise ValueError(f"claim {claim_id} changed must be true or false")
            changed = item["changed"]
        critic = item.get("caused_by_critic")
        cause_id = item.get("caused_by_claim_id")
        if text_changed and not changed:
            raise ValueError(
                f"claim {claim_id} differs from round 1, so changed must be true and a cause is required"
            )
        if changed:
            critic, cause_id = _cause(critic, cause_id, author, foreign_keys, claim_id)
        elif critic or cause_id:
            raise ValueError(f"unchanged claim {claim_id} cannot name a cause")
        else:
            critic, cause_id = None, None
        kept.append(
            {
                "id": claim_id,
                "sentence": sentence,
                "type": claim_type,
                "changed": changed,
                "caused_by_critic": critic,
                "caused_by_claim_id": cause_id,
            }
        )

    dropped = []
    dropped_ids: set[str] = set()
    for index, item in enumerate(withdrawn, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"withdrawn item {index} must be an object")
        claim_id = _claim_id(item.get("id"), f"withdrawn item {index} id")
        if claim_id not in own_by_id:
            raise ValueError(f"withdrawn claim {claim_id} was not in this model's round 1")
        if claim_id in dropped_ids or claim_id in kept_ids:
            raise ValueError(f"claim {claim_id} appears more than once in the revision")
        dropped_ids.add(claim_id)
        critic, cause_id = _cause(
            item.get("caused_by_critic"),
            item.get("caused_by_claim_id"),
            author,
            foreign_keys,
            claim_id,
        )
        dropped.append(
            {
                "id": claim_id,
                "caused_by_critic": critic,
                "caused_by_claim_id": cause_id,
            }
        )

    missing = set(own_by_id) - kept_ids - dropped_ids
    if missing:
        shown = ", ".join(sorted(missing))
        raise ValueError(f"every round-1 claim must be kept or withdrawn; missing {shown}")

    kept.sort(key=lambda item: int(item["id"][1:]))
    dropped.sort(key=lambda item: int(item["id"][1:]))

    conceded = []
    seen_concessions: set[tuple[str, str]] = set()
    for index, item in enumerate(concessions, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"concession {index} must be an object")
        other = item.get("author")
        if not isinstance(other, str) or not other.strip():
            raise ValueError(f"concession {index} is missing the author")
        other = other.strip()
        claim_id = _claim_id(item.get("claim_id"), f"concession {index} claim_id")
        if other == author:
            raise ValueError("cannot concede your own claim")
        if (other, claim_id) not in foreign_keys:
            raise ValueError(f"concession {other} {claim_id} is not a foreign claim")
        if (other, claim_id) in seen_concessions:
            continue
        seen_concessions.add((other, claim_id))
        conceded.append({"author": other, "claim_id": claim_id})

    return {
        "position": position,
        "claims": kept,
        "withdrawn": dropped,
        "concessions": conceded,
    }


def _cause(critic, cause_id, author: str, foreign_keys: set[tuple[str, str]], claim_id: str):
    if not isinstance(critic, str) or not critic.strip():
        raise ValueError(f"claim {claim_id} must name the critic model id")
    critic = critic.strip()
    if critic == author:
        raise ValueError(f"claim {claim_id} must name another model as the critic")
    cause = _claim_id(cause_id, f"claim {claim_id} caused_by_claim_id")
    if (critic, cause) not in foreign_keys:
        raise ValueError(
            f"claim {claim_id} cause {critic} {cause} is not one of that critic's claims"
        )
    return critic, cause
