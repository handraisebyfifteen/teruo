"""The three calculation tools exposed to the Strands agent."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from strands import tool

from store import load_state, save_state


def _round_one(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _display_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _find(records: list[dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    return next((record for record in records if record["id"] == record_id), None)


@tool
def record_sales(date: str, product_id: str, quantity: int) -> str:
    """売上を記録し、商品のレシピに従ってTier 1品目の在庫を減らします。

    Args:
        date: 売上日。YYYY-MM-DD形式。
        product_id: 商品ID。ホットドッグは hotdog。
        quantity: 売上個数。0以上の整数。
    """
    if quantity < 0:
        return "売上数は0以上で指定してください。"

    state = load_state()
    product = _find(state["products"], product_id)
    if product is None:
        return f"商品ID「{product_id}」は見つかりません。"

    changes: list[str] = []
    for ingredient in product["recipe"]:
        item = _find(state["items"], ingredient["item_id"])
        if item is None or item.get("tier") != 1:
            continue
        before = float(item["stock"])
        consumed = _round_one(
            quantity * float(ingredient["qty"]) * float(item["coefficient"])
        )
        after = _round_one(before - consumed)
        item["stock"] = after
        changes.append(
            f'{item["name"]} {_display_number(before)} → '
            f'{_display_number(after)}{item["unit"]}'
            f'（{_display_number(consumed)}{item["unit"]}減）'
        )

    state["history"].append(
        {
            "date": date,
            "product_id": product_id,
            "quantity": quantity,
            "recorded_at": datetime.now().astimezone().isoformat(),
        }
    )
    save_state(state)
    return "、".join(changes)


@tool
def record_count(item_id: str, actual_stock: float) -> str:
    """棚卸し実測値を記録し、前回棚卸し後の差から消費係数を補正します。

    Args:
        item_id: 品目ID。sausage または bun。
        actual_stock: 棚卸しで数えた現在庫。
    """
    if actual_stock < 0:
        return "実測在庫は0以上で指定してください。"

    state = load_state()
    item = _find(state["items"], item_id)
    if item is None or item.get("tier") != 1:
        return f"Tier 1品目ID「{item_id}」は見つかりません。"

    counted_at = datetime.now().astimezone().isoformat()
    previous_coefficient = float(item["coefficient"])
    calculated_stock = float(item["stock"])
    last_counted = item.get("last_counted")

    message: str
    if last_counted is None:
        message = (
            f'{item["name"]}は初回棚卸しのため係数は'
            f"{previous_coefficient:.2f}のままです。"
        )
    else:
        theoretical_consumption = 0.0
        for sale in state["history"]:
            if sale.get("recorded_at", "") <= last_counted:
                continue
            product = _find(state["products"], sale["product_id"])
            if product is None:
                continue
            recipe = next(
                (
                    ingredient
                    for ingredient in product["recipe"]
                    if ingredient["item_id"] == item_id
                ),
                None,
            )
            if recipe:
                theoretical_consumption += (
                    float(sale["quantity"])
                    * float(recipe["qty"])
                    * previous_coefficient
                )

        if theoretical_consumption > 0:
            actual_consumption = theoretical_consumption + (
                calculated_stock - actual_stock
            )
            new_coefficient = previous_coefficient * (
                actual_consumption / theoretical_consumption
            )
            new_coefficient = min(1.5, max(0.8, new_coefficient))
            item["coefficient"] = round(new_coefficient, 4)
            message = (
                f'{item["name"]}の係数を{previous_coefficient:.2f}から'
                f'{item["coefficient"]:.2f}に更新しました。'
            )
        else:
            message = (
                f'{item["name"]}は前回棚卸し後の売上がないため、係数は'
                f"{previous_coefficient:.2f}のままです。"
            )

    item["stock"] = _round_one(actual_stock)
    item["last_counted"] = counted_at
    save_state(state)
    return (
        f"{message} 在庫を{_display_number(float(item['stock']))}"
        f'{item["unit"]}に更新しました。'
    )


@tool
def get_stock_status() -> str:
    """全Tier 1品目の現在庫、単位、係数、最終棚卸し日時を返します。"""
    state = load_state()
    lines: list[str] = []
    for item in state["items"]:
        if item.get("tier") != 1:
            continue
        last_counted = item.get("last_counted") or "未実施"
        lines.append(
            f'- {item["name"]}: {_display_number(float(item["stock"]))}'
            f'{item["unit"]}、係数 {float(item["coefficient"]):.2f}、'
            f"最終棚卸し {last_counted}"
        )
    return "\n".join(lines)