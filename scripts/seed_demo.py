"""Demo seed data generator — builds one consistent month of trading records.

It calls the real tools (tools.py) to record everything, so the generated
state matches the production coefficient logic and history format exactly.
The RNG is seeded, so runs are reproducible.

Embedded anomalies (chicken):
- Portioning drift +3% (a bit over 2g/serving — inside the ±4g/serving cap,
  so daily numbers look normal)
- Unrecorded consumption (waste, staff meals, ... that never got logged):
  1.5kg × 4 times (each stock count makes the coefficient hit its cap warning)
→ The monthly reconciliation surfaces it as a gap larger than portioning
  variance can explain.

Output: data/state.demo-month.json (the existing data/state.json is untouched).
With --lang ja the Japanese template (data/state.ja.json) is used instead and
the result goes to data/state.demo-month.ja.json; the generated state carries
config.language so main.py needs no --lang flag.

Usage:
    python scripts/seed_demo.py
    INVENTORY_STATE_PATH=data/state.demo-month.json python main.py
    > reconcile last month        # the generated month is last month

    python scripts/seed_demo.py --lang ja
    INVENTORY_STATE_PATH=data/state.demo-month.ja.json python main.py
    > 先月の突合をして
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import i18n  # noqa: E402

_parser = argparse.ArgumentParser(description="Generate one month of demo records.")
_parser.add_argument("--lang", default="en", help="en (default) or ja")
LANGUAGE = i18n.set_language(_parser.parse_args().lang)
SUFFIX = "" if LANGUAGE == "en" else f".{LANGUAGE}"
TEMPLATE = REPO_ROOT / "data" / f"state{SUFFIX}.json"
OUT_PATH = REPO_ROOT / "data" / f"state.demo-month{SUFFIX}.json"

shutil.copy(TEMPLATE, OUT_PATH)
os.environ["INVENTORY_STATE_PATH"] = str(OUT_PATH)

import store  # noqa: E402  (import after setting INVENTORY_STATE_PATH)
import tools  # noqa: E402

tools.DIRECT_OUTPUT = False  # keep the tools quiet while seeding

TZ = ZoneInfo("Asia/Tokyo")
rng = random.Random(42)

# --- Simulation clock. Replaces "now" inside tools ---
_sim_now = datetime.now(TZ)


def _clock() -> datetime:
    return _sim_now


tools._now = _clock


def at(day: date, hour: int, minute: int) -> None:
    global _sim_now
    _sim_now = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def call(tool_obj, *args, **kwargs):
    """Call the underlying function through the strands @tool wrapper."""
    fn = getattr(tool_obj, "_tool_func", None) or getattr(
        tool_obj, "original_function", None
    )
    if fn is None and callable(tool_obj):
        fn = tool_obj
    return fn(*args, **kwargs)


# --- Target month = the month before the run date ---
today = date.today()
month_last = today.replace(day=1) - timedelta(days=1)
month_first = month_last.replace(day=1)
MONTH = month_first.strftime("%Y-%m")

business_days = [
    month_first + timedelta(days=i)
    for i in range((month_last - month_first).days + 1)
    if (month_first + timedelta(days=i)).weekday() != 0  # closed Mondays
]

# --- True stock (the reality teruo cannot see) ---
true_stock = {
    "meat_chicken": 8500.0,
    "meat_beef": 6200.0,
    "pita": 200.0,
    "tortilla": 150.0,
    "rice": 8000.0,
    "wrap_paper": 500.0,
    "napkin": 1000.0,
    "container": 300.0,
    "spoon": 300.0,
}
# Portioning drift (the hand's real multiplier vs. the recipe).
# Inside the ±4g/serving cap.
POUR_FACTOR = {"meat_chicken": 1.03, "meat_beef": 1.03, "rice": 1.01}

RECIPES = {
    "kebab_sand": {"meat_chicken": 75, "pita": 1, "wrap_paper": 1, "napkin": 1},
    "kebab_wrap": {"meat_chicken": 75, "tortilla": 1, "wrap_paper": 1, "napkin": 1},
    "rice_box": {"meat_chicken": 110, "rice": 200, "container": 1, "spoon": 1, "napkin": 1},
    "kebab_mix": {"meat_beef": 60, "meat_chicken": 60, "container": 1, "napkin": 1},
    "meat_only": {"meat_chicken": 120, "container": 1},
}
SAUCE_PRODUCTS = ("kebab_sand", "kebab_wrap")  # products using one serving of sauce

# Unrecorded chicken consumption (waste, staff meals, ... never logged).
# Four times during the month, 1.5kg each.
unrecorded_days = {business_days[i] for i in (5, 11, 17, 23)}
UNRECORDED_G = 1500.0
# Lost pita (demo of a small gap in a count-tracked item)
pita_loss_days = {business_days[8], business_days[19]}

# --- Sauce bottles (the true picture) ---
sauce_bottles = 4          # bottle count, including the open one
sauce_capacity = rng.randint(48, 52)
sauce_used_in_open = 0

count_warnings: list[str] = []


def consume(product_id: str, quantity: int) -> None:
    for item_id, qty in RECIPES[product_id].items():
        factor = POUR_FACTOR.get(item_id, 1.0)
        true_stock[item_id] -= quantity * qty * factor


def maybe_empty_sauce() -> None:
    global sauce_bottles, sauce_capacity, sauce_used_in_open
    while sauce_used_in_open >= sauce_capacity:
        sauce_used_in_open -= sauce_capacity
        sauce_bottles -= 1
        sauce_capacity = rng.randint(48, 52)
        call(tools.record_unit_used, "sauce_yogurt")


def restock(day: date) -> None:
    global sauce_bottles
    at(day, 10, 0)
    orders: list[dict] = []
    while true_stock["meat_chicken"] < 8000:
        amount = float(rng.randint(9700, 10300))
        orders.append({"item_id": "meat_chicken", "amount": amount, "units": 1})
        true_stock["meat_chicken"] += amount
    if true_stock["meat_beef"] < 1500:
        amount = float(rng.randint(9700, 10300))
        orders.append({"item_id": "meat_beef", "amount": amount, "units": 1})
        true_stock["meat_beef"] += amount
    for item_id, threshold, lot in (
        ("pita", 60, 100), ("tortilla", 40, 100), ("rice", 3000, 5000),
        ("wrap_paper", 150, 500), ("napkin", 250, 1000),
        ("container", 80, 300), ("spoon", 40, 200),
    ):
        if true_stock[item_id] < threshold:
            orders.append({"item_id": item_id, "amount": float(lot)})
            true_stock[item_id] += lot
    if sauce_bottles < 2:
        orders.append({"item_id": "sauce_yogurt", "units": 3})
        sauce_bottles += 3
    if orders:
        call(tools.record_purchase, orders)


def take_count(item_id: str) -> None:
    result = call(tools.record_count, item_id, round(true_stock[item_id], 1))
    if tools.hit_cap(result):
        count_warnings.append(f"{_sim_now.date()} {result.splitlines()[0]}")


def daily_sales(day: date) -> None:
    global sauce_used_in_open
    event = day.weekday() in (5, 6)
    venue = "event" if event else "solo"
    scale = 1.5 if event else 1.0
    plan = {
        "kebab_sand": max(1, round(rng.randint(18, 30) * scale)),
        "kebab_wrap": max(1, round(rng.randint(8, 16) * scale)),
        "rice_box": max(1, round(rng.randint(4, 9) * scale)),
        "kebab_mix": max(0, round(rng.randint(2, 6) * scale)),
        "meat_only": max(0, round(rng.randint(1, 4) * scale)),
    }
    slots = [(11, 30), (12, 15), (13, 0), (17, 30), (18, 15), (19, 0)]
    for index, (hour, minute) in enumerate(slots):
        at(day, hour, minute)
        for product_id, total in plan.items():
            share = total // len(slots) + (1 if index < total % len(slots) else 0)
            if share <= 0:
                continue
            call(tools.record_sales, product_id, share, venue)
            consume(product_id, share)
            if product_id in SAUCE_PRODUCTS:
                sauce_used_in_open += share
                maybe_empty_sauce()


# ============================== Simulation ==============================

first_day, last_day = business_days[0], business_days[-1]

# Start of month: count every item (the baseline) and mark the open sauce bottle
at(first_day, 9, 0)
for item_id in true_stock:
    take_count(item_id)
at(first_day, 9, 10)
call(tools.record_unit_used, "sauce_yogurt")  # record only the opening point

chicken_count_days = set(business_days[6::6])  # roughly weekly

for day in business_days:
    restock(day)
    daily_sales(day)
    if day in unrecorded_days:
        at(day, 22, 0)
        true_stock["meat_chicken"] -= UNRECORDED_G   # consumption never logged
    if day in pita_loss_days:
        true_stock["pita"] -= 1                  # loss never logged
    if day in chicken_count_days and day != last_day:
        at(day, 21, 30)
        take_count("meat_chicken")

# End of month: count every item (the reconciliation's other anchor)
at(last_day, 21, 30)
for item_id in true_stock:
    take_count(item_id)

# Remember the language in the generated state so main.py needs no --lang
_state = store.load_state()
_state["config"] = {**(_state.get("config") or {}), "language": LANGUAGE}
store.save_state(_state)

# ============================== Verification output ==============================

print(f"Generated: {OUT_PATH} (target month {MONTH}, {len(business_days)} business days)")
print()
print("Embedded anomalies:")
print(f"- Chicken: +3% portioning drift, plus {UNRECORDED_G:.0f}g unrecorded consumption × {len(unrecorded_days)}")
print(f"- Pita: {len(pita_loss_days)} sheets lost")
print()
print(f"Cap warnings raised by mid-month stock counts: {len(count_warnings)}")
for line in count_warnings:
    print(f"  {line}")
print()
print("=== get_monthly_reconciliation output (exactly what the video will show) ===")
print(call(tools.get_monthly_reconciliation, MONTH))
