"""Assemble the client answer from the deliberation record.

No model writes the final answer.

A surviving claim is agreed when its author still holds that claim id and
every other model has conceded that same claim id. A surviving claim is
contested when its author still holds it and at least one other model
rebutted it without a later concession of that claim id. A surviving claim
is unchallenged when its author still holds it and nobody rebutted it, but
not every other model conceded it. Withdrawn claims are dropped.

Claims match only when a model concedes the other's claim by id, or when
the same model still holds its own claim id. This function does not compare
claim text. It performs no network call and imports no model client.
"""

from __future__ import annotations

from collections.abc import Sequence

from deliberation.schemas import Concession, HeldClaim, Stance


RULE = (
    "No model writes the final answer. "
    "A surviving claim is agreed when its author still holds that claim id and every other model has conceded that same claim id. "
    "A surviving claim is contested when its author still holds it and at least one other model rebutted it without a later concession of that claim id. "
    "A surviving claim is unchallenged when its author still holds it and nobody rebutted it, but not every other model conceded it. "
    "Withdrawn claims are dropped. "
    "Claims match only when a model concedes the other's claim by id, or when the same model still holds its own claim id. "
    "Claim text is not compared. "
    "Claim-id order is the numeric id, then the panel order of the author. "
    "Each agreed recommendation is written as the author, the claim id, and the sentence. "
    "If no recommendation is agreed, Advice is the fixed no-agreement sentence and nothing else. "
    "Contested claims keep the holder's sentence and each remaining rebuttal. "
    "Unchallenged claims stay labeled with the model that holds them and are not treated as agreement. "
    "Agreed would_change claims are listed under what would change the advice. "
    "A contested would_change claim stays under disagreements."
)

NO_AGREEMENT_SENTENCE = (
    "The models did not reach agreement on a recommendation. "
    "The disagreements below are the substance of the advice."
)

NOTHING_AGREED = "Nothing was agreed."
NONE = "None."


def _claim_number(claim_id: str) -> int:
    if not claim_id.startswith("c") or not claim_id[1:].isdigit():
        raise ValueError(f"claim id {claim_id!r} is not a claim id")
    return int(claim_id[1:])


def _sort_key(author: str, claim_id: str, panel_index: dict[str, int]) -> tuple:
    if author not in panel_index:
        raise ValueError(f"unknown author {author}")
    return (_claim_number(claim_id), panel_index[author], author, claim_id)


