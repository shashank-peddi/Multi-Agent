from dataclasses import dataclass


CLAIM_TYPES = ("recommendation", "reason", "risk", "would_change")
STANCES = ("concede", "rebut", "clarify")


@dataclass(frozen=True)
class HeldClaim:
    author: str
    claim_id: str
    sentence: str
    claim_type: str


@dataclass(frozen=True)
class Stance:
    reviewer: str
    author: str
    claim_id: str
    stance: str
    reason: str


@dataclass(frozen=True)
class Concession:
    reviewer: str
    author: str
    claim_id: str
