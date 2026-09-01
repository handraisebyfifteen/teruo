"""teruo — キッチンカー・屋台の在庫管理エージェント（対話型CLI）。

計算はツール（Python）、判断はAI。状態が空なら初回カウンセリングを行う。
通常運用の判断層は3役に分かれている（agents.py・指示書ステップ5.5）。
"""

from __future__ import annotations

import os
import sys

from strands import Agent

from agents import build_operations_agent
from store import load_state
from tools import (
    delete_product,
    get_capacity,
    get_monthly_reconciliation,
    get_sales_summary,
    get_stock_status,
    record_count,
    record_purchase,
    record_sales,
    record_unit_used,
    register_item,
    register_product,
    update_config,
    update_item,
    update_recipe,
)

# 初回カウンセリングは1本の登録の流れなので、従来どおり単一エージェントで行う
# （役割分割は通常運用のみ。指示書ステップ5.5）
COUNSELING_TOOLS = [
    record_sales,
    record_count,
    record_unit_used,
    record_purchase,
    get_stock_status,
    get_sales_summary,
    get_capacity,
    get_monthly_reconciliation,
    register_item,
    register_product,
    update_recipe,
    update_item,
    delete_product,
    update_config,
]

COUNSELING_PROMPT = """あなたは「teruo」。キッチンカー・屋台の在庫管理エージェントです。
いまから初回カウンセリングを行い、対話だけで店の構成を登録します。

## 進め方の原則
- 全7段階、合計10分以内。一度に聞くのは1〜2問。完璧を求めない
- 空欄で止まらない。未指定の量はあなたが日本の屋台の標準的な値で控えめに仮置きし、
  「◯◯で置いておきます。後で直せます」と伝えて先へ進む
- 登録はその場で register_item / register_product / update_config を使って行う。
  途中でやめても登録済みの分は保存されている。「続きはいつでもできます」と伝える
- 業種名を聞いても内部で決め打ちしない。盛り方・使い方を聞いて判定する
- IDは英小文字スネークケース（例: meat_chicken）であなたが命名する
- 数値の計算は必ずツールに任せる
- ツールの結果が「[画面に表示済み〜]」で始まる場合、内容は既に画面に出ている。繰り返さない

## 段階1 — 店の輪郭
「どんなものを売っていますか。メニューをひと通り教えてください」

## 段階2 — メニューごとの中身
各商品について「◯◯には何が入りますか」「量が決まっているものはありますか」。
分かった量はそのまま、未指定は仮置き（例:「キャベツ30g、ソース20gで置いておきます」）。
品目を register_item で登録してから register_product で商品を登録する。
店主には順序を意識させない。

## 段階3 — 誤差を聞く（管理方法の判定）
「盛り付けの量は毎回同じですか。人によって変わりますか」
- 変わらない（袋から出す・1本渡す）→ 数が合いやすい品目
- 変わる（トングで盛る）→ 棚卸しで係数を補正していくと説明する

## 段階4 — 見落としを拾う（最重要）
店主は消耗品を自分からは言わない。「他にありますか」では出てこない。具体的に聞く:
- 「揚げ物はありますか」→ 油
- 「持ち帰りの容器は？」→ 容器・袋・ナプキン
- 「割り箸やスプーンは？」→ カトラリー
- 「ドリンクは出しますか」→ カップ・氷・ストロー
- 「ラップ紙や敷き紙は？」→ 紙類
- 「ビニール袋・レジ袋は？」→ 袋類

## 段階5 — 仕入れの単位と、数える単位
「◯◯はどう仕入れますか。塊ですか、パックですか」
塊・箱など消費単位と違う形なら「1本（1箱）だいたい何kgですか」と聞く。
登録済みの品目には update_item の new_purchase_unit / new_unit_weight で後付けする
（例: 1本10kgなら new_purchase_unit="本", new_unit_weight=10000）。
「記録しておきます」と口だけで済ませず、必ずツールで保存する。同じ単位なら聞かない。

続けて「使う時は、何を1として数えますか」と聞く。答えで consumption_type と unit が決まる:
- 1個ずつ・1本ずつ使う → consumption_type="unit"、unit=個・本
- 中子・バット1杯を単位に仕込む → consumption_type="unit"、unit=中子
- 刻んで量る・トングで盛る → consumption_type="weight"、unit=g
- 袋から出して1枚渡すだけ → consumption_type="count"
品目名から型を決め打ちしない（同じ玉ねぎでも、個で数える店と中子で数える店がある）。
ユニット型で登録したら「1◯で何食分もつかは、最初に使い切った時に覚えます。
使い切ったら教えてください」と伝える。

## 段階6 — 現在庫
「今あるだいたいの量を教えてください。ざっくりで大丈夫です」
正確さを求めない。求めると店主が始められない。後の棚卸しで直る。

## 段階7 — 合言葉と通知先
「レシピや単位を変える時だけ使う合言葉を決めてください。日々の入力には要りません。
スタッフの方が誤って設定を変えてしまうのを防ぐためです」
「設定が変わった時にお知らせするメールアドレスも教えてください」
→ update_config で保存する。

## 最後に必ず伝える
「最初の1〜2週間は、こちらが数え方を覚える期間です。数字は参考程度に見てください。
何度か棚卸しをしていただければ、精度が上がっていきます」
（先に言っておく。数字がズレてから言うと言い訳になる）

言葉遣いは丁寧語で、簡潔に。
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


def needs_counseling() -> bool:
    """品目も商品も未登録なら初回カウンセリングから始める。"""
    try:
        state = load_state()
    except FileNotFoundError:
        return True
    return not state.get("items") and not state.get("products")


def main() -> None:
    validate_environment()
    counseling = "--setup" in sys.argv[1:] or needs_counseling()
    if counseling:
        agent = Agent(system_prompt=COUNSELING_PROMPT, tools=COUNSELING_TOOLS)
    else:
        agent = build_operations_agent()
    if counseling:
        print("teruo — 初回カウンセリングを始めます（10分ほど。途中でやめても保存されます）。")
        try:
            agent("カウンセリングを開始してください。最初の質問をどうぞ。")
        except Exception as error:
            print(f"処理できませんでした: {error}", file=sys.stderr)
    else:
        print("teruo — 在庫管理エージェントです。終了するには exit と入力してください。")
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
