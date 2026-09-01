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
# 消費型の3分類（設計書2章）。数え方の軸で、unit_type（単位の種別）とは別。
CONSUMPTION_TYPES = ("count", "weight", "unit")
CONFLICT_MESSAGE = "他の方が先に入力したようです。もう一度お願いします"
PASSPHRASE_MESSAGE = "合言葉が違います。レシピや単位などの設定変更には合言葉が必要です。"
NEGATIVE_STOCK_DISPLAY = "実測が必要です（理論値が在庫を割りました）"

# 同種別の単位換算表（基準単位あたりの倍率）。別種別への換算はしない。
WEIGHT_UNITS = {"g": 1.0, "kg": 1000.0}
VOLUME_UNITS = {"ml": 1.0, "mL": 1.0, "l": 1000.0, "L": 1000.0}
COUNT_UNITS = ("枚", "本", "個", "袋", "缶", "箱", "食", "杯", "巻")

ITEM_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# 学習中（育成フェーズ）の打ち切り条件: 棚卸し5回 または 14日（設計書 原則9）
LEARNING_MAX_COUNTS = 5
LEARNING_MAX_DAYS = 14
STABLE_COEFFICIENT_BAND = 0.05

# 係数の上限（設計書2章）。盛り方のブレは物理的に1食±3〜4gが限度。
WEIGHT_BOUND_PER_SERVING = 4.0
# 係数更新の平滑化。実測1回分の補正をそのまま採ると日ごとの手のブレ（±5%程度）を
# 全量追いかけて振動する（収束シミュレーションで確認）。半分ずつ寄せると
# 5回でほぼ収束したまま、振れ幅が半減する。
COEFFICIENT_SMOOTHING = 0.5
# ユニット型: 過去実績の±20%。実績3回そろうまで上限判定しない。
UNIT_BOUND_RATIO = 0.2
UNIT_BOUND_MIN_SAMPLES = 3
UNIT_LEARNING_SAMPLES = 3


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


# 事実（ツールの確定出力）はPythonが直接画面に出す（原則3: 計算はPython、判断はAI）。
# LLMの要約で明細が欠けたり数字が変わるのを防ぐ。seed_demo.py 等は False にして黙らせる。
DIRECT_OUTPUT = True

TOLD_MARKER = "[画面に表示済み。内容を繰り返さず、必要な判断や次の一手だけ短く添える]"


def _tell(text: str) -> str:
    """確定出力を stdout に直接印字し、LLMには復唱しないよう印を付けて渡す。"""
    if DIRECT_OUTPUT:
        print(text, flush=True)
        return f"{TOLD_MARKER}\n{text}"
    return text


