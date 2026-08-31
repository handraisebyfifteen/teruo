# キッチンカー在庫エージェント

ホットドッグの売上と棚卸しからTier 1食材の在庫と消費係数を管理するPython CLI。

## Run & Operate

- `python main.py` — 対話型CLIを起動
- Required secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- Required env: `AWS_DEFAULT_REGION=us-west-2`

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
- Scope: `docs/design.md`

## Architecture decisions

- Implement only the three specified tools and Tier 1 inventory.
- All arithmetic runs in Python tools, never in the model.
- State writes replace the JSON file atomically to avoid partial-file corruption.
- The first stock count establishes a baseline and does not alter the coefficient.

## Product

Records hot-dog sales, reports current sausage/bun stock, and reconciles physical counts.

## User preferences

- Do not add unrequested features beyond the supplied design document.

## Gotchas

- Bedrock interaction requires the AWS credentials above.
- Keep secrets out of source files and do not create `.env`.

## Pointers

- `README.md` contains operator instructions.
