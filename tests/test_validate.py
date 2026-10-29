import pytest

from deliberation.validate import validate_round1, validate_round2, validate_round3


def test_round1_rejects_too_few_claims():
    with pytest.raises(ValueError, match="3 to 7"):
        validate_round1(
            {
                "position": "Ask for the unfinished inventory count before answering the lender.",
                "claims": [
                    {
                        "id": "c1",
                        "sentence": "Do not state that the controls are effective.",
                        "type": "recommendation",
                    },
                    {
                        "id": "c2",
                        "sentence": "The inventory count is unfinished.",
                        "type": "reason",
                    },
                ],
            }
        )


def test_blanket_agreement_is_not_engagement():
    foreign = [
        {
            "author": "bravo",
            "id": "c1",
            "sentence": "The inventory count is unfinished.",
            "type": "risk",
        }
    ]
    with pytest.raises(ValueError, match="named claim"):
        validate_round2(
            {
                "responses": [
                    {
                        "claim_id": "c1",
                        "author": "bravo",
                        "stance": "concede",
                        "reason": "I agree with the others.",
                    }
                ]
            },
            "alpha",
            foreign,
        )


def test_empty_reason_is_invalid():
    foreign = [
        {
            "author": "bravo",
            "id": "c1",
            "sentence": "The inventory count is unfinished.",
            "type": "risk",
        }
    ]
    with pytest.raises(ValueError, match="empty"):
        validate_round2(
            {
                "responses": [
                    {
                        "claim_id": "c1",
                        "author": "bravo",
                        "stance": "rebut",
                        "reason": "   ",
                    }
                ]
            },
            "alpha",
            foreign,
        )


def test_round3_must_account_for_every_claim():
    own = [
        {"id": "c1", "sentence": "Do not state that the controls are effective.", "type": "recommendation"},
        {"id": "c2", "sentence": "The inventory count is unfinished.", "type": "reason"},
        {"id": "c3", "sentence": "Ask for the open count items before replying.", "type": "would_change"},
    ]
    foreign = [
        {"author": "bravo", "id": "c1", "sentence": "Name the open items.", "type": "recommendation"}
    ]
    with pytest.raises(ValueError, match="missing"):
        validate_round3(
            {
                "position": "The partner should ask for the count before answering.",
                "claims": [
                    {
                        "id": "c1",
                        "sentence": "Do not state that the controls are effective.",
                        "type": "recommendation",
                        "changed": False,
                        "caused_by_critic": None,
                        "caused_by_claim_id": None,
                    }
                ],
                "withdrawn": [],
                "concessions": [],
            },
            "alpha",
            own,
            foreign,
        )
