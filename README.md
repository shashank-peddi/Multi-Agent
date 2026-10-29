# Panel deliberation

A FastAPI service that sends one open question to at least three models from at least two vendors, has them answer each other, and assembles the client answer in Python.

No model writes the final answer. LangGraph runs three fixed rounds: alone, cross-examination, then each model revises only its own claims. `compose()` in `deliberation/compose.py` turns that record into the answer. It does not call a model, vote, or compare claim text.

A claim is agreed when its author still holds that claim id and every other model has conceded that same id. It is contested when the author still holds it and another model rebutted it without later conceding that id. It is unchallenged when the author still holds it and nobody rebutted it, but not every other model conceded it. Withdrawn claims are dropped. If no recommendation is agreed, Advice is:

> The models did not reach agreement on a recommendation. The disagreements below are the substance of the advice.

## Routes

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | Reports panel size, vendor count, and whether the panel meets the rule. Does not call a model. |
| `POST` | `/answer` | Body `{"question": "..."}`. Returns the client answer, the decision record, and the transcript. |
| `POST` | `/answer/hard-01` | Runs the fixed comfort-letter question, writes `hard-01.md`, and returns the same payload plus `transcript_path`. |

If the panel has fewer than three models or fewer than two vendors, the answer routes return 503. Health still reports the counts.

## Layout

- `app.py` — FastAPI app. Serve it with `uvicorn app:app`.
- `deliberation/` — rounds, vendor adapters, validation, transcript, and `compose()`.
- `tests/` — the decision rule and the environment-variable checks, with no network.

Setup, environment variables, and the curl commands are in [HOW_TO_RUN.md](HOW_TO_RUN.md).
