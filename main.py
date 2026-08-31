"""Interactive CLI for the kitchen-car inventory agent."""

from __future__ import annotations

import os
import sys

from strands import Agent

from tools import get_stock_status, record_count, record_sales


SYSTEM_PROMPT = """あなたはキッチンカーの在庫管理を手伝うアシスタントです。
店主は忙しいので、質問は最小限にしてください。

- 売上を伝えられたら record_sales を使って記録する
- 棚卸しの数を伝えられたら record_count を使う
- 在庫を聞かれたら get_stock_status を使う
- 数値の計算は必ずツールを使い、自分で暗算しない
- 係数が大きく動いたときは、数え間違いの可能性も店主に確認する
- 丁寧語で、簡潔に応答する
"""

REQUIRED_ENVIRONMENT = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
)


def validate_environment() -> None:
    missing = [name for name in REQUIRED_ENVIRONMENT if not os.environ.get(name)]
    if missing:
        print(
            "起動に必要なReplit Secrets / 環境変数がありません: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> None:
    validate_environment()
    agent = Agent(
        system_prompt=SYSTEM_PROMPT,
        tools=[record_sales, record_count, get_stock_status],
    )
    print("キッチンカー在庫エージェントです。終了するには exit と入力してください。")
    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue
        try:
            agent(user_input)
        except Exception as error:
            print(f"処理できませんでした: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
