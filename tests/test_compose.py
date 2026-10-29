import ast
from pathlib import Path

import httpx
import pytest

import deliberation.adapters as adapters
from deliberation.compose import NO_AGREEMENT_SENTENCE, RULE, compose
from deliberation.schemas import Concession, HeldClaim, Stance
from tests.support import headings, sections


PANEL = ["alpha", "bravo", "charlie"]

AGREED = "Do not state that the controls are effective."
CONTESTED = "Tell the lender it may rely on the letter."
UNTOUCHED = "Ask management to finish the inventory count before any letter is issued."
REBUTTAL = "A lender-reliance statement is not supported while the count is open."
CLARIFY = "Finishing the count is a procedure, not a conclusion about controls."

EXPECTED_ANSWER = """## Advice

alpha `c1`: Do not state that the controls are effective.

## Agreed

- alpha `c1` (recommendation): Do not state that the controls are effective.

## Disagreements

### bravo holds `c1` (recommendation)

Tell the lender it may rely on the letter.

- Rebuttal by alpha: A lender-reliance statement is not supported while the count is open.

## Unchallenged, not treated as consensus

- charlie `c1` (recommendation): Ask management to finish the inventory count before any letter is issued.

## What would change the advice

None.
"""


class ModelClientDouble:
    calls = 0

    def __init__(self, *args, **kwargs):
        ModelClientDouble.calls += 1

    async def post(self, *args, **kwargs):
        ModelClientDouble.calls += 1
        raise AssertionError("model client called")

    def __enter__(self):
        ModelClientDouble.calls += 1
        return self

    def __exit__(self, *args):
        return False

    async def __aenter__(self):
        ModelClientDouble.calls += 1
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def wrap_model_clients(monkeypatch):
    ModelClientDouble.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", ModelClientDouble)
    monkeypatch.setattr(httpx, "Client", ModelClientDouble)
    monkeypatch.setattr(adapters.httpx, "AsyncClient", ModelClientDouble)
    monkeypatch.setattr(adapters.httpx, "Client", ModelClientDouble)
    yield
    assert ModelClientDouble.calls == 0


def _mixed_inputs():
    held = [
        HeldClaim("charlie", "c1", UNTOUCHED, "recommendation"),
        HeldClaim("alpha", "c1", AGREED, "recommendation"),
        HeldClaim("bravo", "c1", CONTESTED, "recommendation"),
    ]
    stances = [
        Stance("charlie", "alpha", "c1", "concede", "Effectiveness is unsupported until the count is complete."),
        Stance("bravo", "alpha", "c1", "concede", "The count is unfinished, so effectiveness cannot be stated."),
        Stance("alpha", "bravo", "c1", "rebut", REBUTTAL),
        Stance("charlie", "bravo", "c1", "clarify", "The letter's date and period need to be stated before reliance is discussed."),
        Stance("bravo", "charlie", "c1", "clarify", "The count timing affects what the letter can cover."),
        Stance("alpha", "charlie", "c1", "clarify", CLARIFY),
    ]
    return held, stances


def test_fixture_statuses_and_sections_and_client_is_never_called():
    assert NO_AGREEMENT_SENTENCE == (
        "The models did not reach agreement on a recommendation. "
        "The disagreements below are the substance of the advice."
    )
    assert "No model writes the final answer." in RULE
    held, stances = _mixed_inputs()
    answer, record = compose(PANEL, held, stances, [])
    assert answer == EXPECTED_ANSWER
    assert headings(answer) == [
        "Advice",
        "Agreed",
        "Disagreements",
        "Unchallenged, not treated as consensus",
        "What would change the advice",
    ]
    parsed = sections(answer)
    assert parsed["Advice"] == f"alpha `c1`: {AGREED}"
    assert CONTESTED not in parsed["Advice"]
    assert UNTOUCHED not in parsed["Advice"]
    assert NO_AGREEMENT_SENTENCE not in parsed["Advice"]
    assert AGREED in parsed["Agreed"]
    assert CONTESTED not in parsed["Agreed"]
    assert UNTOUCHED not in parsed["Agreed"]
    assert "Nothing was agreed." not in answer
    assert CONTESTED in parsed["Disagreements"]
    assert REBUTTAL in parsed["Disagreements"]
    assert "Rebuttal by alpha" in parsed["Disagreements"]
    assert "Rebuttal by charlie" not in parsed["Disagreements"]
    assert CLARIFY not in answer
    assert f"charlie `c1`" in parsed["Unchallenged, not treated as consensus"]
    assert UNTOUCHED in parsed["Unchallenged, not treated as consensus"]
    assert parsed["What would change the advice"] == "None."

    by_claim = {(row["author"], row["claim_id"]): row for row in record["claims"]}
    assert by_claim[("alpha", "c1")]["status"] == "agreed"
    assert by_claim[("bravo", "c1")]["status"] == "contested"
    assert by_claim[("charlie", "c1")]["status"] == "unchallenged"
    assert [row["effective_stance"] for row in by_claim[("alpha", "c1")]["stances"]] == [
        "concede",
        "concede",
    ]
    bravo_stances = {row["reviewer"]: row for row in by_claim[("bravo", "c1")]["stances"]}
    assert bravo_stances["alpha"]["effective_stance"] == "rebut"
    assert bravo_stances["charlie"]["effective_stance"] == "clarify"
    assert ModelClientDouble.calls == 0