def compose(
    panel: Sequence[str],
    held_claims: Sequence[HeldClaim],
    stances: Sequence[Stance],
    concessions: Sequence[Concession] = (),
) -> tuple[str, dict]:
    """Return the client answer and the decision record. Same inputs, same output."""
    panel = list(panel)
    if len(panel) != len(set(panel)):
        raise ValueError("panel model ids must be unique")
    panel_index = {model_id: index for index, model_id in enumerate(panel)}

    seen_claims: set[tuple[str, str]] = set()
    for claim in held_claims:
        key = (claim.author, claim.claim_id)
        if key in seen_claims:
            raise ValueError(f"duplicate held claim {claim.author} {claim.claim_id}")
        seen_claims.add(key)
        if not claim.sentence.strip():
            raise ValueError(f"empty sentence for {claim.author} {claim.claim_id}")

    stance_index: dict[tuple[str, str, str], Stance] = {}
    for stance in stances:
        if stance.reviewer not in panel_index or stance.author not in panel_index:
            raise ValueError("stance names a model that is not on the panel")
        if stance.reviewer == stance.author:
            raise ValueError("a model cannot review its own claim")
        if stance.stance not in {"concede", "rebut", "clarify"}:
            raise ValueError(f"unknown stance {stance.stance!r}")
        if not stance.reason.strip():
            raise ValueError(
                f"empty reason from {stance.reviewer} on {stance.author} {stance.claim_id}"
            )
        key = (stance.reviewer, stance.author, stance.claim_id)
        if key in stance_index:
            raise ValueError(
                f"duplicate stance from {stance.reviewer} on {stance.author} {stance.claim_id}"
            )
        stance_index[key] = stance

    conceded: set[tuple[str, str, str]] = set()
    for concession in concessions:
        if concession.reviewer not in panel_index or concession.author not in panel_index:
            raise ValueError("concession names a model that is not on the panel")
        if concession.reviewer == concession.author:
            raise ValueError("a model cannot concede its own claim")
        conceded.add((concession.reviewer, concession.author, concession.claim_id))

    classified = []
    for claim in held_claims:
        others = [model_id for model_id in panel if model_id != claim.author]
        stance_rows = []
        for reviewer in others:
            stance = stance_index.get((reviewer, claim.author, claim.claim_id))
            if stance is None:
                raise ValueError(
                    f"missing stance from {reviewer} on {claim.author} {claim.claim_id}"
                )
            later = (reviewer, claim.author, claim.claim_id) in conceded
            effective = "concede" if later or stance.stance == "concede" else stance.stance
            stance_rows.append(
                {
                    "reviewer": reviewer,
                    "effective_stance": effective,
                    "round_2_stance": stance.stance,
                    "round_2_reason": stance.reason,
                    "round_3_conceded": later,
                }
            )
        effectives = [row["effective_stance"] for row in stance_rows]
        if effectives and all(item == "concede" for item in effectives):
            status = "agreed"
        elif any(item == "rebut" for item in effectives):
            status = "contested"
        else:
            status = "unchallenged"
        classified.append(
            {
                "author": claim.author,
                "claim_id": claim.claim_id,
                "sentence": claim.sentence,
                "type": claim.claim_type,
                "status": status,
                "stances": stance_rows,
            }
        )

    classified.sort(key=lambda row: _sort_key(row["author"], row["claim_id"], panel_index))
    record = {
        "failure": False,
        "message": None,
        "panel": panel,
        "claims": classified,
        "failures": [],
        "rule": RULE,
    }
    return _render(classified), record


def _render(claims: list[dict]) -> str:
    agreed = [claim for claim in claims if claim["status"] == "agreed"]
    contested = [claim for claim in claims if claim["status"] == "contested"]
    unchallenged = [claim for claim in claims if claim["status"] == "unchallenged"]
    agreed_recommendations = [claim for claim in agreed if claim["type"] == "recommendation"]
    agreed_changes = [claim for claim in agreed if claim["type"] == "would_change"]

    if agreed_recommendations:
        advice = "\n\n".join(
            f"{claim['author']} `{claim['claim_id']}`: {claim['sentence']}"
            for claim in agreed_recommendations
        )
    else:
        advice = NO_AGREEMENT_SENTENCE

    if agreed:
        agreed_body = "\n".join(_labeled(claim) for claim in agreed)
    else:
        agreed_body = NOTHING_AGREED

    if contested:
        blocks = []
        for claim in contested:
            lines = [
                f"### {claim['author']} holds `{claim['claim_id']}` ({claim['type']})",
                "",
                claim["sentence"],
                "",
            ]
            for stance in claim["stances"]:
                if stance["effective_stance"] == "rebut":
                    lines.append(
                        f"- Rebuttal by {stance['reviewer']}: {stance['round_2_reason']}"
                    )
            blocks.append("\n".join(lines).rstrip())
        disagreement_body = "\n\n".join(blocks)
    else:
        disagreement_body = NONE

    if unchallenged:
        unchallenged_body = "\n".join(_labeled(claim) for claim in unchallenged)
    else:
        unchallenged_body = NONE

    if agreed_changes:
        change_body = "\n".join(_labeled(claim) for claim in agreed_changes)
    else:
        change_body = NONE

    sections = [
        ("Advice", advice),
        ("Agreed", agreed_body),
        ("Disagreements", disagreement_body),
        ("Unchallenged, not treated as consensus", unchallenged_body),
        ("What would change the advice", change_body),
    ]
    rendered = "".join(f"## {title}\n\n{body}\n\n" for title, body in sections)
    return rendered.rstrip() + "\n"


def _labeled(claim: dict) -> str:
    return (
        f"- {claim['author']} `{claim['claim_id']}` ({claim['type']}): {claim['sentence']}"
    )
