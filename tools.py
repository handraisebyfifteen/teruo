"""The calculation tools exposed to the Strands agent.

All arithmetic happens here (Python); the AI never does mental math.
Structure-changing tools verify the passphrase and log before/after
values to settings_log.
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
    """Serialize one whole load→save cycle per tool call.

    The agent sometimes calls tools in parallel (e.g. during stock counts);
    without the lock a later write silently clobbers an earlier one
    (observed on real hardware).
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with STATE_LOCK:
            return func(*args, **kwargs)

    return wrapper


TIMEZONE = ZoneInfo("Asia/Tokyo")
VENUE_TYPES = ("event", "solo")
UNIT_TYPES = ("weight", "volume", "count")
# The three consumption types (design doc §2). This is the counting axis,
# separate from unit_type (the kind of unit).
CONSUMPTION_TYPES = ("count", "weight", "unit")
CONFLICT_MESSAGE = "Someone else seems to have entered data first. Please try again."
PASSPHRASE_MESSAGE = (
    "The passphrase is incorrect. Changing recipes, units, or other settings "
    "requires the passphrase."
)
NEGATIVE_STOCK_DISPLAY = "recount needed (the book value went negative)"

# Conversion tables within the same unit kind (multiplier per base unit).
# Never convert across kinds. Metric and imperial both live here — which
# system a shop uses is decided at onboarding, per item.
WEIGHT_UNITS = {"g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.59237}
VOLUME_UNITS = {"ml": 1.0, "mL": 1.0, "l": 1000.0, "L": 1000.0, "fl oz": 29.5735}
COUNT_UNITS = (
    "pc", "sheet", "bottle", "bag", "can", "box",
    "serving", "cup", "roll", "tub", "piece", "cone",
)

ITEM_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Learning-phase cutoff: 5 stock counts or 14 days (design doc, principle 9)
LEARNING_MAX_COUNTS = 5
LEARNING_MAX_DAYS = 14
STABLE_COEFFICIENT_BAND = 0.05

# Coefficient cap (design doc §2). Portioning variance is physically
# bounded at about ±3-4g per serving. Defined in grams; always convert to
# the item's unit via _bound_per_serving (±4 would mean ±113g for an oz item).
WEIGHT_BOUND_PER_SERVING = 4.0
# Coefficient smoothing. Adopting a single count's correction in full chases
# day-to-day hand variance (about ±5%) and oscillates (confirmed by the
# convergence simulation). Moving halfway keeps ~5-count convergence while
# halving the swing.
COEFFICIENT_SMOOTHING = 0.5
# Unit-tracked items: ±20% of past records. No cap check until 3 records exist.
UNIT_BOUND_RATIO = 0.2
UNIT_BOUND_MIN_SAMPLES = 3
UNIT_LEARNING_SAMPLES = 3


def _now() -> datetime:
    return datetime.now(TIMEZONE)


def _now_iso() -> str:
    """Timestamps are always generated in Python. Never let the AI invent dates."""
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


def _plural(unit: str, value: float) -> str:
    if abs(value) == 1:
        return unit
    if unit.endswith(("s", "x", "ch", "sh")):
        return unit + "es"
    return unit + "s"


def _amount(value: float, unit: str) -> str:
    """Format a quantity with its unit: '300g' for measures, '3 bottles' for counts."""
    if unit in WEIGHT_UNITS or unit in VOLUME_UNITS:
        return f"{_display_number(value)}{unit}"
    return f"{_display_number(value)} {_plural(unit, value)}"


def _bound_per_serving(unit: str) -> float:
    """The portioning-variance cap expressed in the item's unit.

    The physical limit is defined in grams (±4g/serving); ml is treated as
    the equivalent for volume items. Unknown units fall back to the raw value.
    """
    factor = WEIGHT_UNITS.get(unit) or VOLUME_UNITS.get(unit) or 1.0
    return WEIGHT_BOUND_PER_SERVING / factor


def _display_bound(value: float) -> str:
    """Bound values below 1 (e.g. 0.14oz) need two decimals to stay meaningful."""
    return _display_number(value) if value >= 1 else f"{value:.2f}"


# Facts (final tool output) are printed straight to the screen by Python
# (principle 3: Python calculates, AI judges). This prevents the LLM's
# paraphrase from dropping line items or altering numbers.
# seed_demo.py and friends set this to False to silence it.
DIRECT_OUTPUT = True

TOLD_MARKER = (
    "[Already shown on screen. Do not repeat the content; "
    "add only a brief judgment or next step]"
)


def _tell(text: str) -> str:
    """Print the final output directly to stdout and tag it so the LLM won't echo it."""
    if DIRECT_OUTPUT:
        print(text, flush=True)
        return f"{TOLD_MARKER}\n{text}"
    return text


def _find(records: list[dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    return next((record for record in records if record["id"] == record_id), None)


def _consumption_type(item: dict[str, Any]) -> str:
    """Consumption type. Older data without one falls back to unit_type
    (count→count, everything else→weight)."""
    value = item.get("consumption_type")
    if value in CONSUMPTION_TYPES:
        return value
    return "count" if item.get("unit_type") == "count" else "weight"


def _display_stock(item: dict[str, Any]) -> str:
    """Stock for display. Negative values stay stored internally but the
    number itself is never shown (design doc, principle 10)."""
    stock = float(item["stock"])
    if stock < 0:
        return NEGATIVE_STOCK_DISPLAY
    return _amount(stock, item["unit"])


def _check_passphrase(state: dict[str, Any], passphrase: str) -> str | None:
    """Match against the stored passphrase. Pass through when none is set
    (i.e. during onboarding)."""
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
    """Structure-change history. Always keep both the before and the after
    (design doc, principle 4)."""
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
    """Conversion multiplier within the same kind (g→kg etc.). None across kinds."""
    for table in (WEIGHT_UNITS, VOLUME_UNITS):
        if old_unit in table and new_unit in table:
            return table[old_unit] / table[new_unit]
    return None


def _growth_counts(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Stock counts since the most recent unit change. A unit change
    restarts the learning phase."""
    counts: list[dict[str, Any]] = []
    for entry in item.get("count_history", []):
        if entry.get("event") == "unit_change":
            counts = []
        elif "actual_stock" in entry:
            counts.append(entry)
    return counts


def _growth_label(item: dict[str, Any]) -> str:
    """Learning-phase label (design doc, principle 9).

    "learning" is cut off unconditionally after 5 stock counts or 14 days,
    and never said again. If the coefficient hasn't settled, return the fact
    (recent coefficient movement) and leave interpretation to the AI.
    Unit-tracked items count empty-unit records instead (design doc §2).
    """
    ctype = _consumption_type(item)
    if ctype == "count":
        return "coefficient fixed"
    if ctype == "unit":
        n = len(item.get("unit_history", []))
        if n == 0:
            return "unlearned (waiting for the first empty unit)"
        if n < UNIT_LEARNING_SAMPLES:
            return f"learning ({n}/{UNIT_LEARNING_SAMPLES} empty units)"
        return f"stable ({n} records)"
    counts = _growth_counts(item)
    n = len(counts)
    if n == 0:
        return f"learning (0/{LEARNING_MAX_COUNTS} stock counts)"
    days = (_now() - _parse_iso(counts[0]["recorded_at"])).days
    if n < LEARNING_MAX_COUNTS and days < LEARNING_MAX_DAYS:
        return f"learning (stock count {n}/{LEARNING_MAX_COUNTS})"
    if n < 2:
        return "not enough stock counts"
    delta = abs(
        float(counts[-1]["coefficient_after"]) - float(counts[-2]["coefficient_after"])
    )
    if delta <= STABLE_COEFFICIENT_BAND:
        return "stable"
    return (
        "coefficient not settling (last "
        f'{float(counts[-2]["coefficient_after"]):.2f} → '
        f'{float(counts[-1]["coefficient_after"]):.2f})'
    )


def _save(state: dict[str, Any]) -> str | None:
    try:
        save_state(state)
    except StateConflictError:
        return CONFLICT_MESSAGE
    return None


# ---------------------------------------------------------------------------
# Daily entries (no passphrase required)
# ---------------------------------------------------------------------------


@tool
@_serialized
def record_sales(product_id: str, quantity: int, venue_type: str = "solo") -> str:
    """Record sales and reduce item stock according to the product's recipe.

    Each consumption type behaves differently (design doc §2):
    count items decrease one-for-one, weight items by recipe × coefficient.
    Unit items (sauce etc.) only accumulate a serving tally; their stock
    moves when an empty unit is recorded.
    The sale timestamp is set by Python automatically — no date input needed.

    Args:
        product_id: Product ID, e.g. kebab_sand (kebab sandwich).
        quantity: Number sold. Integer, zero or more.
        venue_type: "event" (event booth) or "solo" (regular solo pitch).
            Use "event" only when the owner explicitly says it was an event.
            Defaults to "solo".
    """
    if quantity < 0:
        return "Quantity must be zero or more."
    if venue_type not in VENUE_TYPES:
        return 'venue_type must be "event" or "solo".'

    state = load_state()
    product = _find(state["products"], product_id)
    if product is None:
        return f'Product ID "{product_id}" was not found.'

    changes: list[str] = []
    notes: list[str] = []
    for ingredient in product["recipe"]:
        item = _find(state["items"], ingredient["item_id"])
        if item is None or not item.get("active", True):
            continue
        ctype = _consumption_type(item)
        qty = float(ingredient["qty"])

        if ctype == "unit":
            # Partial contents can't be measured. Only tally servings
            # (stock moves via record_unit_used).
            item["sales_count"] = float(item.get("sales_count", 0)) + quantity * qty
            coefficient = item.get("coefficient")
            opened_at = item.get("opened_at_sales_count")
            used_note = ""
            if opened_at is not None:
                used = int(round(float(item["sales_count"]) - float(opened_at)))
                used_note = f'; the open {item["unit"]} is at serving {used}'
            changes.append(
                f'{item["name"]}: stock unchanged '
                f'(running total {_display_number(float(item["sales_count"]))} '
                f'servings{used_note})'
            )
            if coefficient and opened_at is not None:
                remaining = float(coefficient) - used
                if remaining <= max(5.0, float(coefficient) * 0.1):
                    notes.append(
                        f'{item["name"]}: the open {item["unit"]} should run out soon '
                        f'(about {max(0, int(remaining))} servings left). '
                        "Tell me when it's empty."
                    )
            continue

        coefficient = float(item["coefficient"]) if ctype == "weight" else 1.0
        before = float(item["stock"])
        consumed = _round_one(quantity * qty * coefficient)
        after = _round_one(before - consumed)
        item["stock"] = after
        if after < 0 <= before:
            # Keep the negative value, never show the number (principle 10).
            # Don't stop with an error either.
            changes.append(
                f'{item["name"]}: the book value ran below zero. There should still '
                "be some left — my estimate ran low. Please measure it at closing."
            )
        elif after < 0:
            changes.append(f'{item["name"]}: {NEGATIVE_STOCK_DISPLAY}')
        else:
            changes.append(
                f'{item["name"]}: {_display_number(before)} → '
                f'{_amount(after, item["unit"])} '
                f'(down {_amount(consumed, item["unit"])})'
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
    lines = [f'Recorded {product["name"]} × {quantity}.']
    lines.extend(f"- {change}" for change in changes)
    lines.extend(notes)
    return _tell("\n".join(lines))


@tool
@_serialized
def record_count(item_id: str, actual_stock: float) -> str:
    """Record a physical stock count. For weight items, the difference since
    the last count corrects the consumption coefficient.

    Count items are only recounted (coefficient fixed at 1.0). Unit items are
    only recounted in units; their coefficient is settled by empty-unit
    records (record_unit_used).

    Args:
        item_id: Item ID, e.g. meat_chicken (kebab meat, chicken).
        actual_stock: The counted stock, in the item's registered unit.
            For unit items, count an opened unit as 1.
    """
    if actual_stock < 0:
        return "Counted stock must be zero or more."

    state = load_state()
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return f'Item ID "{item_id}" was not found.'

    ctype = _consumption_type(item)
    counted_at = _now_iso()
    previous_coefficient = float(item.get("coefficient") or 1.0)
    calculated_stock = float(item["stock"])
    last_counted = item.get("last_counted")

    warning = ""
    message: str
    if ctype == "unit":
        message = (
            f'Recounted {item["name"]} units. '
            f'Servings per {item["unit"]} is settled by empty-unit records.'
        )
    elif ctype == "count":
        difference = _round_one(calculated_stock - actual_stock)
        if difference == 0:
            message = f'{item["name"]} matches the book value.'
        else:
            # A gap in a count-tracked item can't be explained by a coefficient.
            # State the fact only (principle 12).
            direction = "fewer" if difference > 0 else "more"
            message = (
                f'{item["name"]} counted '
                f'{_amount(abs(difference), item["unit"])} {direction} than the book '
                "value. This item is tracked by count, so please check for "
                "unlogged sales or waste."
            )
    elif last_counted is None:
        message = (
            f'{item["name"]}: first stock count, so the coefficient stays at '
            f"{previous_coefficient:.2f}."
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
            # Smoothing: never adopt one count in full, move halfway
            # (anti-oscillation).
            new_coefficient = previous_coefficient + COEFFICIENT_SMOOTHING * (
                measured_coefficient - previous_coefficient
            )
            # Coefficient cap: recipe value ±4g/serving (design doc §2) —
            # the physical limit of portioning variance, in the item's unit.
            bound = _bound_per_serving(item["unit"])
            base_per_serving = recipe_consumption / servings
            lower = max(0.0, base_per_serving - bound) / base_per_serving
            upper = (base_per_serving + bound) / base_per_serving
            clamped = min(upper, max(lower, new_coefficient))
            item["coefficient"] = round(clamped, 4)
            message = (
                f'Updated the coefficient for {item["name"]} from '
                f'{previous_coefficient:.2f} to {item["coefficient"]:.2f}.'
            )
            if clamped != new_coefficient:
                warning = (
                    " The coefficient has hit the cap of what portioning variance "
                    f"can explain (recipe value ±"
                    f'{_display_bound(bound)}{item["unit"]}'
                    "/serving). I won't adjust it any further on my own. "
                    "The recipe itself may need a review."
                )
            elif abs(clamped - previous_coefficient) > 0.15:
                warning = (
                    " That is a big jump. Please double-check the count as well."
                )
        else:
            message = (
                f'{item["name"]} has no sales since the last count, so the '
                f"coefficient stays at {previous_coefficient:.2f}."
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
    if ctype == "weight" and label_before.startswith("learning") and not growth.startswith("learning"):
        # When learning ends, always show the gap between the initial and the
        # settled value. Never finalize silently (design doc §2).
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
                f' Learning is complete. {item["name"]}: '
                f'{_amount(_round_one(base), item["unit"])} → '
                f'{_amount(_round_one(final), item["unit"])} per serving '
                f"({percent:+.0f}%). Please confirm this range is acceptable."
            )
    elif growth.startswith("learning"):
        growth_note = f" Still {growth} — treat the numbers as rough for now."
    elif growth.startswith("coefficient not settling"):
        growth_note = f" Note: {growth}."
    if conflict := _save(state):
        return conflict
    return _tell(
        (
            f"{message} Stock updated to "
            f'{_amount(float(item["stock"]), item["unit"])}.{warning}{growth_note}'
        ).rstrip()
    )


@tool
@_serialized
def record_unit_used(item_id: str, opened_next: bool = True) -> str:
    """Record that a unit-tracked item (sauce, oil, onion, ...) was used up.

    The serving tally since it was opened settles "servings per unit"
    (design doc §2). Partial contents are never handled — only the certain
    fact that a unit is empty feeds learning. If no opening point exists yet,
    this only records the opening point of the unit currently in use.

    Args:
        item_id: Item ID, e.g. sauce_yogurt.
        opened_next: Whether the next unit was opened right away after this
            one emptied. False if not.
    """
    state = load_state()
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return f'Item ID "{item_id}" was not found.'
    if _consumption_type(item) != "unit":
        return (
            f'{item["name"]} is not a unit-tracked item. '
            "Use record_count for stock counts."
        )

    unit = item["unit"]
    sales_count = float(item.get("sales_count", 0))
    opened_at = item.get("opened_at_sales_count")

    if opened_at is None:
        item["opened_at_sales_count"] = sales_count
        if conflict := _save(state):
            return conflict
        return _tell(
            f'Recorded that a {unit} of {item["name"]} was opened. Tell me when '
            f"it's empty — that will settle how many servings one {unit} holds."
        )

    servings = int(round(sales_count - float(opened_at)))
    history = item.setdefault("unit_history", [])
    anomaly = ""
    if servings <= 0:
        anomaly = (
            f"No sales were recorded since it was opened, so this {unit} won't "
            "count toward the coefficient. Please check for missed sales entries."
        )
    elif len(history) >= UNIT_BOUND_MIN_SAMPLES:
        # Cap check: ±20% of past records (design doc §2). An out-of-band
        # value is kept as a fact but not learned from.
        average = sum(history) / len(history)
        if abs(servings - average) > UNIT_BOUND_RATIO * average:
            anomaly = (
                f"{servings} servings from one {unit} is more than "
                f"±{int(UNIT_BOUND_RATIO * 100)}% off the past average "
                f"({average:.0f} servings). Not counting it toward the "
                "coefficient. It may have been used for something else, or a "
                "sale or empty-unit record may be missing."
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
        return _tell(f'{item["name"]}: {anomaly} {stock_display} left.')
    coefficient = float(item["coefficient"])
    capacity_note = (
        f" (about {int(max(0.0, float(item['stock'])) * coefficient)} servings left)"
        if float(item["stock"]) >= 0
        else ""
    )
    return _tell(
        f'{item["name"]}: {servings} servings from that {unit}. '
        f"{len(history)} records → ≈{coefficient:.0f} servings per {unit}. "
        f"{stock_display} left{capacity_note}."
    )


@tool
@_serialized
def record_purchase(purchases: list[dict]) -> str:
    """Add purchases to stock. The AI reads the owner's notes, confirms the
    line items with them, then calls this.

    Use the actual amount when known; otherwise place a rough figure from the
    estimated amount per purchase unit (unit_weight). Later physical counts
    always win over estimates.

    Args:
        purchases: List of purchase line items. Each element is a dict with:
            item_id: Item ID (required).
            amount: The actual amount added, in the item's registered unit.
                Provide when the real quantity is known.
            units: Number of purchase units (e.g. the 2 in "2 cones of meat").
                Without amount, the stock is estimated as units × unit_weight.
    """
    if not purchases:
        return "The purchase list is empty."

    state = load_state()
    lines: list[str] = []
    for entry in purchases:
        item_id = entry.get("item_id")
        item = _find(state["items"], item_id) if item_id else None
        if item is None or not item.get("active", True):
            return (
                f'Item ID "{item_id}" was not found. '
                "Register it first with register_item."
            )

        amount = entry.get("amount")
        units = entry.get("units")
        estimated = False
        if amount is None:
            if units is None:
                return f'{item["name"]}: needs either amount or units.'
            unit_weight = item.get("unit_weight")
            if unit_weight:
                # A distinct purchase unit exists (1 cone = 10kg, 1 bag = 10
                # sheets, ...) — estimate from the typical amount.
                amount = float(units) * float(unit_weight)
                estimated = True
            elif item.get("unit_type") == "count":
                amount = float(units)
            else:
                return (
                    f'{item["name"]}: no estimated amount per '
                    f'{item.get("purchase_unit", "purchase unit")} is set, '
                    "so please provide the actual amount."
                )
        amount = float(amount)
        if amount < 0:
            return f'{item["name"]}: purchase amount must be zero or more.'

        before = float(item["stock"])
        after = _round_one(before + amount)
        item["stock"] = after

        # With both the actual amount and the unit count, learn the real
        # "grams per cone" from experience.
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
        note = (
            " (rough estimate — tell me the actual amount if you learn it)"
            if estimated
            else ""
        )
        lines.append(
            f'{item["name"]} +{_amount(amount, item["unit"])} '
            f'({_display_number(before)} → '
            f'{_amount(after, item["unit"])}){note}'
        )

    if conflict := _save(state):
        return conflict
    return "Recorded the purchases.\n" + "\n".join(lines)


@tool
@_serialized
def get_stock_status() -> str:
    """Return every item's current stock, coefficient, learning phase, last
    stock count, and recent settings changes.

    Items whose book value is negative show "recount needed" instead of the
    number (principle 10).
    """
    state = load_state()
    lines: list[str] = []
    for item in state["items"]:
        if not item.get("active", True):
            continue
        ctype = _consumption_type(item)
        last_counted = item.get("last_counted")
        last_display = _fmt_dt(last_counted) if last_counted else "never"
        if ctype == "unit":
            coefficient = item.get("coefficient")
            coef_display = (
                f'≈{float(coefficient):.0f} servings per {item["unit"]}'
                if coefficient
                else "unlearned"
            )
            opened_at = item.get("opened_at_sales_count")
            opened_note = ""
            if opened_at is not None:
                used = int(round(float(item.get("sales_count", 0)) - float(opened_at)))
                opened_note = f', open {item["unit"]} at serving {used}'
            lines.append(
                f'- {item["name"]}: {_display_stock(item)}, {coef_display}, '
                f"{_growth_label(item)}{opened_note}, last counted {last_display}"
            )
        elif ctype == "count":
            lines.append(
                f'- {item["name"]}: {_display_stock(item)}, coefficient fixed, '
                f"last counted {last_display}"
            )
        else:
            lines.append(
                f'- {item["name"]}: {_display_stock(item)}, '
                f'coefficient {float(item["coefficient"]):.2f}, '
                f"{_growth_label(item)}, last counted {last_display}"
            )

    settings_log = state.get("settings_log", [])
    if settings_log:
        lines.append("")
        lines.append("Recent settings changes:")
        for entry in settings_log[-5:]:
            lines.append(f'- {_fmt_dt(entry["changed_at"])} {entry["summary"]}')
    return _tell("\n".join(lines))


@tool
@_serialized
def get_sales_summary() -> str:
    """Return per-product average daily sales, split by venue type
    (event / solo).

    Events and solo days differ in crowd and scale, so they are averaged
    separately, never mixed.
    """
    state = load_state()
    sales = [
        entry
        for entry in state["history"]
        if entry.get("product_id") is not None and entry.get("recorded_at")
    ]
    if not sales:
        return "No sales records yet."

    venue_names = {"event": "Event days", "solo": "Solo days"}
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
        lines = [f"{venue_names[venue]} ({len(days)} business days):"]
        for product_id, total in totals.items():
            product = _find(state["products"], product_id)
            name = product["name"] if product else product_id
            average = _round_one(total / len(days))
            lines.append(
                f"- {name}: {_display_number(total)} total, "
                f"{_display_number(average)}/day average"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


@tool
@_serialized
def get_capacity() -> str:
    """Return how many more servings of each product the current stock allows,
    with the bottleneck item.

    All remaining-serving math happens in Python. Use it to judge whether
    stock will last — not to forecast sales.
    """
    state = load_state()
    if not state["products"]:
        return "No products registered."
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
                    # An unlearned unit item can't yield a remaining count.
                    # Never silently treat it as 0 or infinity.
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
            f' (excluding {", ".join(unlearned)} — still unlearned)'
            if unlearned
            else ""
        )
        if missing:
            lines.append(
                f'- {product["name"]}: cannot compute '
                f'(item "{missing}" is unregistered or inactive)'
            )
        elif servings is None:
            lines.append(
                f'- {product["name"]}: no items available to compute a remaining '
                f"count{unlearned_note}"
            )
        elif servings < 0:
            lines.append(
                f'- {product["name"]}: the book value for {bottleneck} ran below '
                f"zero. A recount is needed{unlearned_note}"
            )
        else:
            lines.append(
                f'- {product["name"]}: {int(servings)} servings left '
                f"(bottleneck: {bottleneck}){unlearned_note}"
            )
    return "\n".join(lines)


@tool
@_serialized
def get_monthly_reconciliation(month: str = "") -> str:
    """Monthly reconciliation: per item, compare the change between physical
    counts against "purchases − recipe-basis consumption".

    Small gaps that stay inside the daily cap (±4g/serving) still show up
    when accumulated over a month (principle 12). The cause of a gap
    (missed records, waste, shrinkage) cannot be told apart, so only the
    facts are returned. Unit-tracked items are excluded — their empty-unit
    records are already a reconciliation.

    Args:
        month: Target month (YYYY-MM). Defaults to the current month.
    """
    if month:
        if not re.match(r"^\d{4}-\d{2}$", month):
            return "month must be in YYYY-MM format, e.g. 2026-09."
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

        # Expected stock on a recipe-value basis vs. the physical count.
        # Because this bypasses the coefficient, drift that was absorbed
        # into the coefficient surfaces in the accumulation
        # (design doc, principle 12: "check monthly").
        expected_last = float(first["actual_stock"]) + purchased - recipe_consumption
        gap = _round_one(expected_last - float(last["actual_stock"]))
        bound = _bound_per_serving(item["unit"])
        allowance = _round_one(bound * servings) if ctype == "weight" else 0.0
        if gap == 0 or abs(gap) <= allowance:
            continue
        unit = item["unit"]
        period = f'{_fmt_dt(first["recorded_at"])} – {_fmt_dt(last["recorded_at"])}'
        direction = "short" if gap > 0 else "over"
        if ctype == "weight":
            findings.append(
                f'- {item["name"]}: {period}: purchased '
                f"{_amount(purchased, unit)}, recipe-basis consumption "
                f"{_amount(_round_one(recipe_consumption), unit)} "
                f"({_display_number(servings)} servings sold). The gap vs. the "
                f"physical count, {_amount(abs(gap), unit)} ({direction}), is more "
                "than portioning variance can explain "
                f"(±{_display_bound(bound)}{unit}/serving = "
                f"{_amount(allowance, unit)}). Please check for missed purchase "
                "or sales records"
            )
        else:
            findings.append(
                f'- {item["name"]}: gap vs. the physical count over {period}: '
                f"{_amount(abs(gap), unit)} ({direction}). This item is tracked "
                "by count, so please check for unlogged waste or missed records"
            )

    lines = [f"Monthly reconciliation for {month}:"]
    if findings:
        lines.extend(findings)
    else:
        lines.append("No unexplained gaps.")
    if uncheckable:
        lines.append(
            "Items with fewer than two stock counts (cannot reconcile): "
            + ", ".join(uncheckable)
        )
    return _tell("\n".join(lines))


# ---------------------------------------------------------------------------
# Structure changes (passphrase required; change history kept)
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
    """Add an item (ingredient or supply). A structure change — passphrase required.

    Weight-item coefficients always start at 1.0 (never let the owner pick
    one); physical counts grow them. Unit items start with no value — the
    first empty unit (record_unit_used) settles it.

    Args:
        item_id: Lowercase snake_case ID, e.g. sauce_yogurt. Named by the AI.
        name: Display name, e.g. Yogurt sauce.
        unit: Consumption unit, e.g. g, pc, sheet, bottle, tub.
        unit_type: "weight" / "volume" / "count".
        stock: Current stock. A rough figure is fine.
        tier: Management tier. A provisional guess is fine.
        consumption_type: How consumption is counted. "count" (decreases
            one-for-one) / "weight" (portioned by hand; coefficient learned
            from stock counts) / "unit" (servings per bottle/piece/tub;
            learned from empty units).
            Decided by the onboarding question "what do you count as one
            when you use it?" — never guessed from the item name. If omitted,
            falls back to unit_type (count→count, others→weight).
        purchase_unit: Only when the purchase unit differs from the
            consumption unit, e.g. cone, bag.
        unit_weight: Estimated amount per purchase unit. Only with
            purchase_unit.
        passphrase: The owner's passphrase.
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    if not ITEM_ID_PATTERN.match(item_id):
        return (
            "item_id must be lowercase letters and underscores, e.g. sauce_yogurt."
        )
    if _find(state["items"], item_id) is not None:
        return f'Item ID "{item_id}" already exists. Use a different ID.'
    if unit_type not in UNIT_TYPES:
        return 'unit_type must be one of "weight" / "volume" / "count".'
    if consumption_type and consumption_type not in CONSUMPTION_TYPES:
        return 'consumption_type must be one of "count" / "weight" / "unit".'
    if stock < 0:
        return "Stock must be zero or more."

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
        f"Added item: {name} ({_amount(float(stock), unit)})",
        None,
        {k: item[k] for k in ("id", "name", "unit", "consumption_type", "stock")},
    )
    if conflict := _save(state):
        return conflict
    if consumption_type == "unit":
        return (
            f"Registered {name} ({_amount(float(stock), unit)}). Servings per "
            f"{unit} will be learned from the first empty unit."
        )
    if consumption_type == "count":
        return (
            f"Registered {name} ({_amount(float(stock), unit)}, tracked by count)."
        )
    return (
        f"Registered {name} ({_amount(float(stock), unit)}; coefficient starts "
        "at 1.00 and learns from stock counts)."
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
    """Add a product (menu entry). A structure change — passphrase required.

    If the recipe mentions unregistered items, register them with
    register_item first, then call this (keeping the owner unaware of the
    ordering is the AI's job).

    Args:
        product_id: Lowercase snake_case ID, e.g. kebab_sand.
        name: Display name, e.g. Kebab sandwich.
        price: Price including tax (yen).
        recipe: Ingredient list. Each element is a dict of
            {"item_id": item ID, "qty": amount per serving}.
        passphrase: The owner's passphrase.
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    if not ITEM_ID_PATTERN.match(product_id):
        return "product_id must be lowercase letters and underscores."
    if _find(state["products"], product_id) is not None:
        return f'Product ID "{product_id}" already exists.'
    if price < 0:
        return "Price must be zero or more."
    if not recipe:
        return "The recipe is empty. Specify at least one ingredient."

    seen: set[str] = set()
    missing: list[str] = []
    for ingredient in recipe:
        item_id = ingredient.get("item_id")
        qty = ingredient.get("qty")
        if not item_id or qty is None or float(qty) <= 0:
            return (
                "Every recipe element needs an item_id and a qty greater than zero."
            )
        if item_id in seen:
            return f'Item "{item_id}" appears twice in the recipe.'
        seen.add(item_id)
        item = _find(state["items"], item_id)
        if item is None or not item.get("active", True):
            missing.append(item_id)
    if missing:
        return (
            "These items are unregistered. Register them first with "
            "register_item: " + ", ".join(missing)
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
    recipe_text = ", ".join(
        f'{_find(state["items"], i["item_id"])["name"]} '
        f'{_amount(float(i["qty"]), _find(state["items"], i["item_id"])["unit"])}'
        for i in product["recipe"]
    )
    _log_setting(
        state,
        "register_product",
        f"Added product: {name} (¥{price}) — recipe: {recipe_text}",
        None,
        product,
    )
    if conflict := _save(state):
        return conflict
    return f"Registered {name} (¥{price}). Recipe: {recipe_text}"


@tool
@_serialized
def update_recipe(
    product_id: str,
    item_id: str,
    qty: float,
    passphrase: str = "",
) -> str:
    """Change, add, or remove one ingredient in a product recipe.
    A structure change — passphrase required.

    Args:
        product_id: Product ID.
        item_id: Item ID.
        qty: New amount per serving. 0 removes the ingredient from the recipe.
        passphrase: The owner's passphrase.
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    product = _find(state["products"], product_id)
    if product is None:
        return f'Product ID "{product_id}" was not found.'
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return (
            f'Item ID "{item_id}" is unregistered. '
            "Register it first with register_item."
        )
    if qty < 0:
        return "qty must be zero or more (0 removes the ingredient)."

    existing = next(
        (i for i in product["recipe"] if i["item_id"] == item_id), None
    )
    unit = item["unit"]
    if qty == 0:
        if existing is None:
            return (
                f'The recipe for {product["name"]} does not include '
                f'{item["name"]}.'
            )
        product["recipe"] = [
            i for i in product["recipe"] if i["item_id"] != item_id
        ]
        summary = (
            f'Recipe for {product["name"]}: {item["name"]} '
            f'{_amount(float(existing["qty"]), unit)} → removed'
        )
        before, after = float(existing["qty"]), None
        message = (
            f'Removed {item["name"]} from the recipe for {product["name"]}.'
        )
    elif existing is None:
        product["recipe"].append({"item_id": item_id, "qty": float(qty)})
        summary = (
            f'Recipe for {product["name"]}: {item["name"]} '
            f"none → {_amount(float(qty), unit)}"
        )
        before, after = None, float(qty)
        message = (
            f'Added {item["name"]} '
            f'{_amount(float(qty), unit)} to the recipe for {product["name"]}.'
        )
    else:
        before = float(existing["qty"])
        existing["qty"] = float(qty)
        summary = (
            f'Recipe for {product["name"]}: {item["name"]} '
            f"{_amount(before, unit)} → {_amount(float(qty), unit)}"
        )
        after = float(qty)
        message = (
            f'Changed {item["name"]} in {product["name"]} from '
            f"{_amount(before, unit)} to {_amount(float(qty), unit)}."
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
    """Fix an item's name, unit, or purchase unit. A structure change —
    passphrase required.

    Unit-change rules:
    - Within the same kind (g→kg etc.): stock, recipes, and the estimated
      purchase amount convert automatically.
    - Across kinds (g→pc etc.): no conversion is possible, so a recounted
      stock (new_stock) is required. The coefficient resets to 1.0 and the
      learning phase restarts (past records are kept).

    Args:
        item_id: Item ID.
        new_name: New display name (only when changing).
        new_unit: New consumption unit (only when changing), e.g. kg, pc.
        new_stock: On a cross-kind unit change, the recounted stock in the
            new unit.
        new_purchase_unit: Purchase unit (set or change it once known),
            e.g. cone, bag.
        new_unit_weight: Estimated amount per purchase unit, in the
            consumption unit. E.g. 10000 for a 10kg cone.
        passphrase: The owner's passphrase.
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    item = _find(state["items"], item_id)
    if item is None or not item.get("active", True):
        return f'Item ID "{item_id}" was not found.'
    if not new_name and not new_unit and not new_purchase_unit and new_unit_weight <= 0:
        return (
            "Specify what to change "
            "(new_name / new_unit / new_purchase_unit / new_unit_weight)."
        )

    messages: list[str] = []

    if new_purchase_unit or new_unit_weight > 0:
        if not new_purchase_unit and not item.get("purchase_unit"):
            return (
                "Cannot set an estimated amount alone. Also specify the "
                "purchase unit (new_purchase_unit)."
            )
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
            f' (1 {purchase_unit} ≈ '
            f'{_amount(float(item["unit_weight"]), item["unit"])})'
            if item.get("unit_weight")
            else ""
        )
        _log_setting(
            state,
            "update_item",
            f'Set purchase unit for {item["name"]}: {purchase_unit}{weight_note}',
            before_purchase,
            {
                "purchase_unit": item.get("purchase_unit"),
                "unit_weight": item.get("unit_weight"),
            },
        )
        messages.append(
            f"Registered the purchase unit as {purchase_unit}{weight_note}. "
            "Tell me the actual amount at purchase time when you learn it — "
            "real measurements will refine the estimate."
        )

    if new_name and new_name != item["name"]:
        old_name = item["name"]
        item["name"] = new_name
        _log_setting(
            state,
            "update_item",
            f"Renamed item: {old_name} → {new_name}",
            old_name,
            new_name,
        )
        messages.append(f"Renamed {old_name} to {new_name}.")

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
            # Same kind: mechanically convert stock, recipes, and the
            # estimate. The coefficient keeps its meaning, so it stays.
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
                f'Changed unit for {item["name"]}: {old_unit} → {new_unit} '
                f"(stock {_amount(old_stock, old_unit)} → "
                f'{_amount(float(item["stock"]), new_unit)}, recipes converted)',
                before_snapshot,
                {"unit": new_unit, "stock": item["stock"]},
            )
            note = (
                f"Recipes ({', '.join(dict.fromkeys(affected))}) were converted too."
                if affected
                else ""
            )
            messages.append(
                f"Converted the unit from {old_unit} to {new_unit} "
                f'(stock {_amount(float(item["stock"]), new_unit)}). {note}'
            )
        else:
            # Different kind: no conversion. A recount is mandatory
            # (design doc §2-4).
            new_kind = _unit_kind(new_unit)
            if new_stock < 0:
                return (
                    f'Changing the unit of {item["name"]} from {old_unit} to '
                    f"{new_unit} cannot be converted automatically. The current "
                    f"stock of {_amount(old_stock, old_unit)} must be recounted. "
                    f"Tell me how many {new_unit} there are now "
                    "(pass it as new_stock)."
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
                f'Changed unit for {item["name"]}: {old_unit} → {new_unit} '
                f"(stock {_amount(old_stock, old_unit)} → "
                f"{_amount(float(new_stock), new_unit)}, coefficient reset to "
                "1.0 to relearn)",
                before_snapshot,
                {
                    "unit": new_unit,
                    "unit_type": item["unit_type"],
                    "stock": item["stock"],
                    "coefficient": 1.0,
                },
            )
            warning = (
                f"Recipe amounts ({', '.join(affected_products)}) are still in "
                "the old unit. Fix them with update_recipe."
                if affected_products
                else ""
            )
            messages.append(
                f"Changed the unit from {old_unit} to {new_unit} and recounted "
                f"the stock as {_amount(float(new_stock), new_unit)}. The "
                f"coefficient is back to 1.0 and will relearn. {warning}"
            )
    elif new_unit:
        messages.append(f"The unit is already {new_unit}.")

    if conflict := _save(state):
        return conflict
    return " ".join(messages) if messages else "Nothing was changed."


@tool
@_serialized
def delete_product(
    product_id: str,
    confirm: bool = False,
    passphrase: str = "",
) -> str:
    """Delete a product. Confirmation required; a structure change, so the
    passphrase is required too.

    Deleting a product keeps its items (ingredients) and sales history.
    Call with confirm=True only after the owner has clearly confirmed the
    deletion.

    Args:
        product_id: Product ID.
        confirm: True only once the owner has approved the deletion.
        passphrase: The owner's passphrase.
    """
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    product = _find(state["products"], product_id)
    if product is None:
        return f'Product ID "{product_id}" was not found.'
    if not confirm:
        return (
            f'You are about to delete {product["name"]} (¥{product["price"]}). '
            "A deleted product cannot be restored (its items and sales history "
            "remain). Confirm with the owner that they really want this, then "
            "call again with confirm=True."
        )
    state["products"] = [p for p in state["products"] if p["id"] != product_id]
    _log_setting(
        state,
        "delete_product",
        f'Deleted product: {product["name"]} (¥{product["price"]})',
        product,
        None,
    )
    if conflict := _save(state):
        return conflict
    return (
        f'Deleted {product["name"]}. Its items and sales history are still there.'
    )


@tool
@_serialized
def update_config(
    passphrase: str = "",
    new_passphrase: str = "",
    new_notify_email: str = "",
) -> str:
    """Set the passphrase and the email address notified of settings changes.

    On first setup (nothing stored yet) it can be set directly. Changing it
    later requires the current passphrase.

    Args:
        passphrase: The current passphrase (only needed when changing).
        new_passphrase: The new passphrase.
        new_notify_email: Email address to notify about settings changes.
    """
    if not new_passphrase and not new_notify_email:
        return "Specify what to set (new_passphrase or new_notify_email)."
    state = load_state()
    if error := _check_passphrase(state, passphrase):
        return error
    config = state.setdefault("config", {"passphrase": None, "notify_email": None})
    messages: list[str] = []
    if new_passphrase:
        config["passphrase"] = new_passphrase
        _log_setting(state, "update_config", "Passphrase set", None, "(hidden)")
        messages.append(
            "Passphrase set. It will be needed for recipe and unit changes."
        )
    if new_notify_email:
        old_email = config.get("notify_email")
        config["notify_email"] = new_notify_email
        _log_setting(
            state,
            "update_config",
            f"Notification email set: {new_notify_email}",
            old_email,
            new_notify_email,
        )
        messages.append(f"Notifications will go to {new_notify_email}.")
    if conflict := _save(state):
        return conflict
    return " ".join(messages)
