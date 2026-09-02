# Design Doc A — Food Truck Inventory Agent

> English translation of [design.md](design.md). The Japanese original is authoritative.

Tier 1 (the initial implementation) was built from the user-provided design doc
`Pasted--A-0-Replit-Agent--1788164012029_1788164012029.txt`.
This document carries on from it and defines the extension to Tiers 2–4.

The interface remains a terminal CLI only.
Web UI, databases, automated ordering, email, weather, and authentication are out of scope.
Every "notification" means output displayed in the CLI (at startup and when `check_alerts` runs).

**Shared principle: for every Tier, all numeric computation happens on the Python side (in tools);
the AI never does arithmetic in its head.** The agent only calls tools and relays their results.

---

## 1. Tier Classification

| Tier | Nature | Examples | Management approach |
|------|------|----|----------|
| 1 | Depletes, proportional to recipe, fast turnover | Sausages, buns | Subtract recipe × coefficient; correct the coefficient at stock count |
| 2 | Depletes, varies by staff and customer, fast turnover | Ketchup, mustard | Subtract based on "how many servings per bottle"; confidence decays quickly |
| 3 | Depletes, predictable by calculation, slow turnover | Wrappers, gas canisters, frying oil | Don't chase precision; protect with lead time + safety stock |
| 4 | Doesn't deplete, has due dates | Inspections, payments, business permit renewals | No consumption calculation; notify by due date |

## 2. Engine Split

The engine is split in two, each as an independent module.

- **Consumption engine** (`consumption.py`): handles Tiers 1–3.
  Subtracts stock based on orders (sales) and business days. Stock-count corrections,
  confidence calculation, and Tier 3 days-remaining calculation also live here.
- **Calendar engine** (`calendar_engine.py`): handles Tier 4.
  Performs no consumption calculation at all; decides notifications purely from due dates and lead times.
  (The file is named `calendar_engine.py` to avoid clashing with the standard library `calendar` module.)

`tools.py` stays a thin wrapper exposed to the agent; the calculation logic moves into
the two engines (the existing Tier 1 logic also moves to `consumption.py`).

```
main.py             — CLI, agent definition, startup alert display
tools.py            — tools exposed to the agent (thin wrappers)
consumption.py      — consumption engine (Tiers 1–3)
calendar_engine.py  — calendar engine (Tier 4)
store.py            — persistence (unchanged)
data/state.json     — state
```

## 3. Handling Business Days

- **A business day is any date with at least one sales record.**
- The first time `record_sales` records a sale for a new date, that date counts as one business day,
  and Tier 3 "per business day" items are decremented on the spot.
- To prevent double subtraction, processed business days are recorded in the
  `business_days` array in `state.json` (a list of date strings).
- Limitation: a business day with zero sales cannot be counted automatically (accepted, since this is rare in practice).

## 4. Confidence (Tiers 1 and 2)

"How much the calculated stock can be trusted" is **derived** from the number of business days
elapsed since the last stock count (it is not stored, to avoid drift from a stored value).

```
confidence = max(0, 1 − elapsed_business_days / D) × 100 (%)
```

- D is a per-Tier constant (defined in code): **Tier 1 = 20 business days, Tier 2 = 7 business days**.
  Tier 2 decays faster because usage varies by staff and customer, so its coefficient fluctuates more.