def test_conflicting_recommendations_keep_both_sides():
    held = [
        HeldClaim("bravo", "c1", "Do not say the controls are effective.", "recommendation"),
        HeldClaim("alpha", "c1", "Say the controls are effective.", "recommendation"),
    ]
    stances = [
        Stance("bravo", "alpha", "c1", "rebut", "The inventory count is unfinished, so effectiveness cannot be stated."),
        Stance("charlie", "alpha", "c1", "rebut", "The lender cannot be told the controls are effective while the count is open."),
        Stance("alpha", "bravo", "c1", "rebut", "Refusing that sentence is the advice the open count supports."),
        Stance("charlie", "bravo", "c1", "rebut", "The unfinished count is a reason to keep the warning in view."),
    ]
    answer, record = compose(PANEL, held, stances, [])
    parsed = sections(answer)
    assert parsed["Advice"] == NO_AGREEMENT_SENTENCE
    assert answer.count(NO_AGREEMENT_SENTENCE) == 1
    assert parsed["Agreed"] == "Nothing was agreed."
    assert "Say the controls are effective." in parsed["Disagreements"]
    assert "Do not say the controls are effective." in parsed["Disagreements"]
    assert "Rebuttal by bravo" in parsed["Disagreements"]
    assert "Rebuttal by charlie" in parsed["Disagreements"]
    assert "Rebuttal by alpha" in parsed["Disagreements"]
    assert parsed["Unchallenged, not treated as consensus"] == "None."
    assert parsed["What would change the advice"] == "None."
    statuses = {row["author"]: row["status"] for row in record["claims"]}
    assert statuses == {"alpha": "contested", "bravo": "contested"}


def test_identical_sentences_are_not_treated_as_agreement():
    sentence = "Do not state that the controls are effective."
    held = [
        HeldClaim(author, "c1", sentence, "recommendation")
        for author in PANEL
    ]
    stances = []
    for reviewer in PANEL:
        for author in PANEL:
            if reviewer == author:
                continue
            stances.append(
                Stance(
                    reviewer,
                    author,
                    "c1",
                    "clarify",
                    "The unfinished count still needs to be named beside this sentence.",
                )
            )
    answer, record = compose(PANEL, held, stances, [])
    assert sections(answer)["Advice"] == NO_AGREEMENT_SENTENCE
    assert sections(answer)["Agreed"] == "Nothing was agreed."
    assert sections(answer)["Disagreements"] == "None."
    assert answer.count(sentence) == 3
    assert {row["status"] for row in record["claims"]} == {"unchallenged"}


def test_one_concession_is_not_agreement():
    held = [HeldClaim("alpha", "c1", AGREED, "recommendation")]
    stances = [
        Stance("bravo", "alpha", "c1", "concede", "The count is unfinished, so effectiveness cannot be stated."),
        Stance("charlie", "alpha", "c1", "clarify", "The letter period still needs to be named before this is used."),
    ]
    answer, record = compose(PANEL, held, stances, [])
    assert sections(answer)["Advice"] == NO_AGREEMENT_SENTENCE
    assert sections(answer)["Agreed"] == "Nothing was agreed."
    assert record["claims"][0]["status"] == "unchallenged"
    assert AGREED in sections(answer)["Unchallenged, not treated as consensus"]


def test_later_concession_removes_the_rebuttal_from_the_answer():
    held = [HeldClaim("alpha", "c1", AGREED, "recommendation")]
    stances = [
        Stance("bravo", "alpha", "c1", "rebut", "Effectiveness is not supported while the count remains open."),
        Stance("charlie", "alpha", "c1", "concede", "The count is unfinished, so effectiveness cannot be stated."),
    ]
    concessions = [Concession("bravo", "alpha", "c1")]
    answer, record = compose(PANEL, held, stances, concessions)
    assert sections(answer)["Advice"] == f"alpha `c1`: {AGREED}"
    assert sections(answer)["Disagreements"] == "None."
    assert "Rebuttal by" not in answer
    stance = record["claims"][0]["stances"][0]
    assert stance["reviewer"] == "bravo"
    assert stance["round_2_stance"] == "rebut"
    assert stance["round_3_conceded"] is True
    assert stance["effective_stance"] == "concede"
    assert record["claims"][0]["status"] == "agreed"


