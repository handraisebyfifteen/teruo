"""係数収束シミュレーション — 「手の誤差を学習する」が本当かを実データ生成で検証する。

teruo の中核の主張: レシピと実際の盛り付けの差（係数）を棚卸しから学習する。
これを検証するため、「真の係数」を決めて売上と棚卸しを機械的に生成し、
実ツール（record_sales / record_count）にそのまま食わせて、
係数が 1.0 から真の値に近づくかを見る。

シナリオは2つ:
  A) 盛りブレが上限（レシピ±4g/食）の内側 → 真の値に収束するはず
  B) 盛りブレが上限を超える           → 上限で止まり、警告が出るはず（原則12）

本体のコードは変更しない。state は tests/sim_state.json を使い、
本番の data/state.json には触らない。

出力:
  tests/convergence.csv   — 棚卸し回ごとの係数（両シナリオ）
  tests/convergence.png   — 収束グラフ

使い方:
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

import store  # noqa: E402  （INVENTORY_STATE_PATH を設定してから import する）
import tools  # noqa: E402

tools.DIRECT_OUTPUT = False  # シミュレーション中はツールに印字させない

TZ = ZoneInfo("Asia/Tokyo")

# --- シミュレーション時計。tools 側の「今」を差し替える ---
_sim_now = datetime.now(TZ)


def _clock() -> datetime:
    return _sim_now


tools._now = _clock


def at(day: date, hour: int, minute: int) -> None:
    global _sim_now
    _sim_now = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def call(tool_obj, *args, **kwargs):
    """strands の @tool ラッパー越しに元関数を呼ぶ。"""
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

DAYS = 20          # 営業日数 = 棚卸し回数
NOISE = 0.05       # 日ごとの手のばらつき ±5%（現場では毎日ぴったり同じにはならない）


def run_scenario(true_coefficient: float, seed: int) -> dict:
    """真の係数を固定して20営業日を回し、棚卸しごとの係数の推移を返す。"""
    shutil.copy(REPO_ROOT / "data" / "state.json", SIM_STATE)
    rng = random.Random(seed)

    # teruo からは見えない現実の在庫
    true_stock = {"meat_chicken": 8500.0, "wrap_paper": 500.0}

    coefficients: list[float] = []
    paper_coefficients: list[float] = []
    cap_hits = 0

    day = date(2026, 8, 1)
    for _ in range(DAYS):
        # --- 営業: 1日30〜60食をランダムに商品へ配分 ---
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

        # --- 仕入れ: 実測グラム付きで入れる（残りが1日分を切る前に） ---
        if true_stock["meat_chicken"] < 5000:
            at(day, 17, 0)
            amount = float(rng.randint(9700, 10300))
            call(
                tools.record_purchase,
                [{"item_id": "meat_chicken", "amount": amount, "units": 1}],
            )
            true_stock["meat_chicken"] += amount

        # --- 締め: 棚卸し（チキンは毎日、紙は5日ごと） ---
        at(day, 21, 0)
        result = call(tools.record_count, "meat_chicken", round(true_stock["meat_chicken"]))
        if "上限に達しています" in result:
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
    scenario_a = run_scenario(true_coefficient=1.04, seed=7)   # 上限の内側
    scenario_b = run_scenario(true_coefficient=1.15, seed=7)   # 上限超え

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

    # --- 判定 ---
    tail_a = scenario_a["coefficients"][4:]
    mean_a = statistics.fmean(tail_a)
    swing_a = max(
        abs(x - y) for x, y in zip(scenario_a["coefficients"][5:], scenario_a["coefficients"][4:])
    )
    print(f"シナリオA（真の係数 {scenario_a['true']}）")
    print(f"  係数の推移: {[round(c, 3) for c in scenario_a['coefficients']]}")
    print(f"  5回目以降の平均: {mean_a:.3f}（真の値との差 {abs(mean_a - scenario_a['true']) / scenario_a['true'] * 100:.1f}%）")
    print(f"  5回目以降の最大振れ幅: {swing_a:.3f}")
    print(f"  ラップ紙（count型）の係数: {scenario_a['paper_coefficients']}（1.0のままであること）")
    print(f"シナリオB（真の係数 {scenario_b['true']} — 上限超え）")
    print(f"  係数の推移: {[round(c, 3) for c in scenario_b['coefficients']]}")
    print(f"  上限警告の回数: {scenario_b['cap_hits']} / {DAYS}")
    print(f"出力: {CSV_PATH.relative_to(REPO_ROOT)}, {PNG_PATH.relative_to(REPO_ROOT)}")

    ok = True
    if abs(mean_a - scenario_a["true"]) / scenario_a["true"] > 0.02:
        ok = False
        print("NG: シナリオAが真の係数に収束していません")
    if swing_a > 0.04:
        ok = False
        print("NG: 係数が振動し続けています（平滑化を見直すこと）")
    if any(c != 1.0 for c in scenario_a["paper_coefficients"]):
        ok = False
        print("NG: count型（ラップ紙）の係数が動いています")
    if scenario_b["cap_hits"] == 0:
        ok = False
        print("NG: シナリオBで上限警告が出ていません")
    print("判定: " + ("OK — 係数は真の値に収束し、上限も機能しています" if ok else "NG"))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