- When confidence drops **below 30%**, raise a "stock count recommended" alert.
- Tier 3 has no confidence value (turnover is slow, so the coefficient never matures; we don't chase precision).

## 5. Design by Tier

### Tier 1 (existing; changes only)

The calculation method stays as in the current implementation (recipe × coefficient, coefficient corrected at stock count, correction clamped to 0.8–1.5×).
There are two changes:

1. Tier 1 items now get confidence display and alerts (§4).
2. Restocks are included when computing actual consumption for coefficient correction (following the introduction of `record_restock` in §6):
   `actual consumption = previous count + restocks during the period − current count`

### Tier 2 — Depletes, varies by staff and customer, fast turnover

- Consumption is expressed as **"how many servings one bottle covers"** (`servings_per_unit`).
  Example: one bottle of ketchup covers 50 servings.
- Tier 2 items are added to product recipes; `qty` is the number of servings' worth used per serving sold (normally 1).
- Consumption for N servings sold: `N × qty ÷ servings_per_unit` bottles.
- Correction at stock count (computed by the consumption engine):
  ```
  servings served S            = total servings of relevant sales since the previous stock count
  actual consumption (bottles) = previous count + restocks during the period − current count
  new servings_per_unit        = S ÷ actual consumption
  ```
  Since large variation is expected, the correction is clamped to **0.5–2.0×** the current value
  (wider than Tier 1's 0.8–1.5). No correction is applied when actual consumption is 0 or less.
- Confidence decays with D = 7 business days (§4).

### Tier 3 — Depletes, predictable by calculation, slow turnover

- **Two kinds of consumption unit are allowed.** Each item declares its kind in the `consumption` field:
  - `{"type": "per_order", "qty": 1}` — per order (e.g., wrapper = 1 sheet).
    On `record_sales`, subtract `servings sold × qty`. Not listed in recipes;
    proportional to servings across all products.
  - `{"type": "per_business_day", "qty": 0.4}` — per business day (e.g., gas canister = 0.4 canisters).
    Subtract `qty` at the first sale of a new business day (§3).
- **No coefficient correction** (turnover is slow, so the coefficient never matures; we don't chase precision).
  A stock count simply overwrites the stock.
- **Protected by lead time and safety stock.** Each item has
  `lead_time_days` (days from ordering to delivery) and `safety_days` (safety margin in days).
- Days remaining (in business days) is calculated as:
  - per_business_day: `days remaining = stock ÷ qty`
  - per_order: `days remaining = stock ÷ (average consumption per business day over the last 14 business days)`.
    If the average is 0, display "cannot be calculated" and raise no alert.
- **Raise an ordering alert when `days remaining ≤ lead_time_days + safety_days`.**
  Days remaining is in business days while lead time is in calendar days, but since business days remaining ≤ calendar days remaining,
  this comparison always errs on the safe side (it fires early).

### Tier 4 — Doesn't deplete, has due dates

- **No consumption calculation whatsoever.** Handled only by the calendar engine.
- Each task holds the following **four** fields:

  | Field | Meaning | Example |
  |---|---|---|
  | `next_due` | Next due date (YYYY-MM-DD) | 2026-11-01 |
  | `cycle` | Recurrence cycle; either `{"months": n}` or `{"days": n}` | `{"months": 6}` |
  | `lead_time_days` | How many days before the due date preparation must begin | 14 |
  | `impact` | Impact if missed (free text) | "Business shutdown" |

- **Raise a due-date alert when `today ≥ next_due − lead_time_days`**
  (show the impact alongside it so the severity comes across). Overdue tasks are highlighted further.
- Recording completion (`record_task_done`) updates `next_due = current next_due + cycle`
  (based on the scheduled date, which suits fixed-cycle tasks such as payments).
  For cases where the next date should be based on the completion date, such as inspections, or when a task is significantly late,
  `record_task_done` accepts an optional argument to set the next due date directly.

## 6. Tool List

| Tool | Scope | Description |
|---|---|---|
| `record_sales(date, product_id, quantity)` | Tiers 1–3 | [Extended] In addition to Tier 1, subtracts Tier 2 (via recipe) and Tier 3 per_order. On a new business day, also subtracts per_business_day and records the day in `business_days` |
| `record_count(item_id, actual_stock)` | Tiers 1–3 | [Extended] Tier 1: coefficient correction; Tier 2: servings_per_unit correction; Tier 3: overwrite only. All update `last_counted` |
| `record_restock(item_id, quantity, date)` | Tiers 1–3 | [New] Records a restock and adds to stock. Keeps a history in `restocks` (required, because without restock records neither Tier 3 days remaining nor Tier 1/2 coefficient correction holds up) |
| `get_stock_status()` | All Tiers | [Extended] Tiers 1/2: stock, coefficient, confidence. Tier 3: stock, days remaining. Tier 4: next due date, days remaining, impact |
| `record_task_done(task_id, date, next_due=None)` | Tier 4 | [New] Records completion and advances the next due date by the cycle (an explicit next_due takes precedence) |
| `check_alerts()` | All Tiers | [New] Returns stock-count recommendations (confidence < 30%), ordering alerts (Tier 3), and due-date alerts (Tier 4) together. `main.py` also calls it directly at startup and displays the result |

## 7. Data Model (state.json)

Existing keys stay unchanged; fields and keys are added. Migration of existing data is
absorbed by treating "missing new fields as defaults"; no conversion script is written.

```json
{
  "products": [
    {
      "id": "hotdog",
      "name": "Hot dog",
      "recipe": [
        { "item_id": "sausage", "qty": 1 },
        { "item_id": "bun", "qty": 1 },
        { "item_id": "ketchup", "qty": 1 }
      ]
    }
  ],
  "items": [
    {
      "id": "sausage", "name": "Sausage", "tier": 1,
      "unit": "pcs", "stock": 3000.0,
      "coefficient": 1.0, "last_counted": "..."
    },
    {
      "id": "ketchup", "name": "Ketchup", "tier": 2,
      "unit": "bottle", "stock": 4.0,
      "servings_per_unit": 50, "last_counted": "..."
    },
    {
      "id": "wrapper", "name": "Wrapper", "tier": 3,
      "unit": "sheet", "stock": 800.0,
      "consumption": { "type": "per_order", "qty": 1 },
      "lead_time_days": 3, "safety_days": 2, "last_counted": "..."
    },
    {
      "id": "gas", "name": "Gas canister", "tier": 3,
      "unit": "canister", "stock": 5.0,
      "consumption": { "type": "per_business_day", "qty": 0.4 },
      "lead_time_days": 5, "safety_days": 3, "last_counted": "..."
    }
  ],
  "tasks": [
    {
      "id": "extinguisher", "name": "Fire extinguisher inspection",
      "next_due": "2026-11-01", "cycle": { "months": 6 },
      "lead_time_days": 14, "impact": "Business shutdown"
    }
  ],
  "history": [ { "date": "...", "product_id": "...", "quantity": 0, "recorded_at": "..." } ],
  "restocks": [ { "date": "...", "item_id": "...", "quantity": 0, "recorded_at": "..." } ],
  "business_days": [ "2026-08-30", "2026-08-31" ]
}
```

- The fields an `items` entry carries differ by Tier. Tier 4 entries live in
  `tasks`, not `items`, and are invisible to the consumption engine.
- Constants (the confidence D, clamp ranges, the 14-business-day window for the per_order average,
  and the 30% alert threshold) are defined in code and not stored in state.json.