def test_contested_would_change_stays_in_disagreements():
    change = "A finished count would change the advice given to the partner."
    held = [
        HeldClaim("alpha", "c1", AGREED, "recommendation"),
        HeldClaim("alpha", "c2", change, "would_change"),
    ]
    stances = [
        Stance("bravo", "alpha", "c1", "concede", "The count is unfinished, so effectiveness cannot be stated."),
        Stance("charlie", "alpha", "c1", "concede", "Effectiveness is unsupported until the count is complete."),
        Stance("bravo", "alpha", "c2", "rebut", "Finishing the count alone would not decide the letter wording."),
        Stance("charlie", "alpha", "c2", "concede", "A finished count is a real condition for changing the wording."),
    ]
    answer, record = compose(PANEL, held, stances, [])
    parsed = sections(answer)
    assert parsed["Advice"] == f"alpha `c1`: {AGREED}"
    assert change not in parsed["Advice"]
    assert change in parsed["Disagreements"]
    assert "Rebuttal by bravo" in parsed["Disagreements"]
    assert parsed["What would change the advice"] == "None."
    by_id = {row["claim_id"]: row["status"] for row in record["claims"]}
    assert by_id == {"c1": "agreed", "c2": "contested"}


def test_agreed_would_change_is_listed_and_does_not_invent_a_recommendation():
    change = "A finished count would change the advice given to the partner."
    held = [HeldClaim("alpha", "c2", change, "would_change")]
    stances = [
        Stance("bravo", "alpha", "c2", "concede", "A finished count is a real condition for changing the wording."),
        Stance("charlie", "alpha", "c2", "concede", "The open count is the condition that would change this advice."),
    ]
    answer, _record = compose(PANEL, held, stances, [])
    parsed = sections(answer)
    assert parsed["Advice"] == NO_AGREEMENT_SENTENCE
    assert change in parsed["Agreed"]
    assert parsed["What would change the advice"] == f"- alpha `c2` (would_change): {change}"
    assert parsed["Disagreements"] == "None."


def test_claim_id_order_is_numeric():
    sentence_two = "Ask for the unfinished count items before any letter is issued."
    sentence_ten = "Name the period the comfort letter would cover before drafting it."
    held = [
        HeldClaim("alpha", "c10", sentence_ten, "recommendation"),
        HeldClaim("alpha", "c2", sentence_two, "recommendation"),
    ]
    stances = []
    for claim_id in ("c10", "c2"):
        for reviewer in ("bravo", "charlie"):
            stances.append(
                Stance(
                    reviewer,
                    "alpha",
                    claim_id,
                    "concede",
                    "The missing count evidence makes this request specific enough to concede.",
                )
            )
    answer, _record = compose(PANEL, held, stances, [])
    assert sections(answer)["Advice"] == (
        f"alpha `c2`: {sentence_two}\n\nalpha `c10`: {sentence_ten}"
    )


def test_same_inputs_in_any_order_return_the_same_output():
    held, stances = _mixed_inputs()
    first = compose(PANEL, held, stances, [])
    second = compose(PANEL, list(reversed(held)), list(reversed(stances)), [])
    assert first == second


def test_compose_rejects_a_missing_stance_and_an_empty_reason():
    held = [HeldClaim("alpha", "c1", AGREED, "recommendation")]
    with pytest.raises(ValueError, match="missing stance"):
        compose(
            PANEL,
            held,
            [Stance("bravo", "alpha", "c1", "concede", "The count is unfinished, so this claim is conceded.")],
            [],
        )
    with pytest.raises(ValueError, match="empty reason"):
        compose(
            PANEL,
            held,
            [
                Stance("bravo", "alpha", "c1", "concede", "   "),
                Stance("charlie", "alpha", "c1", "clarify", "The letter period still needs to be named here."),
            ],
            [],
        )


def test_compose_source_does_not_call_a_model_or_match_text():
    source = Path("deliberation/compose.py").read_text()
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    for name in imported:
        for banned in ("httpx", "openai", "anthropic", "requests", "urllib", "socket", "langgraph"):
            assert banned not in name
    lowered = source.lower()
    for banned in ("embedding", "majority", "cosine", "similarity", "vote"):
        assert banned not in lowered
    assert "def compose(" in source
