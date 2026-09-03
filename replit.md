# teruo — food-truck inventory agent

A Python CLI that manages stock and consumption coefficients from a kebab
stall's sales and stock counts. Coefficient logic branches three ways by
consumption type (count / weight / unit).
The name comes from the English "tell" (always written lowercase `teruo`).
The product speaks English by default and Japanese with `--lang ja`
(prompts, tool output, CLI); the choice is stored in state.json as
config.language. README.ja.md is the Japanese README; the design docs are
Japanese with English translations in docs/*.en.md.

## Run & Operate

- `python main.py` — start the interactive CLI (onboarding runs if state is empty)
- `python web.py` — the one-screen browser entry point on PORT (default 5000)
- `python main.py --setup` — force the onboarding interview
- `python main.py --lang ja` — switch to Japanese (remembered; `TERUO_LANG=ja` also works)
- Type a file name on the prompt line to hand over a menu photo or a stocktake sheet
- `INVENTORY_STATE_PATH=data/state.ja.json python main.py` — the Japanese demo shop
- Required secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_DEFAULT_REGION` (`us-east-2`)

## Stack

- Python 3.12
- FastAPI + uvicorn for the web entry point only (the CLI needs neither)
- Strands Agents
- Amazon Bedrock / Claude Sonnet
- JSON file persistence; no database or web framework

## Where things live

- CLI loop, counseling agent, shared `build_agent`: `main.py`
- Web entry point (SSE stream, uploads): `web.py`; the single page: `web/index.html`
- Operations agents (reporter / record keeper / observer, agents-as-tools): `agents.py`
- File input (typed file names → image/document content blocks): `attachments.py`
- Tool calculations: `tools.py`
- Every user-facing string, English and Japanese side by side: `i18n.py` (`t("key")`)
- Atomic JSON persistence: `store.py`
- State: `data/state.json` (`data/state.ja.json`: same shop, Japanese names/counters)
- Convergence simulation: `tests/simulate_convergence.py`
- Scope: `docs/teruo-design.md` (design doc B, authoritative), `docs/teruo-instructions.md` (implementation instructions; both in Japanese, English translations as `*.en.md`)

## Architecture decisions

- All arithmetic runs in Python tools, never in the model.
- Menu photos and spreadsheets are read by handing the raw bytes to Bedrock as
  Converse image/document content blocks (`attachments.py`); nothing is parsed
  locally, so there is no openpyxl/OCR dependency. Anything read this way is a
  proposal — the prompts require showing it and getting a yes before a tool is
  called (design doc ch.9). URLs are refused in Python, not by the model:
  external access stays out of scope (instructions appendix A).
- The browser entry point is an entry point and nothing more. `web.py` calls
  the same `main.build_agent`, and `tools.set_output_sink` (a ContextVar, so it
  follows a sync tool onto the worker thread Strands runs it on) redirects
  principle-3 facts from stdout to that request's SSE stream, verbatim and
  tagged. tools.py / agents.py / store.py / i18n.py are unchanged by it. The
  page shows tool and role activity inline so agents-as-tools is visible.
  One shop, one conversation, one message at a time (asyncio lock — Strands
  refuses concurrent invocations on one Agent).
- A stranger reaching an already-configured teruo is a prompt-level guard, not
  an auth feature: reads (stock, sales, reconciliation) are deliberately
  passphrase-free for staff, so the reporter is told to stop before showing
  figures when someone says they are new and point them at `--setup`.
- Factual tool output (sales breakdown, count results, unit-used results,
  stock status, monthly reconciliation) prints directly to stdout from the
  tool; the LLM is told not to repeat it and only adds judgment. This keeps
  the numbers on screen deterministic (design principle 3).
- State writes replace the JSON file atomically to avoid partial-file corruption.
- The first stock count establishes a baseline and does not alter the coefficient.
- Operations mode splits judgment across three agents (reporter/front,
  record keeper, observer) via agents-as-tools; the calculation layer is shared
  and unchanged. Counseling mode stays a single agent.
- Consumption logic has three types (design doc ch.2): `count` (fixed 1.0),
  `weight` (coefficient learned from count diffs with 0.5 smoothing toward the
  measured value — raw updates oscillated in simulation — bounded to recipe ±4g/serving),
  `unit` (servings-per-unit learned only from used-up events, bounded to ±20%
  of past results once 3 samples exist).
- Negative theoretical stock is kept internally (never clamped to 0, never an
  error); displays say "recount needed" instead of showing a negative number.
- Who entered a number is never recorded, only when (design doc principle 10).
- get_monthly_reconciliation cross-checks purchases vs recipe-based consumption
  vs counted stock per month (design doc principle 12).
- Structure changes (recipes, units, item registry, config) require the shared
  passphrase stored in `state.json`; daily inputs (sales, counts, purchases) do not.
- Items are never deleted, only `active: false`. History and settings_log are append-only.
- All owner-facing text goes through `i18n.t()`; code never branches on a
  label's wording (learning phase is returned as a code by `tools._growth`).
  Tool docstrings stay English — the model reads them, the owner doesn't.
  Japanese counters (枚/本/個) are valid count units; `_amount` never
  pluralizes or spaces non-ASCII units.

## User preferences

- Do not add unrequested features beyond the supplied design document.
- No database, no Docker, no auth system, no external APIs. (The web UI
  exclusion was lifted deliberately — see `web.py`; it adds no state, no
  accounts and no dependencies beyond FastAPI/uvicorn.)

## Gotchas

- Bedrock interaction requires the AWS credentials above.
- Do not deploy as-is. `.replit` still targets autoscale, whose filesystem is
  ephemeral: every restart or scale-to-zero resets `data/state.json` to the
  committed demo shop, and multiple instances would each hold their own copy.
  The demo runs from the workspace Run button, where the file persists
  (decided 2026-09-03). Moving state to a database — or, at minimum, one JSON
  blob in Replit Object Storage via `store.load_state`/`save_state` — is the
  production step the design doc defers (ch.7 "今回やらないこと"), not a
  pre-deadline task.
- Keep secrets out of source files and do not create `.env`.
- Dates must be generated in Python (`ZoneInfo("Asia/Tokyo")`), never by the model.

## Pointers

- `README.md` contains operator instructions.