def _find(records: list[dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    return next((record for record in records if record["id"] == record_id), None)


def _consumption_type(item: dict[str, Any]) -> str:
    """消費型。未設定の既存データは unit_type から補う（count→count、他→weight）。"""
    value = item.get("consumption_type")
    if value in CONSUMPTION_TYPES:
        return value
    return "count" if item.get("unit_type") == "count" else "weight"


def _display_stock(item: dict[str, Any]) -> str:
    """在庫の表示。負値は内部に保持したまま、数字を出さない（設計書 原則10）。"""
    stock = float(item["stock"])
    if stock < 0:
        return NEGATIVE_STOCK_DISPLAY
    return f'{_display_number(stock)}{item["unit"]}'


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
    ユニット型は使い切り実績の回数で数える（設計書2章）。
    """
    ctype = _consumption_type(item)
    if ctype == "count":
        return "係数固定"
    if ctype == "unit":
        n = len(item.get("unit_history", []))
        if n == 0:
            return "未学習（最初の使い切り待ち）"
        if n < UNIT_LEARNING_SAMPLES:
            return f"学習中（使い切り {n}回 / {UNIT_LEARNING_SAMPLES}回）"
        return f"安定（実績{n}回）"
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
    """売上を記録し、商品のレシピに従って品目の在庫を減らします。

    消費型ごとに動きが違います（設計書2章）:
    count型は数どおり、weight型はレシピ×係数で減算。
    unit型（ソース等）は累計食数だけ数え、在庫は使い切りの記録で動きます。
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
    notes: list[str] = []
    for ingredient in product["recipe"]:
        item = _find(state["items"], ingredient["item_id"])
        if item is None or not item.get("active", True):
            continue
        ctype = _consumption_type(item)
        qty = float(ingredient["qty"])

        if ctype == "unit":
            # 途中の残量は測れない。累計食数だけ数える（在庫は record_unit_used が動かす）
            item["sales_count"] = float(item.get("sales_count", 0)) + quantity * qty
            coefficient = item.get("coefficient")
            opened_at = item.get("opened_at_sales_count")
            used_note = ""
            if opened_at is not None:
                used = int(round(float(item["sales_count"]) - float(opened_at)))
                used_note = f'、開封中の1{item["unit"]}は{used}食目'
            changes.append(
                f'{item["name"]} 在庫は動かしません'
                f'（累計{_display_number(float(item["sales_count"]))}食{used_note}）'
            )
            if coefficient and opened_at is not None:
                remaining = float(coefficient) - used
                if remaining <= max(5.0, float(coefficient) * 0.1):
                    notes.append(
                        f'{item["name"]}: 開封中の1{item["unit"]}がそろそろ空きます'
                        f'（推定あと{max(0, int(remaining))}食分）。空いたら教えてください'
                    )
            continue

        coefficient = float(item["coefficient"]) if ctype == "weight" else 1.0
        before = float(item["stock"])
        consumed = _round_one(quantity * qty * coefficient)
        after = _round_one(before - consumed)
        item["stock"] = after
        if after < 0 <= before:
            # 負値は保持し、数字を出さない（設計書 原則10）。エラーでは止めない
            changes.append(
                f'{item["name"]} 理論値が在庫を割りました。実際にはまだ残っているはずです。'
                "こちらの計算が少なく見積もっていました。締めに一度量ってください"
            )
        elif after < 0:
            changes.append(f'{item["name"]} {NEGATIVE_STOCK_DISPLAY}')
        else:
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
    lines = [f'{product["name"]} {quantity}個を記録しました。']
    lines.extend(f"- {change}" for change in changes)
    lines.extend(notes)
    return _tell("\n".join(lines))


@tool
@_serialized
def record_count(item_id: str, actual_stock: float) -> str:
    """棚卸し実測値を記録します。weight型は前回棚卸し後の差から消費係数を補正します。

    count型は数え直しのみ（係数は1.0固定）。unit型はユニット数の数え直しのみで、
    係数は使い切りの記録（record_unit_used）で確定します。

    Args:
        item_id: 品目ID。例: meat_chicken（ケバブ肉・チキン）。
        actual_stock: 棚卸しで数えた現在庫。品目の登録単位で指定する。
            unit型は開封中のものも1と数えたユニット数。
    """
    if actual_stock < 0:
        return "実測在庫は0以上で指定してください。"

    state = load_state()
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return f"品目ID「{item_id}」は見つかりません。"

    ctype = _consumption_type(item)
    counted_at = _now_iso()
    previous_coefficient = float(item.get("coefficient") or 1.0)
    calculated_stock = float(item["stock"])
    last_counted = item.get("last_counted")

    warning = ""
    message: str
    if ctype == "unit":
        message = (
            f'{item["name"]}のユニット数を数え直しました。'
            f'「1{item["unit"]}＝何食分」は使い切りの記録で確定します。'
        )
    elif ctype == "count":
        difference = _round_one(calculated_stock - actual_stock)
        if difference == 0:
            message = f'{item["name"]}は理論値どおりです。'
        else:
            # 数で管理する品目の差は係数では説明できない。事実だけ返す（原則12）
            direction = "少ない" if difference > 0 else "多い"
            message = (
                f'{item["name"]}は理論値より{_display_number(abs(difference))}'
                f'{item["unit"]}{direction}実測でした。数で管理する品目のため、'
                "記録漏れや廃棄がなかったかご確認ください。"
            )
    elif last_counted is None:
        message = (
            f'{item["name"]}は初回棚卸しのため係数は'
            f"{previous_coefficient:.2f}のままです。"
        )
    else:
        last_counted_at = _parse_iso(last_counted)
        theoretical_consumption = 0.0
        recipe_consumption = 0.0
        servings = 0.0
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
                quantity = float(sale["quantity"])
                theoretical_consumption += (
                    quantity * float(recipe["qty"]) * previous_coefficient
                )
                recipe_consumption += quantity * float(recipe["qty"])
                servings += quantity

        if theoretical_consumption > 0:
            actual_consumption = theoretical_consumption + (
                calculated_stock - actual_stock
            )
            measured_coefficient = previous_coefficient * (
                actual_consumption / theoretical_consumption
            )
            # 平滑化: 実測1回に全量は寄せず、半分だけ寄せる（振動対策）
            new_coefficient = previous_coefficient + COEFFICIENT_SMOOTHING * (
                measured_coefficient - previous_coefficient
            )
            # 係数の上限: レシピ値±4g/食（設計書2章）。盛り付けのブレの物理限界
            base_per_serving = recipe_consumption / servings
            lower = max(0.0, base_per_serving - WEIGHT_BOUND_PER_SERVING) / base_per_serving
            upper = (base_per_serving + WEIGHT_BOUND_PER_SERVING) / base_per_serving
            clamped = min(upper, max(lower, new_coefficient))
            item["coefficient"] = round(clamped, 4)
            message = (
                f'{item["name"]}の係数を{previous_coefficient:.2f}から'
                f'{item["coefficient"]:.2f}に更新しました。'
            )
            if clamped != new_coefficient:
                warning = (
                    f' 係数が盛り付けで説明できる範囲'
                    f'（レシピ値±{_display_number(WEIGHT_BOUND_PER_SERVING)}'
                    f'{item["unit"]}/食）の上限に達しています。'
                    "これ以上は自動で調整しません。"
                    "レシピそのものの見直しが必要かもしれません。"
                )
            elif abs(clamped - previous_coefficient) > 0.15:
                warning = " 大きくズレています。数え間違いの可能性もご確認ください。"
        else:
            message = (
                f'{item["name"]}は前回棚卸し後の売上がないため、係数は'
                f"{previous_coefficient:.2f}のままです。"
            )

    label_before = _growth_label(item)
    item["stock"] = _round_one(actual_stock)
    item["last_counted"] = counted_at
    item.setdefault("count_history", []).append(
        {
            "recorded_at": counted_at,
            "actual_stock": item["stock"],
            "calculated_stock": calculated_stock,
            "coefficient_before": previous_coefficient,
            "coefficient_after": float(item.get("coefficient") or 1.0),
        }
    )
    growth = _growth_label(item)
    growth_note = ""
    if ctype == "weight" and label_before.startswith("学習中") and not growth.startswith("学習中"):
        # 学習終了時に初期値と確定値の差を必ず見せる。黙って確定させない（設計書2章）
        recipe_values = [
            float(ingredient["qty"])
            for product in state["products"]
            for ingredient in product["recipe"]
            if ingredient["item_id"] == item_id
        ]
        if recipe_values:
            base = sum(recipe_values) / len(recipe_values)
            final = base * float(item["coefficient"])
            percent = (final - base) / base * 100
            growth_note = (
                f' 学習が終了しました。{item["name"]}: 1食あたり'
                f'{_display_number(_round_one(base))}{item["unit"]} → '
                f'{_display_number(_round_one(final))}{item["unit"]}'
                f"（{percent:+.0f}%）。この幅でよろしければ、一度ご確認ください。"
            )
    elif growth.startswith("学習中"):
        growth_note = f" {growth}。数字は参考程度に見てください。"
    elif growth.startswith("係数が安定しません"):
        growth_note = f" {growth}"
    if conflict := _save(state):
        return conflict
    return _tell(
        (
            f"{message} 在庫を{_display_number(float(item['stock']))}"
            f'{item["unit"]}に更新しました。{warning}{growth_note}'
        ).rstrip()
    )


@tool
@_serialized
def record_unit_used(item_id: str, opened_next: bool = True) -> str:
    """ユニット型品目（ソース・油・玉ねぎ等）を1ユニット使い切った時に記録します。

    開封時点からの累計食数の差で「1ユニット＝何食分」を確定します（設計書2章）。
    途中の残量は扱いません。確定した事実（空になった）だけで学習します。
    開封の起点がまだ無い場合は、いま使っている1ユニットの開封起点だけを記録します。

    Args:
        item_id: 品目ID。例: sauce_yogurt。
        opened_next: 空になった後、次の1ユニットをすぐ開けたか。開けていなければ False。
    """
    state = load_state()
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return f"品目ID「{item_id}」は見つかりません。"
    if _consumption_type(item) != "unit":
        return (
            f'{item["name"]}はユニット型ではありません。'
            "棚卸しは record_count を使ってください。"
        )

    unit = item["unit"]
    sales_count = float(item.get("sales_count", 0))
    opened_at = item.get("opened_at_sales_count")

    if opened_at is None:
        item["opened_at_sales_count"] = sales_count
        if conflict := _save(state):
            return conflict
        return _tell(
            f'{item["name"]}の開封を記録しました。この1{unit}が空になったら'
            f'また教えてください。そこで「1{unit}＝何食分」が確定します。'
        )

    servings = int(round(sales_count - float(opened_at)))
    history = item.setdefault("unit_history", [])
    anomaly = ""
    if servings <= 0:
        anomaly = (
            f"開封からの売上が記録されていないため、今回の1{unit}は係数に反映しません。"
            "売上の記録漏れがないかご確認ください。"
        )
    elif len(history) >= UNIT_BOUND_MIN_SAMPLES:
        # 上限判定: 過去実績の±20%（設計書2章）。超えた値は事実として残すが学習しない
        average = sum(history) / len(history)
        if abs(servings - average) > UNIT_BOUND_RATIO * average:
            anomaly = (
                f"1{unit}で{servings}食は、過去実績（平均{average:.0f}食）の"
                f"±{int(UNIT_BOUND_RATIO * 100)}%を超えています。係数には反映しません。"
                "別用途に使ったか、売上か使い切りの記録漏れの可能性があります。"
            )
    if not anomaly:
        history.append(servings)
        item["coefficient"] = round(sum(history) / len(history), 1)

    item.setdefault("count_history", []).append(
        {
            "recorded_at": _now_iso(),
            "event": "unit_used",
            "servings": servings,
            "reflected": not anomaly,
            "coefficient_after": item.get("coefficient"),
        }
    )
    before = float(item["stock"])
    item["stock"] = _round_one(before - 1)
    item["opened_at_sales_count"] = sales_count if opened_next else None

    if conflict := _save(state):
        return conflict

    stock_display = _display_stock(item)
    if anomaly:
        return _tell(f'{item["name"]}: {anomaly} 残り{stock_display}。')
    coefficient = float(item["coefficient"])
    capacity_note = (
        f"（あと約{int(max(0.0, float(item['stock'])) * coefficient)}食分）"
        if float(item["stock"]) >= 0
        else ""
    )
    return _tell(
        f'{item["name"]}: 1{unit}で{servings}食でした。'
        f"実績{len(history)}回 → 1{unit}≈{coefficient:.0f}食。"
        f"残り{stock_display}{capacity_note}。"
    )


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
    """全品目の現在庫、係数、育成フェーズ、最終棚卸し、直近の設定変更を返します。

    理論値がマイナスの品目は数字を出さず「実測が必要です」と返します（原則10）。
    """
    state = load_state()
    lines: list[str] = []
    for item in state["items"]:
        if not item.get("active", True):
            continue
        ctype = _consumption_type(item)
        last_counted = item.get("last_counted")
        last_display = _fmt_dt(last_counted) if last_counted else "未実施"
        if ctype == "unit":
            coefficient = item.get("coefficient")
            coef_display = (
                f'1{item["unit"]}≈{float(coefficient):.0f}食'
                if coefficient
                else "未学習"
            )
            opened_at = item.get("opened_at_sales_count")
            opened_note = ""
            if opened_at is not None:
                used = int(round(float(item.get("sales_count", 0)) - float(opened_at)))
                opened_note = f'、開封中の1{item["unit"]}は{used}食目'
            lines.append(
                f'- {item["name"]}: {_display_stock(item)}、{coef_display}、'
                f"{_growth_label(item)}{opened_note}、最終棚卸し {last_display}"
            )
        elif ctype == "count":
            lines.append(
                f'- {item["name"]}: {_display_stock(item)}、係数固定、'
                f"最終棚卸し {last_display}"
            )
        else:
            lines.append(
                f'- {item["name"]}: {_display_stock(item)}、'
                f'係数 {float(item["coefficient"]):.2f}、'
                f"{_growth_label(item)}、最終棚卸し {last_display}"
            )

    settings_log = state.get("settings_log", [])
    if settings_log:
        lines.append("")
        lines.append("直近の設定変更:")
        for entry in settings_log[-5:]:
            lines.append(f'- {_fmt_dt(entry["changed_at"])} {entry["summary"]}')
    return _tell("\n".join(lines))


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
        unlearned: list[str] = []
        for ingredient in product["recipe"]:
            item = _find(state["items"], ingredient["item_id"])
            if item is None or not item.get("active", True):
                missing = ingredient["item_id"]
                break
            ctype = _consumption_type(item)
            qty = float(ingredient["qty"])
            if qty <= 0:
                continue
            if ctype == "unit":
                coefficient = item.get("coefficient")
                if not coefficient:
                    # 未学習のユニット型は残数を出せない。黙って0にも∞にもしない
                    unlearned.append(item["name"])
                    continue
                available = float(item["stock"]) * float(coefficient)
                opened_at = item.get("opened_at_sales_count")
                if opened_at is not None:
                    available -= float(item.get("sales_count", 0)) - float(opened_at)
                possible = available / qty
            else:
                coefficient = float(item["coefficient"]) if ctype == "weight" else 1.0
                per_serving = qty * coefficient
                if per_serving <= 0:
                    continue
                possible = float(item["stock"]) / per_serving
            if servings is None or possible < servings:
                servings = possible
                bottleneck = item["name"]
        unlearned_note = (
            f'（{"、".join(unlearned)}は学習前のため計算に含めていません）'
            if unlearned
            else ""
        )
        if missing:
            lines.append(
                f'- {product["name"]}: 計算不可（品目「{missing}」が未登録または無効）'
            )
        elif servings is None:
            lines.append(
                f'- {product["name"]}: 残数を計算できる品目がありません{unlearned_note}'
            )
        elif servings < 0:
            lines.append(
                f'- {product["name"]}: {bottleneck}の理論値が在庫を割っています。'
                f"実測が必要です{unlearned_note}"
            )
        else:
            lines.append(
                f'- {product["name"]}: あと{int(servings)}食'
                f"（ボトルネック: {bottleneck}）{unlearned_note}"
            )
    return "\n".join(lines)


@tool
@_serialized
def get_monthly_reconciliation(month: str = "") -> str:
    """月次突合: 棚卸し実測の変化と「仕入れ − レシピ理論消費」を品目ごとに突き合わせます。

    日々の上限（±4g/食）の内側に収まる小さな差も、月単位の積算では見えます（原則12）。
    差の原因（記録漏れ・廃棄・抜き取り）は区別できないため、事実だけを返します。
    ユニット型は使い切り実績そのものが突合になるため対象外です。

    Args:
        month: 対象月（YYYY-MM）。省略時は今月。
    """
    if month:
        if not re.match(r"^\d{4}-\d{2}$", month):
            return "month は YYYY-MM 形式で指定してください。例: 2026-09"
    else:
        month = _now().strftime("%Y-%m")

    state = load_state()
    findings: list[str] = []
    uncheckable: list[str] = []
    for item in state["items"]:
        if not item.get("active", True):
            continue
        ctype = _consumption_type(item)
        if ctype == "unit":
            continue
        counts = [
            entry
            for entry in item.get("count_history", [])
            if "actual_stock" in entry and entry["recorded_at"][:7] == month
        ]
        if len(counts) < 2:
            uncheckable.append(item["name"])
            continue
        first, last = counts[0], counts[-1]
        window_start = _parse_iso(first["recorded_at"])
        window_end = _parse_iso(last["recorded_at"])

        purchased = 0.0
        recipe_consumption = 0.0
        servings = 0.0
        for entry in state["history"]:
            recorded_at = entry.get("recorded_at")
            if recorded_at is None:
                continue
            at = _parse_iso(recorded_at)
            if not (window_start < at <= window_end):
                continue
            if entry.get("type") == "purchase":
                if entry.get("item_id") == item["id"]:
                    purchased += float(entry["amount"])
                continue
            product_id = entry.get("product_id")
            if product_id is None:
                continue
            product = _find(state["products"], product_id)
            if product is None:
                continue
            recipe = next(
                (i for i in product["recipe"] if i["item_id"] == item["id"]), None
            )
            if recipe:
                quantity = float(entry["quantity"])
                recipe_consumption += quantity * float(recipe["qty"])
                servings += quantity

        # レシピ値ベースの期待在庫と実測の差。係数を経由しないので、
        # 係数に吸収されたズレも積算では表に出る（設計書 原則12「月次で見る」）
        expected_last = float(first["actual_stock"]) + purchased - recipe_consumption
        gap = _round_one(expected_last - float(last["actual_stock"]))
        allowance = (
            _round_one(WEIGHT_BOUND_PER_SERVING * servings)
            if ctype == "weight"
            else 0.0
        )
        if gap == 0 or abs(gap) <= allowance:
            continue
        unit = item["unit"]
        period = f'{_fmt_dt(first["recorded_at"])}〜{_fmt_dt(last["recorded_at"])}'
        direction = "不足" if gap > 0 else "余剰"
        if ctype == "weight":
            findings.append(
                f'- {item["name"]}: {period}に仕入れ{_display_number(purchased)}{unit}、'
                f"レシピ理論消費{_display_number(_round_one(recipe_consumption))}{unit}"
                f"（売上{_display_number(servings)}食）。実測との差 "
                f"{_display_number(abs(gap))}{unit}（{direction}）は、盛り付けのブレ"
                f"（±{_display_number(WEIGHT_BOUND_PER_SERVING)}{unit}/食 ＝ "
                f"{_display_number(allowance)}{unit}）では説明できません。"
                "仕入れか売上の記録漏れがないかご確認ください"
            )
        else:
            findings.append(
                f'- {item["name"]}: {period}の実測との差 '
                f"{_display_number(abs(gap))}{unit}（{direction}）。"
                "数で管理する品目のため、記録漏れや廃棄がなかったかご確認ください"
            )

    lines = [f"{month} の月次突合:"]
    if findings:
        lines.extend(findings)
    else:
        lines.append("説明できない差はありません。")
    if uncheckable:
        lines.append("棚卸しが2回未満で突合できない品目: " + "、".join(uncheckable))
    return _tell("\n".join(lines))


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
    consumption_type: str = "",
    purchase_unit: str = "",
    unit_weight: float = 0.0,
    passphrase: str = "",
) -> str:
    """品目（材料・消耗品）を追加します。構造変更のため合言葉が必要です。

    weight型の係数は必ず1.0から始めます（店主に決めさせない）。実測が育てます。
    unit型は初期値を置かず、最初の使い切り（record_unit_used）で確定します。

    Args:
        item_id: 英小文字スネークケースのID。例: sauce_yogurt。AIが命名する。
        name: 表示名。例: ソース（ヨーグルト）。
        unit: 消費単位。例: g、枚、本、個、中子。
        unit_type: "weight"（重量）/ "volume"（容量）/ "count"（個数）。
        stock: 現在庫。ざっくりで良い。
        tier: 管理区分。仮判定でよい。
        consumption_type: 消費の数え方。"count"（数どおり減る）/
            "weight"（量って盛る。係数を棚卸しで学習）/
            "unit"（1本・1個・中子1杯で何食分か。使い切りで学習）。
            カウンセリング段階5の「何を1として数えますか」の答えで決める。
            品目名から決め打ちしない。省略時は unit_type から補う（count→count、他→weight）。
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
    if consumption_type and consumption_type not in CONSUMPTION_TYPES:
        return 'consumption_type は "count" / "weight" / "unit" のいずれかです。'
    if stock < 0:
        return "在庫は0以上で指定してください。"

    if not consumption_type:
        consumption_type = "count" if unit_type == "count" else "weight"
    item: dict[str, Any] = {
        "id": item_id,
        "name": name,
        "tier": tier,
        "unit": unit,
        "unit_type": unit_type,
        "consumption_type": consumption_type,
        "stock": _round_one(stock),
        "coefficient": 1.0,
        "last_counted": None,
        "count_history": [],
        "active": True,
    }
    if consumption_type == "unit":
        item["coefficient"] = None
        item["sales_count"] = 0
        item["opened_at_sales_count"] = None
        item["unit_history"] = []
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
        {k: item[k] for k in ("id", "name", "unit", "consumption_type", "stock")},
    )
    if conflict := _save(state):
        return conflict
    if consumption_type == "unit":
        return (
            f"{name}を登録しました（{_display_number(float(stock))}{unit}）。"
            f"1{unit}＝何食分かは最初の使い切りで学習します。"
        )
    if consumption_type == "count":
        return f"{name}を登録しました（{_display_number(float(stock))}{unit}、数どおり管理）。"
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
