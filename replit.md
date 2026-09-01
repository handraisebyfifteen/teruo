# teruo — キッチンカー在庫エージェント

ケバブ屋台の売上と棚卸しからTier 1品目の在庫と消費係数を管理するPython CLI。
名前は英語の tell から（表記は常に小文字 `teruo`）。

## Run & Operate

- `python main.py` — 対話型CLIを起動（状態が空なら初回カウンセリング）
- `python main.py --setup` — カウンセリングを強制起動
- Required secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- Required env: `AWS_DEFAULT_REGION=us-east-2`

## Stack

- Python 3.12
- Strands Agents
- Amazon Bedrock / Claude Sonnet
- JSON file persistence; no database or web framework

## Where things live

- Agent and CLI: `main.py`
- Tool calculations: `tools.py`
- Atomic JSON persistence: `store.py`
- State: `data/state.json`
- Scope: `docs/teruo-design.md`（設計書B・正本）, `docs/teruo-instructions.md`（実装指示書）

## Architecture decisions

- All arithmetic runs in Python tools, never in the model.
- State writes replace the JSON file atomically to avoid partial-file corruption.
- The first stock count establishes a baseline and does not alter the coefficient.
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
