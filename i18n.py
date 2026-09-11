"""Language switch for everything teruo says on screen.

A launch opens in English unless told otherwise (``python main.py --lang ja``,
TERUO_LANG=ja, or config.language in state.json). It does not stay there: the
owner writing in the other language is what decides, through detect_language
below and follow_owner_language in main.py, and the choice is remembered in
state.json.

Every user-facing string in the tools and the CLI goes through ``t(key)``.
Agent prompts live next to the code that builds the agent (main.py /
agents.py) and are picked by ``get_language()``. Tool docstrings stay in
English — they are read by the model, not the owner, and the model follows
the prompt's language regardless.

The table is keyed per message so both languages sit side by side; a
missing translation fails at import time rather than at the counter.
"""

from __future__ import annotations

import re

LANGUAGES = ("en", "ja")
DEFAULT_LANGUAGE = "en"
_ALIASES = {
    "en": "en", "en-us": "en", "en-gb": "en", "english": "en",
    "ja": "ja", "jp": "ja", "ja-jp": "ja", "japanese": "ja", "日本語": "ja",
}

_current = DEFAULT_LANGUAGE


def normalize_language(value: object) -> str | None:
    """Map user input like 'jp' / 'JA' / 'japanese' to a language code, or None."""
    if not isinstance(value, str):
        return None
    return _ALIASES.get(value.strip().lower())


# Which language a typed line is written in. Kana and kanji are counted
# separately because kanji alone is not evidence of Japanese prose — an
# English-speaking owner registering 焼きそば is still speaking English.
_KANA = re.compile(r"[\u3040-\u30ff]")
_KANJI = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")


def detect_language(text: str) -> str | None:
    """The language a line is written in, or None when it isn't clear enough.

    Deliberately hard to trip. A line switches teruo's whole language, so a
    product name in the other script must never be enough: Japanese needs kana
    and more Japanese characters than Latin letters, English needs no Japanese
    at all plus a real sentence's worth of words. Anything shorter — "OK",
    "はい" inside an English line, "Kebab Bento" typed by a Japanese owner —
    returns None and leaves the language where it is.
    """
    kana = len(_KANA.findall(text))
    japanese = kana + len(_KANJI.findall(text))
    latin = len(_LATIN.findall(text))
    if kana >= 2 and japanese > latin:
        return "ja"
    if japanese == 0 and latin >= 12 and len(_LATIN_WORD.findall(text)) >= 3:
        return "en"
    return None


def set_language(language: str) -> str:
    global _current
    normalized = normalize_language(language)
    if normalized is None:
        raise ValueError(f"unknown language: {language!r}")
    _current = normalized
    return _current


def get_language() -> str:
    return _current


def tool_label(name: str) -> str:
    """A role/action name for the activity strip, or the raw tool name."""
    variants = MESSAGES.get(f"tool_{name}")
    return variants[_current] if variants else name


def t(key: str, **kwargs: object) -> str:
    """Return the message for ``key`` in the current language, formatted."""
    template = MESSAGES[key][_current]
    return template.format(**kwargs)


# ---------------------------------------------------------------------------
# Messages. Placeholders are filled with str.format; format specs (":.2f")
# are allowed. Japanese count units never pluralize and take no space, so
# quantities arrive pre-formatted through tools._amount.
# ---------------------------------------------------------------------------

