"""デモ用シードデータ生成 — 先月1ヶ月分の整合した営業記録を作る。

実ツール（tools.py）をそのまま呼んで記録するため、生成された state は
本番の係数ロジック・履歴形式と完全に整合する。乱数は固定シードで再現可能。

埋め込んである異常（チキン）:
- 盛りブレ +3%（1食あたり約2g強。係数の上限±4g/食の内側 → 日次では正常）
- 未記録の持ち出し・廃棄 1.5kg × 4回（棚卸しのたびに係数が上限警告を出す）
→ 月次突合では「盛り付けで説明できる幅」を超えた差として現れる

出力: data/state.demo-month.json（既存の data/state.json には触らない）

使い方:
    python scripts/seed_demo.py
    INVENTORY_STATE_PATH=data/state.demo-month.json python main.py
    > 8月の突合をして        # 生成対象は実行日の「先月」
"""

from __future__ import annotations

import os
import random
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "state.demo-month.json"

shutil.copy(REPO_ROOT / "data" / "state.json", OUT_PATH)
os.environ["INVENTORY_STATE_PATH"] = str(OUT_PATH)
sys.path.insert(0, str(REPO_ROOT))

import tools  # noqa: E402  （INVENTORY_STATE_PATH を設定してから import する）

TZ = ZoneInfo("Asia/Tokyo")
rng = random.Random(42)

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


# --- 対象月 = 実行日の先月 ---
today = date.today()
month_last = today.replace(day=1) - timedelta(days=1)
month_first = month_last.replace(day=1)
MONTH = month_first.strftime("%Y-%m")

business_days = [
    month_first + timedelta(days=i)
    for i in range((month_last - month_first).days + 1)
    if (month_first + timedelta(days=i)).weekday() != 0  # 月曜定休
]

# --- 真の在庫（teruo からは見えない現実）---
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
# 盛りブレ（レシピに対する実際の手の倍率）。上限±4g/食の内側
POUR_FACTOR = {"meat_chicken": 1.03, "meat_beef": 1.03, "rice": 1.01}

RECIPES = {
    "kebab_sand": {"meat_chicken": 75, "pita": 1, "wrap_paper": 1, "napkin": 1},
    "kebab_wrap": {"meat_chicken": 75, "tortilla": 1, "wrap_paper": 1, "napkin": 1},
    "rice_box": {"meat_chicken": 110, "rice": 200, "container": 1, "spoon": 1, "napkin": 1},
    "kebab_mix": {"meat_beef": 60, "meat_chicken": 60, "container": 1, "napkin": 1},
    "meat_only": {"meat_chicken": 120, "container": 1},
}
SAUCE_PRODUCTS = ("kebab_sand", "kebab_wrap")  # ソースを1食分使う商品

# 未記録の持ち出し・廃棄（チキン）。月内に4回、1.5kgずつ
chunk_days = {business_days[i] for i in (5, 11, 17, 23)}
CHUNK_G = 1500.0
# ピタの紛失（数え物のわずかな差のデモ）
pita_loss_days = {business_days[8], business_days[19]}

# --- ソースのボトル（真の姿）---
sauce_bottles = 4          # 開封中を含む本数
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
    if "上限に達しています" in result:
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


# ============================== シミュレーション ==============================

first_day, last_day = business_days[0], business_days[-1]

# 月初: 全品目の棚卸し（基準線）と、ソースの開封起点
at(first_day, 9, 0)
for item_id in true_stock:
    take_count(item_id)
at(first_day, 9, 10)
call(tools.record_unit_used, "sauce_yogurt")  # 開封中ボトルの起点だけ記録

chicken_count_days = set(business_days[6::6])  # 週1ペース

for day in business_days:
    restock(day)
    daily_sales(day)
    if day in chunk_days:
        at(day, 22, 0)
        true_stock["meat_chicken"] -= CHUNK_G   # 記録されない持ち出し・廃棄
    if day in pita_loss_days:
        true_stock["pita"] -= 1                  # 記録されない紛失
    if day in chicken_count_days and day != last_day:
        at(day, 21, 30)
        take_count("meat_chicken")

# 月末: 全品目の棚卸し（突合のもう片方の錨）
at(last_day, 21, 30)
for item_id in true_stock:
    take_count(item_id)

# ============================== 検証出力 ==============================

print(f"生成しました: {OUT_PATH}（対象月 {MONTH}、営業{len(business_days)}日）")
print()
print("埋め込んだ異常:")
print(f"- チキン 盛りブレ +3% と、未記録の持ち出し {CHUNK_G:.0f}g × {len(chunk_days)}回")
print(f"- ピタ 紛失 {len(pita_loss_days)}枚")
print()
print(f"月中の棚卸しで出た上限警告: {len(count_warnings)}回")
for line in count_warnings:
    print(f"  {line}")
print()
print("=== get_monthly_reconciliation の出力（動画でこのまま映る内容）===")
print(call(tools.get_monthly_reconciliation, MONTH))
