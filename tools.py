"""The calculation tools exposed to the Strands agent.

計算はすべてここ（Python）で行い、AIに暗算させない。
構造変更ツールは合言葉を検証し、変更前後を settings_log に残す。
"""

from __future__ import annotations

import functools
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from strands import tool

from store import STATE_LOCK, StateConflictError, load_state, save_state


def _serialized(func):
    """ツール1回分の load→save を丸ごと直列化する。

    エージェントは棚卸しなどでツールを並列に呼ぶことがあり、
    ロックなしでは後書きが先書きを黙って潰す（実機で発生）。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with STATE_LOCK:
            return func(*args, **kwargs)

    return wrapper


TIMEZONE = ZoneInfo("Asia/Tokyo")
VENUE_TYPES = ("event", "solo")
UNIT_TYPES = ("weight", "volume", "count")
CONFLICT_MESSAGE = "他の方が先に入力したようです。もう一度お願いします"
PASSPHRASE_MESSAGE = "合言葉が違います。レシピや単位などの設定変更には合言葉が必要です。"

# 同種別の単位換算表（基準単位あたりの倍率）。別種別への換算はしない。
WEIGHT_UNITS = {"g": 1.0, "kg": 1000.0}
VOLUME_UNITS = {"ml": 1.0, "mL": 1.0, "l": 1000.0, "L": 1000.0}
COUNT_UNITS = ("枚", "本", "個", "袋", "缶", "箱", "食", "杯", "巻")

ITEM_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# 学習中（育成フェーズ）の打ち切り条件: 棚卸し5回 または 14日（設計書 原則9）
LEARNING_MAX_COUNTS = 5
LEARNING_MAX_DAYS = 14
STABLE_COEFFICIENT_BAND = 0.05


def _now() -> datetime:
    return datetime.now(TIMEZONE)


def _now_iso() -> str:
    """日時は必ずPython側で生成する。AIに日付を作らせない。"""
    return _now().isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _fmt_dt(value: str) -> str:
    try:
        return _parse_iso(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _round_one(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _display_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _find(records: list[dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    return next((record for record in records if record["id"] == record_id), None)


def _check_passphrase(state: dict[str, Any], passphrase: str) -> str | None:
    """設定済みの合言葉と照合する。未設定（初回カウンセリング中）は通す。"""
    stored = (state.get("config") or {}).get("passphrase")
    if not stored:
        return None
    if passphrase == stored:
        return None
    return PASSPHRASE_MESSAGE


def _log_setting(
    state: dict[str, Any],
    tool_name: str,
    summary: str,
    before: Any,
    after: Any,
) -> None:
    """構造変更の履歴。変更前と変更後を必ず両方残す（設計書 原則4）。"""
    state.setdefault("settings_log", []).append(
        {
            "changed_at": _now_iso(),
            "tool": tool_name,
            "summary": summary,
            "before": before,
            "after": after,
        }
    )


def _unit_kind(unit: str) -> str | None:
    if unit in WEIGHT_UNITS:
        return "weight"
    if unit in VOLUME_UNITS:
        return "volume"
    if unit in COUNT_UNITS:
        return "count"
    return None


def _conversion_factor(old_unit: str, new_unit: str) -> float | None:
    """同種別（g→kg 等）の換算倍率。別種別なら None。"""
    for table in (WEIGHT_UNITS, VOLUME_UNITS):
        if old_unit in table and new_unit in table:
            return table[old_unit] / table[new_unit]
    return None


def _growth_counts(item: dict[str, Any]) -> list[dict[str, Any]]:
    """直近の単位変更以降の棚卸し記録。単位変更で育成期として扱い直す。"""
    counts: list[dict[str, Any]] = []
    for entry in item.get("count_history", []):
        if entry.get("event") == "unit_change":
            counts = []
        elif "actual_stock" in entry:
            counts.append(entry)
    return counts


def _growth_label(item: dict[str, Any]) -> str:
    """育成フェーズの表示（設計書 原則9）。

    「学習中」は棚卸し5回または14日で必ず打ち切り、以後は言わない。
    安定しない場合は事実（直近の係数変動）を返し、原因の解釈はAIに任せる。
    """
    counts = _growth_counts(item)
    n = len(counts)
    if n == 0:
        return f"学習中（棚卸し 0回 / {LEARNING_MAX_COUNTS}回）"
    days = (_now() - _parse_iso(counts[0]["recorded_at"])).days
    if n < LEARNING_MAX_COUNTS and days < LEARNING_MAX_DAYS:
        return f"学習中（棚卸し {n}回目 / {LEARNING_MAX_COUNTS}回）"
    if n < 2:
        return "棚卸しデータ不足"
    delta = abs(
        float(counts[-1]["coefficient_after"]) - float(counts[-2]["coefficient_after"])
    )
    if delta <= STABLE_COEFFICIENT_BAND:
        return "安定"
    return (
        "係数が安定しません（直近 "
        f'{float(counts[-2]["coefficient_after"]):.2f} → '
        f'{float(counts[-1]["coefficient_after"]):.2f}）'
    )


def _save(state: dict[str, Any]) -> str | None:
    try:
        save_state(state)
    except StateConflictError:
        return CONFLICT_MESSAGE
    return None


# ---------------------------------------------------------------------------
# 日々の入力（合言葉 不要）
# ---------------------------------------------------------------------------


@tool
@_serialized
def record_sales(product_id: str, quantity: int, venue_type: str = "solo") -> str:
    """売上を記録し、商品のレシピに従ってTier 1品目の在庫を減らします。

    売上日時はPython側で自動記録するため、日付の入力は不要です。

    Args:
        product_id: 商品ID。例: kebab_sand（ケバブサンド）。
        quantity: 売上個数。0以上の整数。
        venue_type: 出店形態。"event"（イベント出店）または "solo"（単独出店）。
            店主がイベント出店だと明言した場合のみ "event" を指定する。省略時は "solo"。
    """
    if quantity < 0:
        return "売上数は0以上で指定してください。"
    if venue_type not in VENUE_TYPES:
        return '出店形態は "event" か "solo" のどちらかで指定してください。'

    state = load_state()
    product = _find(state["products"], product_id)
    if product is None:
        return f"商品ID「{product_id}」は見つかりません。"

    changes: list[str] = []
    for ingredient in product["recipe"]:
        item = _find(state["items"], ingredient["item_id"])
        if item is None or item.get("tier") != 1 or not item.get("active", True):
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
            "recorded_at": _now_iso(),
            "venue_type": venue_type,
            "product_id": product_id,
            "quantity": quantity,
        }
    )
    if conflict := _save(state):
        return conflict
    return "、".join(changes)


@tool
@_serialized
def record_count(item_id: str, actual_stock: float) -> str:
    """棚卸し実測値を記録し、前回棚卸し後の差から消費係数を補正します。

    Args:
        item_id: 品目ID。例: meat_chicken（ケバブ肉・チキン）。
        actual_stock: 棚卸しで数えた現在庫。品目の登録単位で指定する。
    """
    if actual_stock < 0:
        return "実測在庫は0以上で指定してください。"

    state = load_state()
    item = _find(state["items"], item_id)
    if item is None or item.get("tier") != 1:
        return f"Tier 1品目ID「{item_id}」は見つかりません。"

    counted_at = _now_iso()
    previous_coefficient = float(item["coefficient"])
    calculated_stock = float(item["stock"])
    last_counted = item.get("last_counted")

    warning = ""
    message: str
    if last_counted is None:
        message = (
            f'{item["name"]}は初回棚卸しのため係数は'
            f"{previous_coefficient:.2f}のままです。"
        )
    else:
        last_counted_at = _parse_iso(last_counted)
        theoretical_consumption = 0.0
        for sale in state["history"]:
            recorded_at = sale.get("recorded_at")
            product_id = sale.get("product_id")
            if (
                recorded_at is None
                or product_id is None
                or _parse_iso(recorded_at) <= last_counted_at
            ):
                continue
            product = _find(state["products"], product_id)
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
            clamped = min(1.5, max(0.8, new_coefficient))
            item["coefficient"] = round(clamped, 4)
            message = (
                f'{item["name"]}の係数を{previous_coefficient:.2f}から'
                f'{item["coefficient"]:.2f}に更新しました。'
            )
            if clamped != new_coefficient or abs(clamped - previous_coefficient) > 0.15:
                warning = " 大きくズレています。数え間違いの可能性もご確認ください。"
        else:
            message = (
                f'{item["name"]}は前回棚卸し後の売上がないため、係数は'
                f"{previous_coefficient:.2f}のままです。"
            )

    item["stock"] = _round_one(actual_stock)
    item["last_counted"] = counted_at
    item.setdefault("count_history", []).append(
        {
            "recorded_at": counted_at,
            "actual_stock": item["stock"],
            "calculated_stock": calculated_stock,
            "coefficient_before": previous_coefficient,
            "coefficient_after": float(item["coefficient"]),
        }
    )
    growth = _growth_label(item)
    growth_note = ""
    if growth.startswith("学習中"):
        growth_note = f" {growth}。数字は参考程度に見てください。"
    elif growth.startswith("係数が安定しません"):
        growth_note = f" {growth}"
    if conflict := _save(state):
        return conflict
    return (
        f"{message} 在庫を{_display_number(float(item['stock']))}"
        f'{item["unit"]}に更新しました。{warning}{growth_note}'
    ).rstrip()


@tool
@_serialized
def record_purchase(purchases: list[dict]) -> str:
    """仕入れを在庫に加算します。店主のメモをAIが読み取り、確認を得てから呼び出します。

    実際の量が分かればそれを使い、なければ1仕入れ単位あたりの目安量
    （unit_weight）で仮置きします。実測はあとの棚卸しで必ず勝ちます。

    Args:
        purchases: 仕入れ明細のリスト。各要素は次のキーを持つ辞書。
            item_id: 品目ID（必須）。
            amount: 実際に増えた量（品目の登録単位）。実測が分かる場合に指定。
            units: 仕入れ単位の数（例: 肉2本の 2）。amount が無い場合は
                units × unit_weight の目安で仮置きする。
    """
    if not purchases:
        return "仕入れ明細が空です。"

    state = load_state()
    lines: list[str] = []
    for entry in purchases:
        item_id = entry.get("item_id")
        item = _find(state["items"], item_id) if item_id else None
        if item is None or not item.get("active", True):
            return f"品目ID「{item_id}」は見つかりません。先に register_item で登録してください。"

        amount = entry.get("amount")
        units = entry.get("units")
        estimated = False
        if amount is None:
            if units is None:
                return f'{item["name"]}: amount か units のどちらかが必要です。'
            unit_weight = item.get("unit_weight")
            if unit_weight:
                # 仕入れ単位あり（1本10kg、1袋10枚 など）は目安量で換算する
                amount = float(units) * float(unit_weight)
                estimated = True
            elif item.get("unit_type") == "count":
                amount = float(units)
            else:
                return (
                    f'{item["name"]}: 1{item.get("purchase_unit", "単位")}あたりの量が'
                    "未設定のため、実際の量（amount）を指定してください。"
                )
        amount = float(amount)
        if amount < 0:
            return f'{item["name"]}: 仕入れ量は0以上で指定してください。'

        before = float(item["stock"])
        after = _round_one(before + amount)
        item["stock"] = after

        # 実測（amount）と本数（units）が両方あれば「1本=何g」の実績を学習する
        if (
            not estimated
            and units
            and item.get("unit_type") in ("weight", "volume")
            and item.get("purchase_unit")
        ):
            samples = item.setdefault("unit_weight_samples", [])
            samples.append(_round_one(amount / float(units)))
            item["unit_weight"] = _round_one(sum(samples) / len(samples))

        state["history"].append(
            {
                "recorded_at": _now_iso(),
                "type": "purchase",
                "item_id": item["id"],
                "amount": amount,
                "units": units,
                "estimated": estimated,
            }
        )
        note = "（目安で仮置き。実際の量が分かれば教えてください）" if estimated else ""
        lines.append(
            f'{item["name"]} +{_display_number(amount)}{item["unit"]}'
            f'（{_display_number(before)} → {_display_number(after)}{item["unit"]}）{note}'
        )

    if conflict := _save(state):
        return conflict
    return "仕入れを記録しました。\n" + "\n".join(lines)


@tool
@_serialized
def get_stock_status() -> str:
    """全Tier 1品目の現在庫、係数、育成フェーズ、最終棚卸し、直近の設定変更を返します。"""
    state = load_state()
    lines: list[str] = []
    for item in state["items"]:
        if item.get("tier") != 1 or not item.get("active", True):
            continue
        last_counted = item.get("last_counted")
        last_display = _fmt_dt(last_counted) if last_counted else "未実施"
        lines.append(
            f'- {item["name"]}: {_display_number(float(item["stock"]))}'
            f'{item["unit"]}、係数 {float(item["coefficient"]):.2f}、'
            f"{_growth_label(item)}、最終棚卸し {last_display}"
        )

    settings_log = state.get("settings_log", [])
    if settings_log:
        lines.append("")
        lines.append("直近の設定変更:")
        for entry in settings_log[-5:]:
            lines.append(f'- {_fmt_dt(entry["changed_at"])} {entry["summary"]}')
    return "\n".join(lines)


@tool
@_serialized
def get_sales_summary() -> str:
    """出店形態（イベント / 単独）別に、1営業日あたりの商品別平均販売数を返します。

    イベントと単独は客層も規模も違うため、混ぜずに別々に平均します。
    """
    state = load_state()
    sales = [
        entry
        for entry in state["history"]
        if entry.get("product_id") is not None and entry.get("recorded_at")
    ]
    if not sales:
        return "まだ売上記録がありません。"

    venue_names = {"event": "イベント出店", "solo": "単独出店"}
    blocks: list[str] = []
    for venue in VENUE_TYPES:
        venue_sales = [s for s in sales if s.get("venue_type", "solo") == venue]
        if not venue_sales:
            continue
        days = {_parse_iso(s["recorded_at"]).date() for s in venue_sales}
        totals: dict[str, float] = {}
        for sale in venue_sales:
            totals[sale["product_id"]] = totals.get(sale["product_id"], 0.0) + float(
                sale["quantity"]
            )
        lines = [f"{venue_names[venue]}（営業日数 {len(days)}日）:"]
        for product_id, total in totals.items():
            product = _find(state["products"], product_id)
            name = product["name"] if product else product_id
            average = _round_one(total / len(days))
            lines.append(
                f"- {name}: 合計{_display_number(total)}個、"
                f"1日平均 {_display_number(average)}個"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


@tool
@_serialized
def get_capacity() -> str:
    """現在庫で各商品があと何食作れるか（ボトルネック品目つき）を返します。

    残数の計算はすべてPython側で行います。売上の見込みには使わず、
    在庫が持つかどうかの判断材料として使ってください。
    """
    state = load_state()
    if not state["products"]:
        return "商品が登録されていません。"
    lines: list[str] = []
    for product in state["products"]:
        servings: float | None = None
        bottleneck = ""
        missing = ""
        for ingredient in product["recipe"]:
            item = _find(state["items"], ingredient["item_id"])
            if item is None or not item.get("active", True):
                missing = ingredient["item_id"]
                break
            if item.get("tier") != 1:
                continue
            per_serving = float(ingredient["qty"]) * float(item["coefficient"])
            if per_serving <= 0:
                continue
            possible = float(item["stock"]) / per_serving
            if servings is None or possible < servings:
                servings = possible
                bottleneck = item["name"]
        if missing:
            lines.append(
                f'- {product["name"]}: 計算不可（品目「{missing}」が未登録または無効）'
            )
        elif servings is None:
            lines.append(f'- {product["name"]}: レシピにTier 1品目がありません')
        else:
            lines.append(
                f'- {product["name"]}: あと{int(servings)}食'
                f"（ボトルネック: {bottleneck}）"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 構造変更（合言葉 必要・変更履歴を残す）
# ---------------------------------------------------------------------------


@tool
@_serialized
def register_item(
    item_id: str,
    name: str,
    unit: str,
    unit_type: str,
    stock: float,
    tier: int = 1,
    purchase_unit: str = "",
    unit_weight: float = 0.0,
    passphrase: str = "",
) -> str:
    """品目（材料・消耗品）を追加します。構造変更のため合言葉が必要です。

    係数は必ず1.0から始めます（店主に決めさせない）。実測が育てます。

    Args:
        item_id: 英小文字スネークケースのID。例: sauce_yogurt。AIが命名する。
        name: 表示名。例: ソース（ヨーグルト）。
        unit: 消費単位。例: g、枚、本、個。
        unit_type: "weight"（重量）/ "volume"（容量）/ "count"（個数）。
        stock: 現在庫。ざっくりで良い。
        tier: 管理区分。今回は1のみ運用。仮判定でよい。
        purchase_unit: 仕入れ単位が消費単位と違う場合のみ。例: 本、袋。
        unit_weight: 1仕入れ単位あたりの目安量。purchase_unit がある場合のみ。
        passphrase: 店主の合言葉。
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    if not ITEM_ID_PATTERN.match(item_id):
        return "item_id は英小文字とアンダースコアで指定してください。例: sauce_yogurt"
    if _find(state["items"], item_id) is not None:
        return f"品目ID「{item_id}」は既に存在します。別のIDを使ってください。"
    if unit_type not in UNIT_TYPES:
        return 'unit_type は "weight" / "volume" / "count" のいずれかです。'
    if stock < 0:
        return "在庫は0以上で指定してください。"

    item: dict[str, Any] = {
        "id": item_id,
        "name": name,
        "tier": tier,
        "unit": unit,
        "unit_type": unit_type,
        "stock": _round_one(stock),
        "coefficient": 1.0,
        "last_counted": None,
        "count_history": [],
        "active": True,
    }
    if purchase_unit:
        item["purchase_unit"] = purchase_unit
        if unit_weight > 0:
            item["unit_weight"] = unit_weight
    state["items"].append(item)
    _log_setting(
        state,
        "register_item",
        f"品目を追加: {name}（{_display_number(float(stock))}{unit}）",
        None,
        {k: item[k] for k in ("id", "name", "unit", "stock")},
    )
    if conflict := _save(state):
        return conflict
    return (
        f"{name}を登録しました（{_display_number(float(stock))}{unit}、係数1.00から学習開始）。"
    )


