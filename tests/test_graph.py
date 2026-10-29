import asyncio
from pathlib import Path

from deliberation.graph import build_graph, project_inputs, run_deliberation
from deliberation.schemas import Concession
from tests.fakes import FailingAdapter, make_adapters
from tests.support import sections


def test_edges_are_fixed_and_unconditional():
    graph = build_graph(make_adapters())
    edges = {
        (edge.source, edge.target, edge.conditional) for edge in graph.get_graph().edges
    }
    assert edges == {
        ("__start__", "round_1", False),
        ("round_1", "round_2", False),
        ("round_2", "round_3", False),
        ("round_3", "compose", False),
        ("compose", "__end__", False),
    }
    assert "add_conditional_edges" not in Path("deliberation/graph.py").read_text()


def test_project_inputs_drops_withdrawn_claims():
    panel = ["alpha", "bravo"]
    round2 = {
        "alpha": {"responses": []},
        "bravo": {"responses": []},
    }
    round3 = {
        "alpha": {
            "claims": [
                {
                    "id": "c1",
                    "sentence": "Rewritten sentence stays with its author.",
                    "type": "recommendation",
                }
            ],
            "withdrawn": [
                {"id": "c2", "caused_by_critic": "bravo", "caused_by_claim_id": "c1"}
            ],
            "concessions": [{"author": "bravo", "claim_id": "c1"}],
        },
        "bravo": {"claims": [], "withdrawn": [], "concessions": []},
    }
    held, _stances, concessions = project_inputs(panel, round2, round3)
    assert [claim.claim_id for claim in held] == ["c1"]
    assert held[0].sentence == "Rewritten sentence stays with its author."
    assert concessions == [Concession("alpha", "bravo", "c1")]


def test_scripted_panel_reaches_compose_in_three_calls_each():
    adapters = make_adapters()
    result = asyncio.run(
        run_deliberation("What should the partner say about the open count?", adapters)
    )
    assert result["decision_record"]["failure"] is False, result["decision_record"]
    assert sum(len(adapter.calls) for adapter in adapters) == 9
    for adapter in adapters:
        assert [call["user"].split("\n", 1)[0] for call in adapter.calls] == [
            "This is round 1 of 3.",
            "This is round 2 of 3.",
            "This is round 3 of 3.",
        ]
        assert "No model writes the final answer." in adapter.calls[0]["system"]
        round1 = adapter.calls[0]["user"]
        for other in adapters:
            if other is not adapter:
                assert other.model_id not in round1
        assert "Do not return a replacement final answer." in adapter.calls[1]["user"]
        assert "Do not return a merged answer." in adapter.calls[2]["user"]

    claims = {
        (row["author"], row["claim_id"]): row["status"]
        for row in result["decision_record"]["claims"]
    }
    assert claims[("openai/gpt-test", "c1")] == "agreed"
    assert claims[("anthropic/claude-test", "c1")] == "contested"
    assert claims[("google/gemini-test", "c1")] == "unchallenged"
    parsed = sections(result["client_answer"])
    assert parsed["Advice"] == (
        "openai/gpt-test `c1`: Do not state that the controls are effective."
    )
    assert "Do not tell the lender it may rely on the letter." in parsed["Disagreements"]
    assert "Wait for management's count memo before answering the lender." in parsed[
        "Unchallenged, not treated as consensus"
    ]
    assert (
        "A finished count with cleared exceptions would change the wording."
        in parsed["What would change the advice"]
    )


def test_one_failed_model_does_not_compose(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("compose was called")

    monkeypatch.setattr("deliberation.graph.compose", forbid)
    adapters = make_adapters()
    failing = FailingAdapter(adapters[0].model_id)
    group = [failing, adapters[1], adapters[2]]
    result = asyncio.run(run_deliberation("What should the partner say?", group))
    assert result["client_answer"] is None
    assert result["decision_record"]["failure"] is True
    assert result["decision_record"]["claims"] == []
    assert result["decision_record"]["failures"][0]["model"] == failing.model_id
    assert "No client answer was composed." in result["transcript"]
    assert "were not used to form an answer." in result["transcript"]
    assert "connection reset" in result["transcript"]
    assert len(failing.calls) == 2
    assert "previous response failed" in failing.calls[1]
    for adapter in group[1:]:
        assert len(adapter.calls) == 1
        assert adapter.calls[0]["user"].startswith("This is round 1")
