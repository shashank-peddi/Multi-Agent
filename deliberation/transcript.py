"""Readable transcript. This module does not call a model."""

from __future__ import annotations

from pathlib import Path

from deliberation.panel import transcript_directory


FAILURE_MESSAGE = (
    "A model failed a round. No answer was composed from the remaining models."
)


def render_transcript(state: dict, answer: str | None, record: dict) -> str:
    panel = list(state.get("panel") or [])
    lines: list[str] = ["# Transcript", "", "## Question", "", (state.get("question") or "").strip(), ""]
    lines.extend(["## Panel", ""])
    if panel:
        lines.extend(f"- {model_id}" for model_id in panel)
    else:
        lines.append("No panel was recorded.")
    lines.append("")

    _round_block(
        lines,
        "Round 1 — alone",
        panel,
        state.get("round1") or {},
        _render_round1,
    )
    _round_block(
        lines,
        "Round 2 — cross-examination",
        panel,
        state.get("round2") or {},
        _render_round2,
    )
    _round_block(
        lines,
        "Round 3 — revise own answer",
        panel,
        state.get("round3") or {},
        _render_round3,
    )

    lines.extend(["## Decision record", ""])
    lines.append(record.get("rule") or "")
    lines.append("")
    if record.get("failure"):
        lines.append(record.get("message") or FAILURE_MESSAGE)
        lines.append("")
        for failure in record.get("failures") or []:
            lines.append(
                f"- {failure.get('round', 'round')} `{failure.get('model', 'unknown')}`: "
                f"{failure.get('error', '')}"
            )
        lines.append("")
        lines.append("Drafts shown above, if any, were not used to form an answer.")
        lines.append("")
    else:
        for claim in record.get("claims") or []:
            lines.append(
                f"- `{claim['author']}` `{claim['claim_id']}` ({claim['type']}) — **{claim['status']}**"
            )
            lines.append(f"  - {claim['sentence']}")
            for stance in claim["stances"]:
                lines.append(f"  - {_stance_line(stance)}")
            lines.append("")

    lines.extend(["## Client answer", ""])
    if answer:
        lines.append(answer.rstrip())
    else:
        lines.append("No client answer was composed.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_transcript(name: str, text: str) -> Path:
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("transcript name must be a file name")
    directory = Path(transcript_directory())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _round_block(lines: list[str], title: str, panel: list[str], payloads: dict, render) -> None:
    lines.extend([f"## {title}", ""])
    if not payloads:
        lines.extend(["No output was recorded for this round.", ""])
        return
    for model_id in panel:
        lines.extend([f"### {model_id}", ""])
        payload = payloads.get(model_id)
        if not payload:
            lines.extend(["No output.", ""])
            continue
        render(lines, payload)


def _render_round1(lines: list[str], payload: dict) -> None:
    lines.extend(["**Position**", "", payload.get("position", ""), "", "**Claims**", ""])
    for claim in payload.get("claims") or []:
        lines.append(f"- `{claim['id']}` ({claim['type']}): {claim['sentence']}")
    lines.append("")


def _render_round2(lines: list[str], payload: dict) -> None:
    for item in payload.get("responses") or []:
        lines.append(
            f"- `{item['author']}` `{item['claim_id']}`: **{item['stance']}** — {item['reason']}"
        )
    lines.append("")


def _render_round3(lines: list[str], payload: dict) -> None:
    lines.extend(["**Position**", "", payload.get("position", ""), "", "**Still held**", ""])
    claims = payload.get("claims") or []
    if not claims:
        lines.append("None.")
    for claim in claims:
        if claim.get("changed"):
            change = (
                f"rewritten because `{claim.get('caused_by_critic')}` "
                f"`{claim.get('caused_by_claim_id')}`"
            )
        else:
            change = "unchanged"
        lines.append(f"- `{claim['id']}` ({claim['type']}): {claim['sentence']} — {change}")
    lines.extend(["", "**Withdrawn**", ""])
    withdrawn = payload.get("withdrawn") or []
    if not withdrawn:
        lines.append("None.")
    for item in withdrawn:
        lines.append(
            f"- `{item['id']}` withdrawn because `{item['caused_by_critic']}` "
            f"`{item['caused_by_claim_id']}`"
        )
    lines.extend(["", "**Concessions**", ""])
    concessions = payload.get("concessions") or []
    if not concessions:
        lines.append("None.")
    for item in concessions:
        lines.append(f"- concedes `{item['author']}` `{item['claim_id']}`")
    lines.append("")


def _stance_line(stance: dict) -> str:
    if stance["round_3_conceded"] and stance["round_2_stance"] != "concede":
        how = f"concede (round 3 concession; round 2 was {stance['round_2_stance']})"
    elif stance["round_3_conceded"]:
        how = "concede (round 2, and conceded again in round 3)"
    else:
        how = f"{stance['effective_stance']} (round 2)"
    return f"`{stance['reviewer']}`: {how} — {stance['round_2_reason']}"
