# teruo — food-truck inventory agent

A Python CLI that manages stock and consumption coefficients from a kebab
stall's sales and stock counts. Coefficient logic branches three ways by
consumption type (count / weight / unit).
The name comes from the English "tell" (always written lowercase `teruo`).
The entire product (UI, prompts, docs) is in English; README.ja.md keeps
the Japanese README.

## Run & Operate

- `python main.py` — start the interactive CLI (onboarding runs if state is empty)
- `python main.py --setup` — force the onboarding interview
- Required secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_DEFAULT_REGION` (`us-east-2`)

## Stack

- Python 3.12
- Strands Agents
- Amazon Bedrock / Claude Sonnet
- JSON file persistence; no database or web framework

## Where things live

- CLI loop and counseling agent: `main.py`
- Operations agents (reporter / record keeper / observer, agents-as-tools): `agents.py`
- Tool calculations: `tools.py`
- Atomic JSON persistence: `store.py`
- State: `data/state.json`
- Convergence simulation: `tests/simulate_convergence.py`
- Scope: `docs/teruo-design.md` (design doc B, authoritative), `docs/teruo-instructions.md` (implementation instructions; both in Japanese)

## Architecture decisions

- All arithmetic runs in Python tools, never in the model.
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

## User preferences

- Do not add unrequested features beyond the supplied design document.
- No web UI, no database, no Docker, no auth system, no external APIs.

## Gotchas

- Bedrock interaction requires the AWS credentials above.
- Keep secrets out of source files and do not create `.env`.
- Dates must be generated in Python (`ZoneInfo("Asia/Tokyo")`), never by the model.

## Pointers

- `README.md` contains operator instructions.