@tool
@_serialized
def register_product(
    product_id: str,
    name: str,
    price: int,
    recipe: list[dict],
    passphrase: str = "",
) -> str:
    """商品（メニュー）を追加します。構造変更のため合言葉が必要です。

    レシピ中に未登録の品目があれば、先に register_item で登録してから
    呼び出してください（店主に順序を意識させないのはAIの仕事）。

    Args:
        product_id: 英小文字スネークケースのID。例: kebab_sand。
        name: 表示名。例: ケバブサンド。
        price: 税込価格（円）。
        recipe: 材料リスト。各要素は {"item_id": 品目ID, "qty": 1食あたりの量} の辞書。
        passphrase: 店主の合言葉。
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    if not ITEM_ID_PATTERN.match(product_id):
        return "product_id は英小文字とアンダースコアで指定してください。"
    if _find(state["products"], product_id) is not None:
        return f"商品ID「{product_id}」は既に存在します。"
    if price < 0:
        return "価格は0以上で指定してください。"
    if not recipe:
        return "レシピが空です。材料を1つ以上指定してください。"

    seen: set[str] = set()
    missing: list[str] = []
    for ingredient in recipe:
        item_id = ingredient.get("item_id")
        qty = ingredient.get("qty")
        if not item_id or qty is None or float(qty) <= 0:
            return "レシピの各要素には item_id と 0より大きい qty が必要です。"
        if item_id in seen:
            return f"品目「{item_id}」がレシピに重複しています。"
        seen.add(item_id)
        item = _find(state["items"], item_id)
        if item is None or not item.get("active", True):
            missing.append(item_id)
    if missing:
        return (
            "次の品目が未登録です。先に register_item で登録してください: "
            + ", ".join(missing)
        )

    product = {
        "id": product_id,
        "name": name,
        "price": price,
        "recipe": [
            {"item_id": i["item_id"], "qty": float(i["qty"])} for i in recipe
        ],
    }
    state["products"].append(product)
    recipe_text = "、".join(
        f'{_find(state["items"], i["item_id"])["name"]} '
        f'{_display_number(float(i["qty"]))}'
        f'{_find(state["items"], i["item_id"])["unit"]}'
        for i in product["recipe"]
    )
    _log_setting(
        state,
        "register_product",
        f"商品を追加: {name}（¥{price}） レシピ: {recipe_text}",
        None,
        product,
    )
    if conflict := _save(state):
        return conflict
    return f"{name}（¥{price}）を登録しました。レシピ: {recipe_text}"


@tool
@_serialized
def update_recipe(
    product_id: str,
    item_id: str,
    qty: float,
    passphrase: str = "",
) -> str:
    """商品レシピの1材料を変更・追加・削除します。構造変更のため合言葉が必要です。

    Args:
        product_id: 商品ID。
        item_id: 品目ID。
        qty: 1食あたりの新しい量。0を指定するとその材料をレシピから外す。
        passphrase: 店主の合言葉。
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    product = _find(state["products"], product_id)
    if product is None:
        return f"商品ID「{product_id}」は見つかりません。"
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return f"品目ID「{item_id}」は未登録です。先に register_item で登録してください。"
    if qty < 0:
        return "qty は0以上で指定してください（0で材料を外す）。"

    existing = next(
        (i for i in product["recipe"] if i["item_id"] == item_id), None
    )
    unit = item["unit"]
    if qty == 0:
        if existing is None:
            return f'{product["name"]}のレシピに{item["name"]}は入っていません。'
        product["recipe"] = [
            i for i in product["recipe"] if i["item_id"] != item_id
        ]
        summary = (
            f'{product["name"]}のレシピ: {item["name"]} '
            f'{_display_number(float(existing["qty"]))}{unit} → 削除'
        )
        before, after = float(existing["qty"]), None
        message = f'{product["name"]}のレシピから{item["name"]}を外しました。'
    elif existing is None:
        product["recipe"].append({"item_id": item_id, "qty": float(qty)})
        summary = (
            f'{product["name"]}のレシピ: {item["name"]} '
            f"なし → {_display_number(float(qty))}{unit}"
        )
        before, after = None, float(qty)
        message = (
            f'{product["name"]}のレシピに{item["name"]} '
            f"{_display_number(float(qty))}{unit}を追加しました。"
        )
    else:
        before = float(existing["qty"])
        existing["qty"] = float(qty)
        summary = (
            f'{product["name"]}のレシピ: {item["name"]} '
            f"{_display_number(before)}{unit} → {_display_number(float(qty))}{unit}"
        )
        after = float(qty)
        message = (
            f'{product["name"]}の{item["name"]}を{_display_number(before)}{unit}から'
            f"{_display_number(float(qty))}{unit}に変更しました。"
        )
    _log_setting(state, "update_recipe", summary, before, after)
    if conflict := _save(state):
        return conflict
    return message


