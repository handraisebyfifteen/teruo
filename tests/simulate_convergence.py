"""Coefficient convergence simulation — checks whether "learning the hand's
error" actually holds, using generated data.

teruo's core claim: the gap between the recipe and actual portioning (the
coefficient) is learned from stock counts. To verify it, we fix a "true
coefficient", mechanically generate sales and stock counts, feed them to the
real tools (record_sales / record_count), and watch whether the coefficient
moves from 1.0 toward the true value.

Two scenarios:
  A) Portioning drift inside the cap (recipe ±4g/serving) → should converge
     to the true value
  B) Portioning drift beyond the cap → should stop at the cap and warn
     (principle 12)

No production code is changed. State goes to tests/sim_state.json; the real
data/state.json is untouched.

Output:
  tests/convergence.csv   — coefficient per stock count (both scenarios)
  tests/convergence.png   — convergence chart

Usage:
    python tests/simulate_convergence.py
"""

from __future__ import annotations

import csv
import os
import random
import shutil
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SIM_STATE = REPO_ROOT / "tests" / "sim_state.json"
CSV_PATH = REPO_ROOT / "tests" / "convergence.csv"
PNG_PATH = REPO_ROOT / "tests" / "convergence.png"

os.environ["INVENTORY_STATE_PATH"] = str(SIM_STATE)
sys.path.insert(0, str(REPO_ROOT))

import store  # noqa: E402  (import after setting INVENTORY_STATE_PATH)
import tools  # noqa: E402

tools.DIRECT_OUTPUT = False  # keep the tools quiet during the simulation

TZ = ZoneInfo("Asia/Tokyo")

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


RECIPES = {
    "kebab_sand": {"meat_chicken": 75, "pita": 1, "wrap_paper": 1, "napkin": 1},
    "kebab_wrap": {"meat_chicken": 75, "tortilla": 1, "wrap_paper": 1, "napkin": 1},
    "rice_box": {"meat_chicken": 110, "rice": 200, "container": 1, "spoon": 1, "napkin": 1},
    "kebab_mix": {"meat_beef": 60, "meat_chicken": 60, "container": 1, "napkin": 1},
    "meat_only": {"meat_chicken": 120, "container": 1},
}

DAYS = 20          # business days = number of stock counts
NOISE = 0.05       # daily hand variance ±5% (no hand is identical every day)


def run_scenario(true_coefficient: float, seed: int) -> dict:
    """Fix the true coefficient, run 20 business days, return the
    coefficient's path across stock counts."""
    shutil.copy(REPO_ROOT / "data" / "state.json", SIM_STATE)
    rng = random.Random(seed)

    # The real stock teruo cannot see
    true_stock = {"meat_chicken": 8500.0, "wrap_paper": 500.0}

    coefficients: list[float] = []
    paper_coefficients: list[float] = []
    cap_hits = 0

    day = date(2026, 8, 1)
    for _ in range(DAYS):
        # --- Trading: 30-60 servings per day, split randomly across products ---
        at(day, 12, 0)
        servings = rng.randint(30, 60)
        noise = 1.0 + rng.uniform(-NOISE, NOISE)
        weights = [rng.random() for _ in RECIPES]
        total_weight = sum(weights)
        remaining = servings
        product_ids = list(RECIPES)
        for index, product_id in enumerate(product_ids):
            if index == len(product_ids) - 1:
                quantity = remaining
            else:
                quantity = min(remaining, round(servings * weights[index] / total_weight))
            remaining -= quantity
            if quantity <= 0:
                continue
            call(tools.record_sales, product_id, quantity)
            recipe = RECIPES[product_id]
            true_stock["meat_chicken"] -= (
                quantity * recipe.get("meat_chicken", 0) * true_coefficient * noise
            )
            true_stock["wrap_paper"] -= quantity * recipe.get("wrap_paper", 0)

        # --- Purchases: with measured grams (before less than a day remains) ---
        if true_stock["meat_chicken"] < 5000:
            at(day, 17, 0)
            amount = float(rng.randint(9700, 10300))
            call(
                tools.record_purchase,
                [{"item_id": "meat_chicken", "amount": amount, "units": 1}],
            )
            true_stock["meat_chicken"] += amount

        # --- Closing: stock counts (chicken daily, paper every 5 days) ---
        at(day, 21, 0)
        result = call(tools.record_count, "meat_chicken", round(true_stock["meat_chicken"]))
        if "hit the cap" in result:
            cap_hits += 1
        state = store.load_state()
        chicken = next(i for i in state["items"] if i["id"] == "meat_chicken")
        coefficients.append(float(chicken["coefficient"]))

        if len(coefficients) % 5 == 0:
            call(tools.record_count, "wrap_paper", round(true_stock["wrap_paper"]))
            state = store.load_state()
            paper = next(i for i in state["items"] if i["id"] == "wrap_paper")
            paper_coefficients.append(float(paper["coefficient"]))

        day += timedelta(days=1)

    return {
        "true": true_coefficient,
        "coefficients": coefficients,
        "paper_coefficients": paper_coefficients,
        "cap_hits": cap_hits,
    }


