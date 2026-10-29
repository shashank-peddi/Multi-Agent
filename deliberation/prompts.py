"""Prompts for the three fixed rounds. None of these asks a model to write the client answer."""

from __future__ import annotations

import json


SYSTEM = (
    "You are one advisor on a panel. "
    "Return one JSON object and no markdown. "
    "No model writes the final answer. "
    "Do not score other advisors, do not pick a winner, and do not merge their answers into client-facing text."
)


def round1_user(question: str) -> str:
    return (
        "This is round 1 of 3.\n"
        "You answer alone. You cannot see any other advisor.\n\n"
        "Question:\n"
        "<<<\n"
        f"{question.strip()}\n"
        ">>>\n\n"
        "Return JSON with this shape:\n"
        "{\n"
        '  "position": "<one paragraph, at most 180 words, the advice you would give and why>",\n'
        '  "claims": [\n'
        '    {"id": "c1", "sentence": "<one sentence, at most 40 words>", "type": "recommendation"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- claims has 3 to 7 items.\n"
        "- ids are c1, c2, c3, and so on, each used once.\n"
        "- type is one of: recommendation, reason, risk, would_change.\n"
        "- a recommendation says what the partner should do or should refuse to say.\n"
        "- a would_change claim says what new evidence would change the advice.\n"
        "- each claim sentence is one line of at most 40 words.\n"
        "- Do not write a client-facing answer. Do not refer to other advisors.\n"
    )


def round2_user(
    question: str,
    model_id: str,
    own_position: str,
    own_claims: list[dict],
    foreign_claims: list[dict],
) -> str:
    foreign = [
        {
            "author": claim["author"],
            "claim_id": claim["id"],
            "type": claim["type"],
            "sentence": claim["sentence"],
        }
        for claim in foreign_claims
    ]
    return (
        "This is round 2 of 3.\n"
        "Cross-examination. Do not return a replacement final answer.\n\n"
        f"You are {model_id}.\n\n"
        "Question:\n"
        "<<<\n"
        f"{question.strip()}\n"
        ">>>\n\n"
        "Your round-1 position:\n"
        f"{own_position}\n\n"
        "Your round-1 claims:\n"
        f"{_dump(own_claims)}\n\n"
        "Foreign claims you must answer, each by id. Copy author and claim_id exactly:\n"
        f"{_dump(foreign)}\n\n"
        "Return JSON:\n"
        '{"responses": [{"claim_id": "c1", "author": "<exact author>", '
        '"stance": "concede", "reason": "<one or two sentences that address that claim>"}]}\n\n'
        "Rules:\n"
        "- One response for every foreign claim above, and no extras.\n"
        "- stance is exactly concede, rebut, or clarify.\n"
        "- reason is required. One or two sentences. It must address the claim named by that id.\n"
        '- A blanket "I agree with the others," with no claim named, is invalid.\n'
        "- Do not return a position, a revised draft, or a merged client answer.\n"
    )


def round3_user(
    question: str,
    model_id: str,
    own_position: str,
    own_claims: list[dict],
    critiques: list[dict],
    foreign_claims: list[dict],
) -> str:
    foreign = [
        {
            "author": claim["author"],
            "claim_id": claim["id"],
            "type": claim["type"],
            "sentence": claim["sentence"],
        }
        for claim in foreign_claims
    ]
    return (
        "This is round 3 of 3.\n"
        "Revise your own answer only. Do not return a merged answer. "
        "Do not paste another model's paragraph into yours.\n\n"
        f"You are {model_id}.\n\n"
        "Question:\n"
        "<<<\n"
        f"{question.strip()}\n"
        ">>>\n\n"
        "Your round-1 position:\n"
        f"{own_position}\n\n"
        "Your round-1 claims:\n"
        f"{_dump(own_claims)}\n\n"
        "Critiques of your claims:\n"
        f"{_dump(critiques)}\n\n"
        "Foreign claims you may concede by id:\n"
        f"{_dump(foreign)}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "position": "<your own revised paragraph, at most 180 words>",\n'
        '  "claims": [\n'
        "    {\n"
        '      "id": "c1",\n'
        '      "sentence": "<one sentence, at most 40 words>",\n'
        '      "type": "recommendation",\n'
        '      "changed": false,\n'
        '      "caused_by_critic": null,\n'
        '      "caused_by_claim_id": null\n'
        "    }\n"
        "  ],\n"
        '  "withdrawn": [\n'
        '    {"id": "c2", "caused_by_critic": "<other model id>", "caused_by_claim_id": "c1"}\n'
        "  ],\n"
        '  "concessions": [{"author": "<other model id>", "claim_id": "c1"}]\n'
        "}\n\n"
        "Rules:\n"
        "- Every round-1 claim id appears once, either in claims or in withdrawn.\n"
        "- Do not add new claim ids.\n"
        "- If you change a sentence or a type, set changed to true and name the critic model id "
        "and that critic's claim id that caused the change.\n"
        "- If you withdraw a claim, name the critic and the critic's claim id that caused the withdrawal.\n"
        "- concessions may name only foreign claim ids. A concession is by id, not by similar wording.\n"
        "- If you now concede a claim you did not concede in round 2, list it in concessions.\n"
        "- Do not copy another model's position into yours.\n"
        "- Do not return a merged answer.\n"
    )


def _dump(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True)
