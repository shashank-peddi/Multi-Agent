import json


POSITION = (
    "The partner should refuse any statement that the controls are effective "
    "or that the lender may rely on the letter while the inventory count is unfinished. "
    "Ask management for the open count items, the locations still uncounted, "
    "and the period the letter would cover before any draft is discussed."
)

MODELS = (
    "openai/gpt-test",
    "anthropic/claude-test",
    "google/gemini-test",
)

CLAIMS = {
    "openai/gpt-test": [
        {
            "id": "c1",
            "sentence": "Do not state that the controls are effective.",
            "type": "recommendation",
        },
        {
            "id": "c2",
            "sentence": "The inventory count procedures are still incomplete.",
            "type": "reason",
        },
        {
            "id": "c3",
            "sentence": "A finished count with cleared exceptions would change the wording.",
            "type": "would_change",
        },
    ],
    "anthropic/claude-test": [
        {
            "id": "c1",
            "sentence": "Do not tell the lender it may rely on the letter.",
            "type": "recommendation",
        },
        {
            "id": "c2",
            "sentence": "Saying controls are effective would outrun the evidence.",
            "type": "risk",
        },
        {
            "id": "c3",
            "sentence": "Ask for the open count items and the period the letter would cover.",
            "type": "reason",
        },
    ],
    "google/gemini-test": [
        {
            "id": "c1",
            "sentence": "Wait for management's count memo before answering the lender.",
            "type": "recommendation",
        },
        {
            "id": "c2",
            "sentence": "The letter date is three weeks before year-end.",
            "type": "reason",
        },
        {
            "id": "c3",
            "sentence": "Incomplete procedures leave a gap a comfort letter cannot paper over.",
            "type": "risk",
        },
    ],
}


class ScriptedAdapter:
    def __init__(self, model_id: str, rounds: dict):
        self.model_id = model_id
        self.vendor = model_id.split("/", 1)[0]
        self.rounds = rounds
        self.calls = []

    async def complete(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if user.startswith("This is round 1"):
            key = "1"
        elif user.startswith("This is round 2"):
            key = "2"
        elif user.startswith("This is round 3"):
            key = "3"
        else:
            raise AssertionError("round marker missing")
        return json.dumps(self.rounds[key])


class FailingAdapter:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.vendor = model_id.split("/", 1)[0]
        self.calls = []

    async def complete(self, *, system: str, user: str) -> str:
        self.calls.append(user)
        raise RuntimeError("connection reset")


def stance_for(reviewer: str, author: str, claim: dict) -> tuple[str, str]:
    claim_id = claim["id"]
    if author == "openai/gpt-test" and claim_id == "c1":
        return ("concede", "The count is unfinished, so effectiveness cannot be stated.")
    if author == "anthropic/claude-test" and claim_id == "c1" and reviewer == "openai/gpt-test":
        return (
            "rebut",
            "A reliance refusal is right only when it names the missing count evidence.",
        )
    if author == "anthropic/claude-test" and claim_id == "c1" and reviewer == "google/gemini-test":
        return (
            "clarify",
            "The period covered by the letter still has to be named before the refusal is drafted.",
        )
    if author == "google/gemini-test" and claim_id == "c1" and reviewer == "openai/gpt-test":
        return (
            "clarify",
            "A count memo is one request, and the partner still has to decide the letter limits.",
        )
    if author == "google/gemini-test" and claim_id == "c1" and reviewer == "anthropic/claude-test":
        return (
            "clarify",
            "Waiting may be wise, but the open count items should be listed in the request.",
        )
    return (
        "concede",
        f"I concede {author} {claim_id} because the sentence matches the open count and the missing evidence.",
    )


def make_adapters() -> list[ScriptedAdapter]:
    adapters = []
    for model_id in MODELS:
        own = CLAIMS[model_id]
        responses = []
        for other in MODELS:
            if other == model_id:
                continue
            for claim in CLAIMS[other]:
                stance, reason = stance_for(model_id, other, claim)
                responses.append(
                    {
                        "claim_id": claim["id"],
                        "author": other,
                        "stance": stance,
                        "reason": reason,
                    }
                )
        rounds = {
            "1": {"position": POSITION, "claims": own},
            "2": {"responses": responses},
            "3": {
                "position": POSITION,
                "claims": [
                    {
                        "id": claim["id"],
                        "sentence": claim["sentence"],
                        "type": claim["type"],
                        "changed": False,
                        "caused_by_critic": None,
                        "caused_by_claim_id": None,
                    }
                    for claim in own
                ],
                "withdrawn": [],
                "concessions": [],
            },
        }
        adapters.append(ScriptedAdapter(model_id, rounds))
    return adapters