def main() -> None:
    scenario_a = run_scenario(true_coefficient=1.04, seed=7)   # inside the cap
    scenario_b = run_scenario(true_coefficient=1.15, seed=7)   # beyond the cap

    with CSV_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["count_no", "coeff_within_bound", "coeff_beyond_bound"])
        for index in range(DAYS):
            writer.writerow(
                [
                    index + 1,
                    scenario_a["coefficients"][index],
                    scenario_b["coefficients"][index],
                ]
            )

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    counts = list(range(1, DAYS + 1))
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)

    axes[0].plot(counts, scenario_a["coefficients"], marker="o", label="learned coefficient")
    axes[0].axhline(scenario_a["true"], linestyle="--", color="tab:green", label=f'true hand ({scenario_a["true"]:.2f})')
    axes[0].set_title("A: variance within bound — converges")

    axes[1].plot(counts, scenario_b["coefficients"], marker="o", label="learned coefficient")
    axes[1].axhline(scenario_b["true"], linestyle="--", color="tab:green", label=f'true hand ({scenario_b["true"]:.2f})')
    axes[1].axhline(
        (75 + tools.WEIGHT_BOUND_PER_SERVING) / 75,
        linestyle=":",
        color="tab:red",
        label="bound (recipe +4g/serving)",
    )
    axes[1].set_title("B: beyond bound — stops at cap, warns")

    for axis in axes:
        axis.axhline(1.0, linewidth=0.8, color="gray")
        axis.set_xlabel("count #")
        axis.set_xticks(range(0, DAYS + 1, 5))
        axis.legend(fontsize=8)
        axis.grid(alpha=0.3)
    axes[0].set_ylabel("coefficient")
    figure.suptitle("teruo — coefficient learning from daily counts (recipe says 1.0, the hand says otherwise)")
    figure.tight_layout()
    figure.savefig(PNG_PATH, dpi=150)

    # --- Verdict ---
    tail_a = scenario_a["coefficients"][4:]
    mean_a = statistics.fmean(tail_a)
    swing_a = max(
        abs(x - y) for x, y in zip(scenario_a["coefficients"][5:], scenario_a["coefficients"][4:])
    )
    print(f"Scenario A (true coefficient {scenario_a['true']})")
    print(f"  Coefficient path: {[round(c, 3) for c in scenario_a['coefficients']]}")
    print(f"  Mean from count 5 on: {mean_a:.3f} (off the true value by {abs(mean_a - scenario_a['true']) / scenario_a['true'] * 100:.1f}%)")
    print(f"  Max swing from count 5 on: {swing_a:.3f}")
    print(f"  Wrap paper (count type) coefficients: {scenario_a['paper_coefficients']} (must stay 1.0)")
    print(f"Scenario B (true coefficient {scenario_b['true']} — beyond the cap)")
    print(f"  Coefficient path: {[round(c, 3) for c in scenario_b['coefficients']]}")
    print(f"  Cap warnings: {scenario_b['cap_hits']} / {DAYS}")
    print(f"Output: {CSV_PATH.relative_to(REPO_ROOT)}, {PNG_PATH.relative_to(REPO_ROOT)}")

    ok = True
    if abs(mean_a - scenario_a["true"]) / scenario_a["true"] > 0.02:
        ok = False
        print("FAIL: scenario A did not converge to the true coefficient")
    if swing_a > 0.04:
        ok = False
        print("FAIL: the coefficient keeps oscillating (revisit the smoothing)")
    if any(c != 1.0 for c in scenario_a["paper_coefficients"]):
        ok = False
        print("FAIL: a count-type coefficient (wrap paper) moved")
    if scenario_b["cap_hits"] == 0:
        ok = False
        print("FAIL: scenario B never raised a cap warning")
    print("Verdict: " + ("OK — the coefficient converges to the true value and the cap works" if ok else "FAIL"))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