@tool
@_serialized
def update_item(
    item_id: str,
    new_name: str = "",
    new_unit: str = "",
    new_stock: float = -1.0,
    new_purchase_unit: str = "",
    new_unit_weight: float = 0.0,
    passphrase: str = "",
) -> str:
    """品目の名前・単位・仕入れ単位を修正します。構造変更のため合言葉が必要です。

    単位変更のルール:
    - 同種別（g→kg など）は在庫・レシピ・目安量を自動換算する。
    - 別種別（g→本 など）は換算できないため、new_stock で数え直した在庫が必須。
      係数は1.0に戻り、育成期として扱い直す（過去の記録は残る）。

    Args:
        item_id: 品目ID。
        new_name: 新しい表示名（変更する場合のみ）。
        new_unit: 新しい消費単位（変更する場合のみ）。例: kg、本。
        new_stock: 別種別への単位変更時に、数え直した現在庫（新単位）。
        new_purchase_unit: 仕入れ単位（後から分かった場合の設定・変更）。例: 本、袋。
        new_unit_weight: 1仕入れ単位あたりの目安量（消費単位）。例: 1本10kgなら10000。
        passphrase: 店主の合言葉。
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return f"品目ID「{item_id}」は見つかりません。"
    if not new_name and not new_unit and not new_purchase_unit and new_unit_weight <= 0:
        return "変更内容（new_name / new_unit / new_purchase_unit / new_unit_weight）を指定してください。"

    messages: list[str] = []

    if new_purchase_unit or new_unit_weight > 0:
        if not new_purchase_unit and not item.get("purchase_unit"):
            return "目安量だけは登録できません。仕入れ単位（new_purchase_unit）も指定してください。"
        before_purchase = {
            "purchase_unit": item.get("purchase_unit"),
            "unit_weight": item.get("unit_weight"),
        }
        if new_purchase_unit:
            item["purchase_unit"] = new_purchase_unit
        if new_unit_weight > 0:
            item["unit_weight"] = new_unit_weight
        purchase_unit = item["purchase_unit"]
        weight_note = (
            f'（1{purchase_unit} ≒ {_display_number(float(item["unit_weight"]))}{item["unit"]}）'
            if item.get("unit_weight")
            else ""
        )
        _log_setting(
            state,
            "update_item",
            f'{item["name"]}の仕入れ単位を設定: {purchase_unit}{weight_note}',
            before_purchase,
            {
                "purchase_unit": item.get("purchase_unit"),
                "unit_weight": item.get("unit_weight"),
            },
        )
        messages.append(
            f"仕入れ単位を{purchase_unit}{weight_note}として登録しました。"
            "実際の量が分かったら仕入れ時に教えてください。実測で目安を更新します。"
        )

    if new_name and new_name != item["name"]:
        old_name = item["name"]
        item["name"] = new_name
        _log_setting(
            state,
            "update_item",
            f"品目名を変更: {old_name} → {new_name}",
            old_name,
            new_name,
        )
        messages.append(f"名前を{old_name}から{new_name}に変更しました。")

    if new_unit and new_unit != item["unit"]:
        old_unit = item["unit"]
        old_stock = float(item["stock"])
        old_coefficient = float(item["coefficient"])
        factor = _conversion_factor(old_unit, new_unit)
        before_snapshot = {
            "unit": old_unit,
            "unit_type": item["unit_type"],
            "stock": old_stock,
            "coefficient": old_coefficient,
        }

        if factor is not None:
            # 同種別: 在庫・レシピ・目安量を機械的に換算。係数は意味が変わらないので維持
            item["unit"] = new_unit
            item["stock"] = _round_one(old_stock * factor)
            if item.get("unit_weight"):
                item["unit_weight"] = float(item["unit_weight"]) * factor
            affected: list[str] = []
            for product in state["products"]:
                for ingredient in product["recipe"]:
                    if ingredient["item_id"] == item_id:
                        ingredient["qty"] = float(ingredient["qty"]) * factor
                        affected.append(product["name"])
            _log_setting(
                state,
                "update_item",
                f'{item["name"]}の単位を変更: {old_unit} → {new_unit}'
                f"（在庫 {_display_number(old_stock)}{old_unit} → "
                f'{_display_number(float(item["stock"]))}{new_unit}、レシピも換算）',
                before_snapshot,
                {"unit": new_unit, "stock": item["stock"]},
            )
            note = f"レシピ（{'、'.join(dict.fromkeys(affected))}）も換算済み。" if affected else ""
            messages.append(
                f'単位を{old_unit}から{new_unit}に換算しました'
                f'（在庫 {_display_number(float(item["stock"]))}{new_unit}）。{note}'
            )
        else:
            # 別種別: 換算しない。数え直しが必須（設計書 2-4）
            new_kind = _unit_kind(new_unit)
            if new_stock < 0:
                return (
                    f'{item["name"]}の単位を{old_unit}から{new_unit}に変えるには換算ができません。'
                    f"現在の在庫 {_display_number(old_stock)}{old_unit} を数え直す必要があります。"
                    f"いま何{new_unit}あるか教えてください（new_stock で指定）。"
                )
            item["unit"] = new_unit
            if new_kind:
                item["unit_type"] = new_kind
            item["stock"] = _round_one(new_stock)
            item["coefficient"] = 1.0
            item["last_counted"] = None
            item.setdefault("count_history", []).append(
                {
                    "recorded_at": _now_iso(),
                    "event": "unit_change",
                    "before": before_snapshot,
                    "after": {
                        "unit": new_unit,
                        "unit_type": item["unit_type"],
                        "stock": item["stock"],
                        "coefficient": 1.0,
                    },
                }
            )
            affected_products = [
                product["name"]
                for product in state["products"]
                if any(i["item_id"] == item_id for i in product["recipe"])
            ]
            _log_setting(
                state,
                "update_item",
                f'{item["name"]}の単位を変更: {old_unit} → {new_unit}'
                f"（在庫 {_display_number(old_stock)}{old_unit} → "
                f"{_display_number(float(new_stock))}{new_unit}、係数1.0に戻して学習し直し）",
                before_snapshot,
                {
                    "unit": new_unit,
                    "unit_type": item["unit_type"],
                    "stock": item["stock"],
                    "coefficient": 1.0,
                },
            )
            warning = (
                f"レシピ（{'、'.join(affected_products)}）の数量は旧単位のままです。"
                "update_recipe で新単位の量に直してください。"
                if affected_products
                else ""
            )
            messages.append(
                f"単位を{old_unit}から{new_unit}に変更し、在庫を"
                f"{_display_number(float(new_stock))}{new_unit}で数え直しました。"
                f"係数は1.0に戻し、学習し直します。{warning}"
            )
    elif new_unit:
        messages.append(f"単位は既に{new_unit}です。")

    if conflict := _save(state):
        return conflict
    return " ".join(messages) if messages else "変更はありませんでした。"


@tool
@_serialized
def delete_product(
    product_id: str,
    confirm: bool = False,
    passphrase: str = "",
) -> str:
    """商品を削除します。確認必須・構造変更のため合言葉が必要です。

    商品を消しても、品目（材料）と売上履歴は消えません。
    店主が削除の意思を明確に確認できてから confirm=True で呼び出してください。

    Args:
        product_id: 商品ID。
        confirm: 店主が削除を承認した場合のみ True。
        passphrase: 店主の合言葉。
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    product = _find(state["products"], product_id)
    if product is None:
        return f"商品ID「{product_id}」は見つかりません。"
    if not confirm:
        return (
            f'{product["name"]}（¥{product["price"]}）を削除しようとしています。'
            "一度消すと商品は戻せません（品目と売上履歴は残ります）。"
            "本当に削除してよいか店主に確認し、承認されたら confirm=True で"
            "もう一度呼び出してください。"
        )
    state["products"] = [p for p in state["products"] if p["id"] != product_id]
    _log_setting(
        state,
        "delete_product",
        f'商品を削除: {product["name"]}（¥{product["price"]}）',
        product,
        None,
    )
    if conflict := _save(state):
        return conflict
    return f'{product["name"]}を削除しました。品目と売上履歴は残っています。'