MESSAGES: dict[str, dict[str, str]] = {
    # --- shared ---
    "conflict": {
        "en": "Someone else seems to have entered data first. Please try again.",
        "ja": "他の方が先に入力したようです。もう一度お願いします。",
    },
    "passphrase_wrong": {
        "en": "The passphrase is incorrect. Changing recipes, units, or other settings requires the passphrase.",
        "ja": "合言葉が違います。レシピや単位などの設定変更には合言葉が必要です。",
    },
    "negative_stock": {
        "en": "recount needed (the book value went negative)",
        "ja": "実測が必要です（理論値が在庫を割りました）",
    },
    "told_marker": {
        "en": "[Already shown on screen. Do not repeat the content; add only a brief judgment or next step]",
        "ja": "[画面に表示済み。内容を繰り返さず、必要な判断や次の一手だけ短く添える]",
    },
    "list_sep": {"en": ", ", "ja": "、"},
    "period_range": {"en": "{start} – {end}", "ja": "{start}〜{end}"},
    "never_counted": {"en": "never", "ja": "未実施"},
    "purchase_unit_fallback": {"en": "purchase unit", "ja": "仕入れ単位"},
    "item_not_found": {
        "en": 'Item ID "{item_id}" was not found.',
        "ja": "品目ID「{item_id}」は見つかりません。",
    },
    "product_not_found": {
        "en": 'Product ID "{product_id}" was not found.',
        "ja": "商品ID「{product_id}」は見つかりません。",
    },
    "known_item_ids": {
        "en": "Registered item IDs: {ids}",
        "ja": "登録済みの品目ID: {ids}",
    },
    "known_product_ids": {
        "en": "Registered product IDs: {ids}",
        "ja": "登録済みの商品ID: {ids}",
    },
    "known_ids_none": {"en": "(none)", "ja": "（なし）"},

    # --- The clock both entry points open with ---
    "clock": {"en": "{date} ({weekday}) {time}", "ja": "{date}（{weekday}）{time}"},
    "weekday_mon": {"en": "Mon", "ja": "月"},
    "weekday_tue": {"en": "Tue", "ja": "火"},
    "weekday_wed": {"en": "Wed", "ja": "水"},
    "weekday_thu": {"en": "Thu", "ja": "木"},
    "weekday_fri": {"en": "Fri", "ja": "金"},
    "weekday_sat": {"en": "Sat", "ja": "土"},
    "weekday_sun": {"en": "Sun", "ja": "日"},
    # The project's own one-line description (README), plus the clock. Says
    # what this is and that it knows what day it is, before anything else.
    "intro": {
        "en": "teruo — an inventory agent for food trucks and street stalls. {clock}",
        "ja": "teruo — キッチンカー・屋台のための在庫管理エージェント。{clock}",
    },
    # Once onboarding has learned whose shop this is, the opening line says so.
    "intro_named": {
        "en": "teruo — the inventory agent for {shop}. {clock}",
        "ja": "teruo — {shop}のための在庫管理エージェント。{clock}",
    },

    "today_note": {
        "en": "\n\nToday is {today}. Take the date from here, never from memory — build any YYYY-MM argument off it.",
        "ja": "\n\n今日は {today} です。日付はここから取り、記憶で補わないこと。YYYY-MM の引数もここから組み立てる。",
    },

    # --- export_csv ---
    "export_none": {
        "en": "There is nothing to export yet.",
        "ja": "書き出せる記録がまだありません。",
    },
    "export_no_records_for_month": {
        "en": "No records for {month}.",
        "ja": "{month}の記録はありません。",
    },
    "export_months_available": {
        "en": "Months that do have records: {months}",
        "ja": "記録のある月: {months}",
    },
    "export_failed": {
        "en": "Could not write the files: {reason}",
        "ja": "ファイルを書き出せませんでした: {reason}",
    },
    "export_done": {
        "en": "Wrote {count} spreadsheet files to {folder} ({period}):",
        "ja": "{folder} に表計算ファイルを{count}件書き出しました（{period}）:",
    },
    "export_line": {
        "en": "- {file} — {label}, {rows} rows",
        "ja": "- {file} — {label}、{rows}行",
    },
    "export_period_all": {"en": "all records", "ja": "全期間"},
    "export_open_hint": {
        "en": "Five separate files, for feeding another system — accounting software, a script. To just look at the records, or to hand them to someone, ask for Excel instead: that is one file, and Google Sheets opens it as five tabs. Purchase costs are not recorded, so there is no money column for purchases.",
        "ja": "別のシステムに読ませるための5ファイルです（会計ソフト、スクリプトなど）。見るだけ・人に渡すだけなら Excel のほうが1ファイルで済み、Google スプレッドシートでも5タブとして開けます。仕入れ金額は記録していないため、仕入れに金額の列はありません。",
    },
    "export_label_sales": {"en": "sales", "ja": "売上"},
    "export_label_purchases": {"en": "purchases", "ja": "仕入れ"},
    "export_label_counts": {"en": "stock counts", "ja": "棚卸し"},
    "export_label_stock": {"en": "stock right now", "ja": "現在の在庫"},
    "export_label_recipes": {"en": "recipes", "ja": "レシピ"},

    # --- export_excel ---
    "excel_done": {
        "en": "Wrote one Excel workbook to {path} ({period}) — {count} sheets:",
        "ja": "{path} に Excel ファイルを書き出しました（{period}）。シートは{count}枚:",
    },
    "excel_line": {
        "en": "- {label}, {rows} rows",
        "ja": "- {label}、{rows}行",
    },
    "excel_open_hint": {
        "en": "One file, five sheets — hand it over as it is. Excel opens it, and so does Google Sheets (drop it in Drive; the five sheets become five tabs). Numbers are real numbers, so a sum or a pivot works. Purchase costs are not recorded, so there is no money column for purchases.",
        "ja": "1ファイルに5シート、そのまま渡せます。Excel でも Google スプレッドシートでも開けます（Drive に入れると5シートが5タブになります）。数値は数値として入っているので、合計もピボットもそのまま使えます。仕入れ金額は記録していないため、仕入れに金額の列はありません。",
    },
    "excel_unavailable": {
        "en": "Excel output needs the openpyxl library, which is not installed. Install it with 'pip install openpyxl', or ask for CSV instead — the CSV files open in Excel too.",
        "ja": "Excel 形式の書き出しには openpyxl が必要ですが、入っていません。'pip install openpyxl' で入れるか、CSV で書き出してください（CSV も Excel で開けます）。",
    },

    # --- export_csv column headers ---
    "csv_date": {"en": "date", "ja": "日付"},
    "csv_time": {"en": "time", "ja": "時刻"},
    "csv_venue": {"en": "venue", "ja": "出店形態"},
    "csv_product_id": {"en": "product_id", "ja": "商品ID"},
    "csv_product": {"en": "product", "ja": "商品名"},
    "csv_quantity": {"en": "quantity", "ja": "数量"},
    "csv_unit_price": {"en": "unit_price", "ja": "単価"},
    "csv_revenue": {"en": "revenue", "ja": "売上金額"},
    "csv_item_id": {"en": "item_id", "ja": "品目ID"},
    "csv_item": {"en": "item", "ja": "品目名"},
    "csv_amount": {"en": "amount", "ja": "数量"},
    "csv_unit": {"en": "unit", "ja": "単位"},
    "csv_units": {"en": "units", "ja": "本数・袋数"},
    "csv_purchase_unit": {"en": "purchase_unit", "ja": "仕入れ単位"},
    "csv_estimated": {"en": "estimated", "ja": "目安値"},
    "csv_actual_stock": {"en": "counted", "ja": "実測"},
    "csv_book_stock": {"en": "book_value", "ja": "理論値"},
    "csv_gap": {"en": "gap", "ja": "差"},
    "csv_coef_before": {"en": "coefficient_before", "ja": "係数（前）"},
    "csv_coef_after": {"en": "coefficient_after", "ja": "係数（後）"},
    "csv_stock": {"en": "stock", "ja": "在庫"},
    "csv_consumption_type": {"en": "consumption_type", "ja": "消費型"},
    "csv_coefficient": {"en": "coefficient", "ja": "係数"},
    "csv_last_counted": {"en": "last_counted", "ja": "最終棚卸し"},
    "csv_price": {"en": "price", "ja": "価格"},
    "csv_qty_per_serving": {"en": "qty_per_serving", "ja": "1食あたり"},
    "csv_yes": {"en": "yes", "ja": "はい"},
    "csv_no": {"en": "no", "ja": "いいえ"},

    # --- get_recipes ---
    "recipes_none": {"en": "No products registered.", "ja": "商品が登録されていません。"},
    "recipes_line": {
        "en": "- {name} [{id}] ¥{price}: {recipe}",
        "ja": "- {name} [{id}] ¥{price}: {recipe}",
    },
    "recipes_ingredient": {"en": "{name} [{id}] {amount}", "ja": "{name} [{id}] {amount}"},
    "recipes_ingredient_missing": {
        "en": "{id} (unregistered item)",
        "ja": "{id}（未登録の品目）",
    },

    # --- learning phase labels ---
    "growth_fixed": {"en": "coefficient fixed", "ja": "係数固定"},
    "growth_unlearned": {
        "en": "unlearned (waiting for the first empty unit)",
        "ja": "未学習（最初の使い切り待ち）",
    },
    "growth_learning_unit": {
        "en": "learning ({n}/{max} empty units)",
        "ja": "学習中（使い切り {n}回 / {max}回）",
    },
    "growth_stable_unit": {"en": "stable ({n} records)", "ja": "安定（実績{n}回）"},
    "growth_learning": {
        "en": "learning (stock count {n}/{max})",
        "ja": "学習中（棚卸し {n}回 / {max}回）",
    },
    "growth_insufficient": {"en": "not enough stock counts", "ja": "棚卸しデータ不足"},
    "growth_stable": {"en": "stable", "ja": "安定"},
    "growth_unsettled": {
        "en": "coefficient not settling (last {before:.2f} → {after:.2f})",
        "ja": "係数が安定しません（直近 {before:.2f} → {after:.2f}）",
    },

    # --- record_sales ---
    "qty_nonnegative": {
        "en": "Quantity must be zero or more.",
        "ja": "売上数は0以上で指定してください。",
    },
    "venue_invalid": {
        "en": 'venue_type must be "event" or "solo".',
        "ja": '出店形態は "event" か "solo" のどちらかで指定してください。',
    },
    "sales_open_note": {
        "en": "; the open {unit} is at serving {used}",
        "ja": "、開封中の1{unit}は{used}食目",
    },
    "sales_unit_unchanged": {
        "en": "{name}: stock unchanged (running total {total} servings{used_note})",
        "ja": "{name}: 在庫は動かしません（累計{total}食{used_note}）",
    },
    "sales_unit_running_out": {
        "en": "{name}: the open {unit} should run out soon (about {remaining} servings left). Tell me when it's empty.",
        "ja": "{name}: 開封中の1{unit}がそろそろ空きます（推定あと{remaining}食分）。空いたら教えてください。",
    },
    "sales_went_negative": {
        "en": "{name}: the book value ran below zero. There should still be some left — my estimate ran low. Please measure it at closing.",
        "ja": "{name}: 理論値が在庫を割りました。実際にはまだ残っているはずです。こちらの計算が少なく見積もっていました。締めに一度量ってください。",
    },
    "sales_decrease": {
        "en": "{name}: {before} → {after} (down {consumed})",
        "ja": "{name}: {before} → {after}（{consumed}減）",
    },
    "sales_recorded": {
        "en": "Recorded {product} × {quantity}.",
        "ja": "{product} {quantity}個を記録しました。",
    },

    # --- record_count ---
    "count_nonnegative": {
        "en": "Counted stock must be zero or more.",
        "ja": "実測在庫は0以上で指定してください。",
    },
    "count_unit_recounted": {
        "en": "Recounted {name} units. Servings per {unit} is settled by empty-unit records.",
        "ja": "{name}のユニット数を数え直しました。「1{unit}＝何食分」は使い切りの記録で確定します。",
    },
    "count_matches": {
        "en": "{name} matches the book value.",
        "ja": "{name}は理論値どおりです。",
    },
    "fewer": {"en": "fewer", "ja": "少ない"},
    "more": {"en": "more", "ja": "多い"},
    "count_gap": {
        "en": "{name} counted {diff} {direction} than the book value. This item is tracked by count, so please check for unlogged sales or waste.",
        "ja": "{name}は理論値より{diff}{direction}実測でした。数で管理する品目のため、記録漏れや廃棄がなかったかご確認ください。",
    },
    "count_first": {
        "en": "{name}: first stock count, so the coefficient stays at {coef:.2f}.",
        "ja": "{name}は初回棚卸しのため、係数は{coef:.2f}のままです。",
    },
    "count_coef_updated": {
        "en": "Updated the coefficient for {name} from {before:.2f} to {after:.2f}.",
        "ja": "{name}の係数を{before:.2f}から{after:.2f}に更新しました。",
    },
    "count_cap_hit": {
        "en": " The coefficient has hit the cap of what portioning variance can explain (recipe value ±{bound}{unit}/serving). I won't adjust it any further on my own. The recipe itself may need a review.",
        "ja": " 係数が盛り付けで説明できる範囲（レシピ値±{bound}{unit}/食）の上限に達しています。これ以上は自動で調整しません。レシピそのものの見直しが必要かもしれません。",
    },
    "cap_hit_fragment": {"en": "hit the cap", "ja": "上限に達しています"},
    "count_big_jump": {
        "en": " That is a big jump. Please double-check the count as well.",
        "ja": " 大きくズレています。数え間違いの可能性もご確認ください。",
    },
    "count_no_sales": {
        "en": "{name} has no sales since the last count, so the coefficient stays at {coef:.2f}.",
        "ja": "{name}は前回棚卸し後の売上がないため、係数は{coef:.2f}のままです。",
    },
    "count_learning_done": {
        "en": " Learning is complete. {name}: {base} → {final} per serving ({percent:+.0f}%). Please confirm this range is acceptable.",
        "ja": " 学習が終了しました。{name}: 1食あたり{base} → {final}（{percent:+.0f}%）。この幅でよろしければ、一度ご確認ください。",
    },
    "count_still_learning": {
        "en": " Still {growth} — treat the numbers as rough for now.",
        "ja": " {growth}。数字は参考程度に見てください。",
    },
    "count_unsettled_note": {"en": " Note: {growth}.", "ja": " {growth}。"},
    "count_stock_updated": {
        "en": "{message} Stock updated to {stock}.{warning}{growth_note}",
        "ja": "{message} 在庫を{stock}に更新しました。{warning}{growth_note}",
    },

    # --- record_unit_used ---
    "unit_not_unit_type": {
        "en": "{name} is not a unit-tracked item. Use record_count for stock counts.",
        "ja": "{name}はユニット型ではありません。棚卸しは record_count を使ってください。",
    },
    "unit_opened": {
        "en": "Recorded that a {unit} of {name} was opened. Tell me when it's empty — that will settle how many servings one {unit} holds.",
        "ja": "{name}の開封を記録しました。この1{unit}が空になったらまた教えてください。そこで「1{unit}＝何食分」が確定します。",
    },
    "unit_no_sales": {
        "en": "No sales were recorded since it was opened, so this {unit} won't count toward the coefficient. Please check for missed sales entries.",
        "ja": "開封からの売上が記録されていないため、今回の1{unit}は係数に反映しません。売上の記録漏れがないかご確認ください。",
    },
    "unit_out_of_band": {
        "en": "{servings} servings from one {unit} is more than ±{pct}% off the past average ({average:.0f} servings). Not counting it toward the coefficient. It may have been used for something else, or a sale or empty-unit record may be missing.",
        "ja": "1{unit}で{servings}食は、過去実績（平均{average:.0f}食）の±{pct}%を超えています。係数には反映しません。別用途に使ったか、売上か使い切りの記録漏れの可能性があります。",
    },
    "unit_anomaly_result": {
        "en": "{name}: {anomaly} {stock} left.",
        "ja": "{name}: {anomaly} 残り{stock}。",
    },
    "unit_capacity_note": {
        "en": " (about {servings} servings left)",
        "ja": "（あと約{servings}食分）",
    },
    "unit_used_result": {
        "en": "{name}: {servings} servings from that {unit}. Empties recorded: {count} → ≈{coef:.0f} servings per {unit}. {stock} left{capacity_note}.",
        "ja": "{name}: 1{unit}で{servings}食でした。実績{count}回 → 1{unit}≈{coef:.0f}食。残り{stock}{capacity_note}。",
    },

    # --- record_purchase ---
    "purchase_empty": {"en": "The purchase list is empty.", "ja": "仕入れ明細が空です。"},
    "purchase_item_not_found": {
        "en": 'Item ID "{item_id}" was not found. Check the ID below; register it with register_item only if it is really a new item.',
        "ja": "品目ID「{item_id}」は見つかりません。下のID一覧を確認し、本当に新しい品目の時だけ register_item で登録してください。",
    },
    "purchase_needs_amount_or_units": {
        "en": "{name}: needs either amount or units.",
        "ja": "{name}: amount か units のどちらかが必要です。",
    },
    "purchase_no_unit_weight": {
        "en": "{name}: no estimated amount per {purchase_unit} is set, so please provide the actual amount.",
        "ja": "{name}: 1{purchase_unit}あたりの量が未設定のため、実際の量（amount）を指定してください。",
    },
    "purchase_nonnegative": {
        "en": "{name}: purchase amount must be zero or more.",
        "ja": "{name}: 仕入れ量は0以上で指定してください。",
    },
    "purchase_estimated_note": {
        "en": " (rough estimate — tell me the actual amount if you learn it)",
        "ja": "（目安で仮置き。実際の量が分かれば教えてください）",
    },
    "purchase_line": {
        "en": "{name} +{amount} ({before} → {after}){note}",
        "ja": "{name} +{amount}（{before} → {after}）{note}",
    },
    "purchase_recorded": {"en": "Recorded the purchases.", "ja": "仕入れを記録しました。"},

    # --- get_stock_status ---
    "status_coef_unit": {
        "en": "≈{coef:.0f} servings per {unit}",
        "ja": "1{unit}≈{coef:.0f}食",
    },
    "status_open_note": {
        "en": ", open {unit} at serving {used}",
        "ja": "、開封中の1{unit}は{used}食目",
    },
    "status_line_unit": {
        "en": "- {name} [{id}]: {stock}, {coef}, {growth}{opened_note}, last counted {last}",
        "ja": "- {name} [{id}]: {stock}、{coef}、{growth}{opened_note}、最終棚卸し {last}",
    },
    "status_line_unit_unlearned": {
        "en": "- {name} [{id}]: {stock}, {growth}{opened_note}, last counted {last}",
        "ja": "- {name} [{id}]: {stock}、{growth}{opened_note}、最終棚卸し {last}",
    },
    "status_line_count": {
        "en": "- {name} [{id}]: {stock}, coefficient fixed, last counted {last}",
        "ja": "- {name} [{id}]: {stock}、係数固定、最終棚卸し {last}",
    },
    "status_line_weight": {
        "en": "- {name} [{id}]: {stock}, coefficient {coef:.2f}, {growth}, last counted {last}",
        "ja": "- {name} [{id}]: {stock}、係数 {coef:.2f}、{growth}、最終棚卸し {last}",
    },
    "status_recent_changes": {"en": "Recent settings changes:", "ja": "直近の設定変更:"},

    # --- get_sales_summary ---
    "sales_none": {"en": "No sales records yet.", "ja": "まだ売上記録がありません。"},
    "venue_event": {"en": "Event days", "ja": "イベント出店"},
    "venue_solo": {"en": "Solo days", "ja": "単独出店"},
    "sales_block_header": {
        "en": "{venue} ({days} business days):",
        "ja": "{venue}（営業日数 {days}日）:",
    },
    "sales_product_line": {
        "en": "- {name}: {total} total, {average}/day average",
        "ja": "- {name}: 合計{total}個、1日平均 {average}個",
    },

    # --- get_capacity ---
    "capacity_no_products": {"en": "No products registered.", "ja": "商品が登録されていません。"},
    "capacity_unlearned_note": {
        "en": " (excluding {names} — still unlearned)",
        "ja": "（{names}は学習前のため計算に含めていません）",
    },
    "capacity_missing": {
        "en": '- {product}: cannot compute (item "{missing}" is unregistered or inactive)',
        "ja": "- {product}: 計算不可（品目「{missing}」が未登録または無効）",
    },
    "capacity_none": {
        "en": "- {product}: no items available to compute a remaining count{note}",
        "ja": "- {product}: 残数を計算できる品目がありません{note}",
    },
    "capacity_negative": {
        "en": "- {product}: the book value for {bottleneck} ran below zero. A recount is needed{note}",
        "ja": "- {product}: {bottleneck}の理論値が在庫を割っています。実測が必要です{note}",
    },
    "capacity_line": {
        "en": "- {product}: {servings} servings left (bottleneck: {bottleneck}){note}",
        "ja": "- {product}: あと{servings}食（ボトルネック: {bottleneck}）{note}",
    },

    # --- get_monthly_reconciliation ---
    "month_format": {
        "en": "month must be in YYYY-MM format, e.g. 2026-09.",
        "ja": "month は YYYY-MM 形式で指定してください。例: 2026-09",
    },
    "short": {"en": "short", "ja": "不足"},
    "over": {"en": "over", "ja": "余剰"},
    "recon_weight_finding": {
        "en": "- {name}: {period}: purchased {purchased}, recipe-basis consumption {consumption} ({servings} servings sold). The gap vs. the physical count, {gap} ({direction}), is more than portioning variance can explain (±{bound}{unit}/serving = {allowance}). Please check for missed purchase or sales records",
        "ja": "- {name}: {period}に仕入れ{purchased}、レシピ理論消費{consumption}（売上{servings}食）。実測との差 {gap}（{direction}）は、盛り付けのブレ（±{bound}{unit}/食 ＝ {allowance}）では説明できません。仕入れか売上の記録漏れがないかご確認ください",
    },
    "recon_count_finding": {
        "en": "- {name}: gap vs. the physical count over {period}: {gap} ({direction}). This item is tracked by count, so please check for unlogged waste or missed records",
        "ja": "- {name}: {period}の実測との差 {gap}（{direction}）。数で管理する品目のため、記録漏れや廃棄がなかったかご確認ください",
    },
    "recon_header": {
        "en": "Monthly reconciliation for {month}:",
        "ja": "{month} の月次突合:",
    },
    "recon_no_gaps": {"en": "No unexplained gaps.", "ja": "説明できない差はありません。"},
    "recon_uncheckable": {
        "en": "Items with fewer than two stock counts (cannot reconcile): {names}",
        "ja": "棚卸しが2回未満で突合できない品目: {names}",
    },

    # --- register_item ---
    "item_id_format": {
        "en": "item_id must be lowercase letters and underscores, e.g. sauce_yogurt.",
        "ja": "item_id は英小文字とアンダースコアで指定してください。例: sauce_yogurt",
    },
    "item_exists": {
        "en": 'Item ID "{item_id}" already exists. Use a different ID.',
        "ja": "品目ID「{item_id}」は既に存在します。別のIDを使ってください。",
    },
    "unit_type_invalid": {
        "en": 'unit_type must be one of "weight" / "volume" / "count".',
        "ja": 'unit_type は "weight" / "volume" / "count" のいずれかです。',
    },
    "consumption_type_invalid": {
        "en": 'consumption_type must be one of "count" / "weight" / "unit".',
        "ja": 'consumption_type は "count" / "weight" / "unit" のいずれかです。',
    },
    "stock_nonnegative": {
        "en": "Stock must be zero or more.",
        "ja": "在庫は0以上で指定してください。",
    },
    "log_item_added": {
        "en": "Added item: {name} ({stock})",
        "ja": "品目を追加: {name}（{stock}）",
    },
    "item_registered_unit": {
        "en": "Registered {name} ({stock}). Servings per {unit} will be learned from the first empty unit.",
        "ja": "{name}を登録しました（{stock}）。1{unit}＝何食分かは最初の使い切りで学習します。",
    },
    "item_registered_count": {
        "en": "Registered {name} ({stock}, tracked by count).",
        "ja": "{name}を登録しました（{stock}、数どおり管理）。",
    },
    "item_registered_weight": {
        "en": "Registered {name} ({stock}; coefficient starts at 1.00 and learns from stock counts).",
        "ja": "{name}を登録しました（{stock}、係数1.00から学習開始）。",
    },

    # --- register_product ---
    "product_id_format": {
        "en": "product_id must be lowercase letters and underscores.",
        "ja": "product_id は英小文字とアンダースコアで指定してください。",
    },
    "product_exists": {
        "en": 'Product ID "{product_id}" already exists.',
        "ja": "商品ID「{product_id}」は既に存在します。",
    },
    "price_nonnegative": {"en": "Price must be zero or more.", "ja": "価格は0以上で指定してください。"},
    "recipe_empty": {
        "en": "The recipe is empty. Specify at least one ingredient.",
        "ja": "レシピが空です。材料を1つ以上指定してください。",
    },
    "recipe_element_invalid": {
        "en": "Every recipe element needs an item_id and a qty greater than zero.",
        "ja": "レシピの各要素には item_id と 0より大きい qty が必要です。",
    },
    "recipe_duplicate": {
        "en": 'Item "{item_id}" appears twice in the recipe.',
        "ja": "品目「{item_id}」がレシピに重複しています。",
    },
    "recipe_missing_items": {
        "en": "These items are unregistered. Register them first with register_item: {names}",
        "ja": "次の品目が未登録です。先に register_item で登録してください: {names}",
    },
    "log_product_added": {
        "en": "Added product: {name} (¥{price}) — recipe: {recipe}",
        "ja": "商品を追加: {name}（¥{price}） レシピ: {recipe}",
    },
    "product_registered": {
        "en": "Registered {name} (¥{price}). Recipe: {recipe}",
        "ja": "{name}（¥{price}）を登録しました。レシピ: {recipe}",
    },

    # --- update_recipe ---
    "item_unregistered": {
        "en": 'Item ID "{item_id}" is unregistered. Check the ID below; register it with register_item only if it is really a new item.',
        "ja": "品目ID「{item_id}」は未登録です。下のID一覧を確認し、本当に新しい品目の時だけ register_item で登録してください。",
    },
    "recipe_qty_nonnegative": {
        "en": "qty must be zero or more (0 removes the ingredient).",
        "ja": "qty は0以上で指定してください（0で材料を外す）。",
    },
    "recipe_not_include": {
        "en": "The recipe for {product} does not include {item}.",
        "ja": "{product}のレシピに{item}は入っていません。",
    },
    "log_recipe_removed": {
        "en": "Recipe for {product}: {item} {amount} → removed",
        "ja": "{product}のレシピ: {item} {amount} → 削除",
    },
    "recipe_removed": {
        "en": "Removed {item} from the recipe for {product}.",
        "ja": "{product}のレシピから{item}を外しました。",
    },
    "log_recipe_added": {
        "en": "Recipe for {product}: {item} none → {amount}",
        "ja": "{product}のレシピ: {item} なし → {amount}",
    },
    "recipe_added": {
        "en": "Added {item} {amount} to the recipe for {product}.",
        "ja": "{product}のレシピに{item} {amount}を追加しました。",
    },
    "log_recipe_changed": {
        "en": "Recipe for {product}: {item} {before} → {after}",
        "ja": "{product}のレシピ: {item} {before} → {after}",
    },
    "recipe_changed": {
        "en": "Changed {item} in {product} from {before} to {after}.",
        "ja": "{product}の{item}を{before}から{after}に変更しました。",
    },

    # --- update_item ---
    "update_item_nothing": {
        "en": "Specify what to change (new_name / new_unit / new_purchase_unit / new_unit_weight).",
        "ja": "変更内容（new_name / new_unit / new_purchase_unit / new_unit_weight）を指定してください。",
    },
    "unit_weight_alone": {
        "en": "Cannot set an estimated amount alone. Also specify the purchase unit (new_purchase_unit).",
        "ja": "目安量だけは登録できません。仕入れ単位（new_purchase_unit）も指定してください。",
    },
    "purchase_weight_note": {
        "en": " (1 {purchase_unit} ≈ {amount})",
        "ja": "（1{purchase_unit}≈{amount}）",
    },
    "log_purchase_unit_set": {
        "en": "Set purchase unit for {name}: {purchase_unit}{note}",
        "ja": "{name}の仕入れ単位を設定: {purchase_unit}{note}",
    },
    "purchase_unit_registered": {
        "en": "Registered the purchase unit as {purchase_unit}{note}. Tell me the actual amount at purchase time when you learn it — real measurements will refine the estimate.",
        "ja": "仕入れ単位を{purchase_unit}{note}として登録しました。実際の量が分かったら仕入れ時に教えてください。実測で目安を更新します。",
    },
    "log_item_renamed": {
        "en": "Renamed item: {old} → {new}",
        "ja": "品目名を変更: {old} → {new}",
    },
    "item_renamed": {
        "en": "Renamed {old} to {new}.",
        "ja": "名前を{old}から{new}に変更しました。",
    },
    "log_unit_converted": {
        "en": "Changed unit for {name}: {old_unit} → {new_unit} (stock {old_stock} → {new_stock}, recipes converted)",
        "ja": "{name}の単位を変更: {old_unit} → {new_unit}（在庫 {old_stock} → {new_stock}、レシピも換算）",
    },
    "recipes_converted_note": {
        "en": "Recipes ({names}) were converted too.",
        "ja": "レシピ（{names}）も換算済み。",
    },
    "unit_converted": {
        "en": "Converted the unit from {old_unit} to {new_unit} (stock {stock}). {note}",
        "ja": "単位を{old_unit}から{new_unit}に換算しました（在庫 {stock}）。{note}",
    },
    "unit_change_needs_recount": {
        "en": "Changing the unit of {name} from {old_unit} to {new_unit} cannot be converted automatically. The current stock of {old_stock} must be recounted. Tell me how many {new_unit} there are now (pass it as new_stock).",
        "ja": "{name}の単位を{old_unit}から{new_unit}に変えるには換算ができません。現在の在庫 {old_stock} を数え直す必要があります。いま何{new_unit}あるか教えてください（new_stock で指定）。",
    },
    "log_unit_changed": {
        "en": "Changed unit for {name}: {old_unit} → {new_unit} (stock {old_stock} → {new_stock}, coefficient reset to 1.0 to relearn)",
        "ja": "{name}の単位を変更: {old_unit} → {new_unit}（在庫 {old_stock} → {new_stock}、係数1.0に戻して学習し直し）",
    },
    "recipes_old_unit_warning": {
        "en": "Recipe amounts ({names}) are still in the old unit. Fix them with update_recipe.",
        "ja": "レシピ（{names}）の数量は旧単位のままです。update_recipe で新単位の量に直してください。",
    },
    "unit_changed": {
        "en": "Changed the unit from {old_unit} to {new_unit} and recounted the stock as {stock}. The coefficient is back to 1.0 and will relearn. {warning}",
        "ja": "単位を{old_unit}から{new_unit}に変更し、在庫を{stock}で数え直しました。係数は1.0に戻し、学習し直します。{warning}",
    },
    "unit_already": {"en": "The unit is already {unit}.", "ja": "単位は既に{unit}です。"},
    "nothing_changed": {"en": "Nothing was changed.", "ja": "変更はありませんでした。"},

    # --- delete_product ---
    "delete_confirm": {
        "en": "You are about to delete {name} (¥{price}). A deleted product cannot be restored (its items and sales history remain). Confirm with the owner that they really want this, then call again with confirm=True.",
        "ja": "{name}（¥{price}）を削除しようとしています。一度消すと商品は戻せません（品目と売上履歴は残ります）。本当に削除してよいか店主に確認し、承認されたら confirm=True でもう一度呼び出してください。",
    },
    "log_product_deleted": {
        "en": "Deleted product: {name} (¥{price})",
        "ja": "商品を削除: {name}（¥{price}）",
    },
    "product_deleted": {
        "en": "Deleted {name}. Its items and sales history are still there.",
        "ja": "{name}を削除しました。品目と売上履歴は残っています。",
    },

    # --- reset_shop ---
    "reset_confirm": {
        "en": "Ready to set this shop aside: {items} items, {products} products, {history} records. Nothing is deleted — the file is kept under a dated name. Confirm with the owner, then call again with confirm=True.",
        "ja": "この店を退避する準備ができました: 品目{items}・商品{products}・履歴{history}件。削除はせず、日付付きの名前でファイルを残します。店主に確認し、承認されたら confirm=True でもう一度呼び出してください。",
    },
    "reset_done": {
        "en": "Set aside as {archive}. Starting fresh — the onboarding interview begins now.",
        "ja": "{archive} として退避しました。まっさらの状態から、初回カウンセリングを始めます。",
    },

    # --- update_config ---
    "config_nothing": {
        "en": "Specify what to set (new_shop_name, new_passphrase or new_notify_email).",
        "ja": "設定内容（new_shop_name / new_passphrase / new_notify_email）を指定してください。",
    },
    "log_shop_name_set": {
        "en": "Shop name set: {shop}",
        "ja": "店名を設定: {shop}",
    },
    "shop_name_set": {
        "en": "Noted — this is {shop}'s teruo from now on.",
        "ja": "覚えました。これからは{shop}の teruo です。",
    },
    "log_passphrase_set": {"en": "Passphrase set", "ja": "合言葉を設定しました"},
    "hidden": {"en": "(hidden)", "ja": "（非表示）"},
    "passphrase_set": {
        "en": "Passphrase set. It will be needed for recipe and unit changes.",
        "ja": "合言葉を設定しました。レシピや単位の変更時に必要になります。",
    },
    "log_email_set": {
        "en": "Notification email set: {email}",
        "ja": "通知先メールを設定: {email}",
    },
    "email_set": {
        "en": "Notifications will go to {email}.",
        "ja": "通知先を{email}に設定しました。",
    },

    # --- CLI (main.py) ---
    "cli_missing_env": {
        "en": "Missing required Replit Secrets / environment variables: {names}",
        "ja": "起動に必要なReplit Secrets / 環境変数がありません: {names}",
    },
    "cli_bad_language": {
        "en": "Unknown language: {value}. Use --lang en or --lang ja.",
        "ja": "言語 {value} は使えません。--lang en か --lang ja を指定してください。",
    },
    "cli_counseling_start": {
        "en": "Starting the onboarding interview (about 10 minutes; progress is saved if you stop midway).",
        "ja": "初回カウンセリングを始めます（10分ほど。途中でやめても保存されます）。",
    },
    "cli_counseling_kickoff": {
        "en": "Begin the onboarding interview. Ask your first question.",
        "ja": "カウンセリングを開始してください。最初の質問をどうぞ。",
    },
    "cli_error": {
        "en": "Something went wrong: {error}",
        "ja": "処理できませんでした: {error}",
    },
    "cli_welcome": {
        "en": "Sales, stock counts, purchases — tell me as they happen. Type exit to quit.",
        "ja": "売上・棚卸し・仕入れ、その都度お知らせください。終了は exit。",
    },

    # --- Files handed to teruo (attachments.py) ---
    "attachment_no_url": {
        "en": "I can't open links. Save the page as a photo or a file and give me the file name.",
        "ja": "リンクは開けません。写真かファイルとして保存して、ファイル名で渡してください。",
    },
    "attachment_not_found": {
        "en": "No file named {path} here. Check the name, or give me the full path.",
        "ja": "{path} というファイルが見つかりません。名前を確認するか、フルパスで渡してください。",
    },
    "attachment_too_large": {
        "en": "{path} is too big (the limit is about {limit} MB). Use a smaller photo, or split the file.",
        "ja": "{path} は大きすぎます（上限は約{limit}MB）。写真を小さくするか、ファイルを分けてください。",
    },
    "attachment_unreadable": {
        "en": "Could not read {path}: {error}",
        "ja": "{path} を読めませんでした: {error}",
    },
    "attachment_too_many": {
        "en": "That's too many files at once. Up to {limit} per message, please.",
        "ja": "一度に渡せるファイルが多すぎます。1回につき{limit}個までにしてください。",
    },
    "attachment_unsupported": {
        "en": "I can't read {path}. Photos (png jpg gif webp) and documents (xlsx xls csv pdf docx doc html txt md) only.",
        "ja": "{path} は読めない形式です。写真（png jpg gif webp）と文書（xlsx xls csv pdf docx doc html txt md）のみ対応しています。",
    },
    "attachment_default_text": {
        "en": "Here is {names}. Read it and show me what you got before registering anything.",
        "ja": "{names} を渡します。読み取った内容を見せてください。登録はその後で。",
    },

    # --- Web entry point (web.py) ---
    "web_tagline": {
        "en": "inventory agent for food trucks and street stalls",
        "ja": "キッチンカー・屋台の在庫管理エージェント",
    },
    "web_placeholder": {
        "en": "Type here — or press + to hand over a photo or a spreadsheet",
        "ja": "ここに入力 — ＋ から写真や表計算ファイルを渡せます",
    },
    "web_send": {"en": "Send", "ja": "送信"},
    "web_attach": {
        "en": "Hand over a photo or a file",
        "ja": "写真やファイルを渡す",
    },
    "web_fact_badge": {"en": "calculated in Python", "ja": "Pythonが計算"},
    "web_working": {"en": "working", "ja": "処理中"},
    "web_drop_hint": {"en": "Drop to hand over", "ja": "ドロップで渡す"},
    "web_download_hint": {
        "en": "Ready to download:",
        "ja": "ダウンロードできます:",
    },
    "web_busy": {
        "en": "Still working on the previous message — one at a time.",
        "ja": "前のメッセージを処理中です。1件ずつお願いします。",
    },
    "web_counseling_banner": {
        "en": "Onboarding — registering this shop's setup. About ten minutes; progress is saved if you stop.",
        "ja": "初回カウンセリング中 — お店の構成を登録しています。10分ほど。途中でやめても保存されます。",
    },
    "language_followed": {
        "en": "Switching to English from here. I've remembered it, so the next launch starts in English.",
        "ja": "ここからは日本語で続けます。設定として覚えたので、次の起動も日本語です。",
    },
    "web_greeting": {
        "en": "Sales, stock counts, purchases — tell me as they happen.",
        "ja": "売上・棚卸し・仕入れ、その都度お知らせください。",
    },
    "web_disconnected": {
        "en": "The connection dropped. Entries already made are saved; reload to carry on.",
        "ja": "接続が切れました。入力済みの分は保存されています。再読み込みで続けられます。",
    },

    # Labels for the activity strip — what the owner sees while teruo works.
    # Keyed by tool name; the three roles read as roles, not function names.
    "tool_record_keeper": {"en": "Record keeper", "ja": "記録係"},
    "tool_observer_check": {"en": "Observer", "ja": "観測係"},
    "tool_record_sales": {"en": "Recording sales", "ja": "売上を記録"},
    "tool_record_count": {"en": "Recording a stock count", "ja": "棚卸しを記録"},
    "tool_record_purchase": {"en": "Recording a purchase", "ja": "仕入れを記録"},
    "tool_record_unit_used": {"en": "Recording an empty unit", "ja": "使い切りを記録"},
    "tool_get_stock_status": {"en": "Reading stock", "ja": "在庫を確認"},
    "tool_get_sales_summary": {"en": "Totalling sales", "ja": "売上を集計"},
    "tool_get_capacity": {"en": "Checking servings left", "ja": "残り食数を確認"},
    "tool_get_recipes": {"en": "Reading recipes", "ja": "レシピを確認"},
    "tool_export_csv": {"en": "Writing spreadsheet files", "ja": "表計算ファイルを書き出し"},
    "tool_export_excel": {"en": "Writing an Excel file", "ja": "Excel ファイルを書き出し"},
    "tool_get_monthly_reconciliation": {"en": "Monthly reconciliation", "ja": "月次突合"},
    "tool_register_item": {"en": "Registering an item", "ja": "品目を登録"},
    "tool_register_product": {"en": "Registering a product", "ja": "商品を登録"},
    "tool_update_recipe": {"en": "Updating a recipe", "ja": "レシピを更新"},
    "tool_update_item": {"en": "Updating an item", "ja": "品目を更新"},
    "tool_delete_product": {"en": "Deleting a product", "ja": "商品を削除"},
    "tool_update_config": {"en": "Updating settings", "ja": "設定を更新"},
    "tool_reset_shop": {"en": "Resetting the shop", "ja": "店を初期化"},
}

# Fail at import if a translation is missing — never at the counter.
for _key, _variants in MESSAGES.items():
    _missing = [lang for lang in LANGUAGES if not _variants.get(lang)]
    if _missing:
        raise RuntimeError(f"i18n: message {_key!r} lacks {_missing}")
