# teruo — キッチンカー在庫エージェント

ケバブ屋台の売上と棚卸しから在庫と消費係数を管理するPython CLI。
係数ロジックは消費型3分類（count / weight / unit）の3系統。
名前は英語の tell から（表記は常に小文字 `teruo`）。

## Run & Operate

- `python main.py` — 対話型CLIを起動（状態が空なら初回カウンセリング）
- `python main.py --setup` — カウンセリングを強制起動
- Required secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_DEFAULT_REGION`（`us-east-2`）

## Stack

- Python 3.12
- Strands Agents
- Amazon Bedrock / Claude Sonnet
- JSON file persistence; no database or web framework

## Where things live

- CLI loop and counseling agent: `main.py`
- Operations agents (報告係・記録係・観測係, agents-as-tools): `agents.py`
- Tool calculations: `tools.py`
- Atomic JSON persistence: `store.py`
- State: `data/state.json`
- Convergence simulation: `tests/simulate_convergence.py`
- Scope: `docs/teruo-design.md`（設計書B・正本）, `docs/teruo-instructions.md`（実装指示書）

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
  error); displays say 実測が必要です instead of showing a negative number.
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