@tool
@_serialized
def update_config(
    passphrase: str = "",
    new_passphrase: str = "",
    new_notify_email: str = "",
) -> str:
    """合言葉・設定変更の通知先メールアドレスを設定します。

    初回（未設定時）はそのまま登録できます。変更時は現在の合言葉が必要です。

    Args:
        passphrase: 現在の合言葉（変更時のみ必要）。
        new_passphrase: 新しい合言葉。
        new_notify_email: 設定変更を知らせるメールアドレス。
    """
    if not new_passphrase and not new_notify_email:
        return "設定内容（new_passphrase または new_notify_email）を指定してください。"
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    config = state.setdefault("config", {"passphrase": None, "notify_email": None})
    messages: list[str] = []
    if new_passphrase:
        config["passphrase"] = new_passphrase
        _log_setting(state, "update_config", "合言葉を設定しました", None, "（非表示）")
        messages.append("合言葉を設定しました。レシピや単位の変更時に必要になります。")
    if new_notify_email:
        old_email = config.get("notify_email")
        config["notify_email"] = new_notify_email
        _log_setting(
            state,
            "update_config",
            f"通知先メールを設定: {new_notify_email}",
            old_email,
            new_notify_email,
        )
        messages.append(f"通知先を{new_notify_email}に設定しました。")
    if conflict := _save(state):
        return conflict
    return " ".join(messages)
