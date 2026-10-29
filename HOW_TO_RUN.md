# How to run

Run these commands from the project directory. You need Python 3.11 or newer.

## 1. Install

```shell
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If this folder already has a `.venv` from a previous install, activate it and skip the install.

## 2. Set the environment

Keys and the panel are read from the process environment. The program does not load a `.env` file.

`PANEL_MODELS` is a comma-separated list of `vendor/model` ids. Use at least three models from at least two of these vendors: `openai`, `anthropic`, `google`. The model name itself cannot contain a slash.

```shell
export PANEL_MODELS='openai/<model>,anthropic/<model>,google/<model>'
export OPENAI_API_KEY='...'
export ANTHROPIC_API_KEY='...'
export GOOGLE_API_KEY='...'
```

Google also accepts `GEMINI_API_KEY`. When both Google variables are set, `GOOGLE_API_KEY` is the one sent.

Optional:

```shell
export TRANSCRIPT_DIR='transcripts'    # default
export MODEL_TIMEOUT_SECONDS='120'     # default, seconds per model call
```

A panel of three models and two vendors is enough. Example: two OpenAI models and one Anthropic model. One vendor, fewer than three models, or a malformed entry makes `POST /answer` and `POST /answer/hard-01` return 503.

## 3. Start the API

```shell
uvicorn app:app
```

With the virtualenv from step 1 and no activation, the same server is:

```shell
.venv/bin/uvicorn app:app
```

The API listens on `http://127.0.0.1:8000`.

## 4. Check the panel

```shell
curl -s http://127.0.0.1:8000/health
```

`meets_rule` is true when the panel has at least three models from at least two vendors. This request does not call a model. Key values are not included.

## 5. Ask a question

```shell
curl -s -X POST http://127.0.0.1:8000/answer \
  -H 'Content-Type: application/json' \
  -d '{"question": "What should the partner tell the lender?"}'
```

The JSON body has three fields:

- `client_answer` — Advice, Agreed, Disagreements, Unchallenged, and What would change the advice
- `decision_record` — every surviving claim id, its status, and the stances that produced that status
- `transcript` — the three rounds, in markdown

A round that fails is recorded. The answer is not built from the models that succeeded.

## 6. Run the comfort-letter question

```shell
curl -s -X POST http://127.0.0.1:8000/answer/hard-01
```

This route ignores any body. It uses the question stored in `deliberation/question.py`, writes the transcript, and adds `transcript_path` to the response. The default file is `transcripts/hard-01.md`. That directory is gitignored.

Each round calls every model, and a failed response is retried once. Expect the request to take a few minutes.

## 7. Run the tests

The tests do not call a model and do not need API keys.

```shell
.venv/bin/pytest -q
```
