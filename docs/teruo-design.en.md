# teruo — Design Doc B (System Specification)

> English translation of [teruo-design.md](teruo-design.md). The Japanese original is authoritative.

An inventory management agent for food trucks and street stalls.
This is the whole-system specification that sits above Design Doc A (the Tier 1 implementation).
The demo subject (kebab) and the system specification are described separately.

Last updated: 2026-09-01 (incorporates addenda: three consumption types, coefficient cap, principles 10/12)

## About the Name

**teruo** (lowercase Latin letters; still teruo at the start of a sentence)

The name comes from the English 'tell'.
This system calculates, but it doesn't act. It only tells.
It speaks before opening, stays quiet during service, and reports at closing. All of it is "tell".

It also overlaps with the Japanese given names 照男 / 輝雄 (read teruo), so it can be heard as both "to tell" and "to shine a light on".

- No spelling variants: never use Teruo / TERUO / テルオ
- Same lowercase-Latin naming family as by fifteen's existing products (handraise, DeliSpot, 暗号ちゃん, tabenote)
- Trademark not yet checked. No problem for the hackathon submission, but check J-PlatPat before any transfer or commercialization
- The GitHub repository name teruo is most likely already taken. Use an alternative such as teruo-agent

## 0. What Kind of Shop This System Works For

Don't judge by the type of business. The more of the following two conditions hold, the more value it delivers.

1. **Quantities vary by hand** (shaving, scooping, pouring, plating)
2. **One ingredient spans multiple products** (many-to-many)

| Business | Item count | Variance | Relation to products | Fit |
|---|---|---|---|---|
| Hot dogs | Few | Small | 1-to-1 | Low (just count them) |
| Ice pops | Medium | None | 1-to-1 | Low |
| Scooped ice cream | Many | Large | Nearly 1-to-1 | Medium |
| Kebab | Medium | Large | Many-to-many | **High** |

Even within "ice cream shops", scooped and ice pops behave differently.
We don't build business-type templates. We ask how things are made and decide from that.

## 1. System Principles (11 items)

### Principle 1 — Start with a theoretical value, correct it with measurements

Coefficients and unit_weight share the same structure: put in a rough estimate, run with it, and correct it when a measurement comes in.
It doesn't need to be accurate from the start.

### Principle 2 — What counts as truth (priority order)

```
Measured stock count > Measured purchase > Calculation from estimates
```

When a higher-priority value arrives, it overwrites the lower ones. When in doubt, measure.

### Principle 3 — Python does the math, AI does the judgment

Never let the LLM do numeric calculation.
The AI's only job is judgment: "what should we ask them to count" and "is this abnormal".

### Principle 4 — Separate structure-changing operations from daily input

Premise: the owner isn't the only person who touches this device.
But it isn't "anyone", either. The people entering sales and stock counts are senior staff who've been entrusted with inventory.
New hires don't touch it.

| Level | Who | What they can do |
|---|---|---|
| Owner | The owner | Everything. Structural changes require the passphrase |
| Inventory staff | Senior staff entrusted with it | Entering sales, stock counts, and purchases |
| General | Everyone else | Don't touch it |

Changing units, recipes, or the item structure rewrites the shop's configuration itself,
and must not sit somewhere inventory staff can casually poke at.

| Operation | Who | Before executing | After executing |
|---|---|---|---|
| Enter sales | Inventory staff | — | — |
| Enter a stock count | Inventory staff | — | Notification only on abnormal values |
| Enter a purchase | Inventory staff | — | — |
| Change recipe quantities | Owner only | Passphrase + confirmation | Notification |
| Change a unit | Owner only | Passphrase + confirmation | Notification (with before/after values) |
| Add an item | Owner only | Passphrase + confirmation | Notification |
| Delete a product | Owner only | Passphrase + confirmation | Notification |

#### Why two layers

The passphrase is the lock on the door; the notification is how you find out afterwards.
They play different roles, so both are needed.

The passphrase will leak. The owner gets busy and tells an employee; staff turn over and everyone ends up knowing it.
This happens in real life. The notification is the last line of defense left when it does.

Implementation: during the onboarding interview the owner sets a configuration passphrase,
and it is requested only for structure-changing operations (no account authentication this time).

#### Notification contents

```
[Settings changed]
2026-09-01 14:32

Kebab sandwich recipe
  Kebab meat (chicken) 75g → 90g

If you don't recognize this change, please check.
```

- **Write both the before and after values.** "Changed" alone doesn't tell you what happened
- No feature to block changes. The goal is to make them noticeable
- Reverting is done by the owner by hand (possible because the pre-change value remains in history)

#### Where notifications go

| Channel | This time |
|---|---|
| Email | Adopted (lightweight; just register one owner address) |
| LINE / Slack | Deferred (integration effort doesn't fit the deadline) |
| In-app notification | Deferred (there is no screen) |

In stage 7 of the onboarding interview, the notification address is registered together with the passphrase.

Note: implementation priority is medium. Start after Tier 1 and the registration tools are working.
   If it doesn't make it in time, record to history only instead of notifying,
   and make the "settings change history" viewable from get_stock_status (this is lightweight).

#### Specific handling of unit changes

- Same unit type (g → kg): convert
- Across unit types (g → cone): don't convert. Re-enter via a stock count
- Always keep the previous unit, stock, and timestamp in history
  → so that you can later trace which unit a past number was recorded in
- After the change, reset that item's coefficient to 1.0 and treat it as being in the learning period again
  → when the unit changes, the meaning of the coefficient changes too, so it must not carry over

### Principle 5 — Never delete

- Items are never deleted. Hide them with active: false
- history is never deleted, no matter what
- Deleting a product requires confirmation

### Principle 6 — Classify by how things are made, not by business type

Don't hard-code "it's a kebab shop, so it gets this setup".
One question decides the tier: "Does the amount you serve vary?"

### Principle 7 — Separate data by pitch type

Event booths and solo pitches differ in how easy they are to forecast.

| | Crowd size | Competition | Forecast confidence |
|---|---|---|---|
| Event | Predictable (attendance is known in advance) | Managed by the organizer | High |
| Solo (markets, etc.) | Unpredictable | Unknown whether there even is any | Low |

Both are "pitches", but averaging them together gets both wrong.
Make it a single choice at record time (takes one second). Keep separate averages.

Prep volume is a measure of ambition, and it reflects the size of the venue.
Prepping a lot for an event is normal. Only a solo pitch with heavy prep is a misjudgment.
Never use prep volume as evidence on its own. Always look at it together with the pitch type.

### Principle 8 — Protect only the stock. Stay out of the sales forecast

- Be **conservative** about remaining stock. Predict running out early
- Don't be **conservative** about the sales forecast. Whether it sells is the owner's domain

If someone thinks "today's going to be good" and the stock calculation runs on the same optimism,
nothing is left when it misses. But being pessimistic about sales too is overstepping.

### Principle 9 — Say up front that it's still learning

Both the frequency and the coefficients can be pinned down in 2-3 rounds. But until then, they'll be off.

Saying "it was still learning" after it misses is an excuse.
Saying it beforehand is what earns trust.

```
First time: "For the first week or two, I'm learning how you count.
             Treat the numbers as rough guidance only.
             Once you've done a few stock counts, accuracy will improve."
```

What gets learned includes not just the coefficients but the appropriate stock-count frequency itself.
Don't hard-code "count once a week"; decide based on how many rounds it took that item to stabilize.

#### Put a deadline on "learning"

If it's still saying "learning" after a month, that's the same as not learning.
And "learning" becomes an escape hatch for excuses.
A wrong number can be waved away.

- The deadline is **2 weeks or 5 stock counts, whichever comes first**
- Past the deadline, don't say "learning" even if accuracy hasn't improved
- Instead, report **why it isn't stabilizing**

```
× "Still learning."          ← excuse

○ "The chicken numbers aren't stabilizing.
   Likely either a different person shaves the meat each day,
   or the stock counts happen at inconsistent times."  ← information
```

#### Show progress

"Learning" with no end in sight is just unsettling. Show what's left.

```
"Learning (stock count 2 of 5)"
```

### Principle 10 — Never tie shortages to a person

The theoretical stock can go negative. That's not a bug; it's evidence the coefficient hasn't matured yet.

On the ground, there's a bad practice of making individuals cover shortages out of pocket.
**teruo's numbers must never be usable as the basis for that.**

#### Two reasons, and not just ethics

**1. The numbers have no solid basis.**
It's a pre-calibration theoretical value, so the difference itself has no grounding.
Once the coefficient is correct, that negative disappears retroactively.
**A negative that calibration erases was never a loss in the first place.**

**2. A system that penalizes the person entering data won't get honest data.**
Once people realize the numbers they enter come out of their own pocket, they stop entering them honestly.
They over-report stock counts, under-report sales, skip days.
Then the coefficients learn garbage and teruo becomes useless.
**This is a practical, operational concern.**

#### Implementation

| Recorded | Not recorded |
|---|---|
| Time of input | **Who entered it** |
| Stock count value and the coefficient before and after | **Per-person shortage amounts** |
| Before/after values (principle 4) | |

Timestamps are kept. You can still trace which input on a given day moved the coefficient.
Who it was, the owner can work out by checking the shift schedule.
**teruo just doesn't name names; tracing is still possible.**

If teruo itself kept a per-person shortage ledger, it would get used as an invoice. That's the one thing to avoid.

#### Handling negative values

**Don't clamp to 0** (never write `max(0, stock)`).
A negative is information: "the theoretical value overestimated relative to the actual count."
Clamping to 0 destroys the very material needed to correct the coefficient. That violates principle 5.

**Don't halt with an error.** Sales couldn't be entered during service. teruo must never stop the shop floor.

Keep the negative value internally; change only the display.

| | Internal | Display |
|---|---|---|
| Normal | 8,500 | "8,500g" |
| Negative | **kept as -500** | "Actual count needed" |

Negative stock is physically impossible,
**so the moment you show the number, it reads as "it's broken".**

```
"The theoretical stock for chicken has gone below zero.
 In reality there should still be some left.
 My calculation was estimating too low.

 Could you weigh it once at closing?"
```

No apologizing. The theoretical value is a placeholder value (principle 1), so drift is expected.
**Not "it's broken" but "I don't have enough information."**

### Principle 12 — Reconcile against numbers from outside the device

(Numbering follows the design doc the addendum came from. Principle 11 is intentionally skipped.)

#### Coefficient learning as an attack surface

teruo's core feature is, at the same time, its attack surface.

```
1. Report less than the actual amount at the stock count
2. teruo concludes "it's lower than the theoretical value"
3. The coefficient goes up (75g → 85g)
4. From then on, consuming 10g more per serving is "normal"
5. teruo says nothing. It even reports "it's stabilized"
```

**Once it's been taught, subsequent skimming becomes invisible.**
The structure rewards growing the coefficient little by little over one big move.
The ones who understand it are exactly the ones who don't get caught.

The coefficient cap (chapter 2) is the direct defense against this path.

#### Reconciling against paper goods

One move already present in chapter 2.

> Paper goods and containers are included in recipes. Their coefficients don't move, so they serve as a baseline for whether the meat coefficient is right.

The count type has its coefficient fixed at 1.0. **Paper consumed = servings actually served.**

| Observation | Meaning |
|---|---|
| Meat coefficient went up + paper went up by the same amount | Servings really did increase |
| **Only the meat coefficient went up + paper unchanged** | **Same number of servings, but only the meat is going down** |

However, **if paper is taken out along with the meat, this reconciliation breaks.**
It isn't effective against someone who understands the mechanism.
And inventory staff are senior staff, on the side that understands it.

#### Three numbers that can't be fudged

Stock and paper are both entered by the same person from the same device. They can be made consistent at the same time.
We need numbers that can't be made to fit from inside the device alone.

| Stream | Source | Can be manipulated within the device? |
|---|---|---|
| Stock | Stock count (self-reported) | Yes |
| Paper | Theoretical value via recipe | Yes |
| **Sales revenue** | **Register / cash** | **No** |
| **Purchases** | **Supplier invoices** | **No** |
| **Monthly totals** | **Monthly** | **No** |

Skim meat → report fewer servings → sales revenue drops → cash doesn't match.
Try to make only the cash match, and the stock doesn't match. **One of the two will always be off.**

#### Look at it monthly

A scheme that keeps hiding inside the threshold can't be detected daily, as a matter of principle.

```
2g/serving × 100 servings = 200g/day   ← inside the 4g cap. Never shows up in a single day
× 25 days = 5kg/month                  ← half a cone
```

| Window | What it can detect |
|---|---|
| 1 day | A single large hit |
| **1 month** | **Sustained skimming that stays inside the threshold** |

```
"This month you purchased 30kg of chicken, and theoretical consumption is 25kg.
 Stock is 2kg. 3kg is unaccounted for."
```

A discrepancy that never appears daily. **Purchases leave a copy on the supplier's side, so they can't be settled within the shop.**

#### teruo doesn't suspect. It just doesn't miss

teruo can't separate causes.
Missed records, unrecorded waste, and skimming all show up the same way: "less than the theoretical value."
**Don't assert one when you can't tell them apart.**

It states only the facts and that the range is abnormal.

```
"The chicken discrepancy is beyond what serving variation can explain.

 800g over 100 servings. Plating variance doesn't produce a gap that wide.
 Please check whether any purchases or sales went unrecorded."
```

What to do about it is the owner's domain (principle 8). Same as the principle 4 notification: **the goal is to make it noticeable.**

#### What can't be stopped

**Structural changes by the owner themselves.**
Whoever holds the passphrase can't be stopped. Overstating costs is technically possible,
and the principle 4 notification goes to the owner, so it's meaningless.

But that's also outside teruo's jurisdiction.
The party being deceived isn't teruo or the inventory staff; it's the tax office or a buyer.

**Keep every before/after value in `history`** (principle 5).
teruo doesn't stop it in real time, but it can be read back later.
**It doesn't stop it, but it doesn't erase it.**

Don't pretend it can be prevented. Write down that it can't.

## 2. Data Structures

### Items (items)

```json
{
  "id": "meat_chicken",
  "name": "ケバブ肉（チキン）",
  "tier": 1,
  "unit": "g",
  "unit_type": "weight",
  "consumption_type": "weight",
  "purchase_unit": "本",
  "unit_weight": 10000,
  "stock": 8500,
  "coefficient": 1.0,
  "last_counted": null,
  "count_history": [],
  "active": true
}
```

- unit_type is one of weight / volume / count
  → never hard-code "g" in the code. Keep it in a form where oz can be added later
- consumption_type is one of three types, count / weight / unit (described below).
  It's a separate axis from unit_type (the kind of unit) and represents **how consumption is counted**
- purchase_unit and unit_weight are optional
  → not set for items whose purchase unit and consumption unit are the same (pita bread, napkins)
- unit_weight is an estimate, not a fixed value (principle 1)
- coefficient always starts at 1.0. The owner doesn't get to set it
  (the unit type is the only exception: no initial value; it's established by the first used-up unit)
- count_history is the record of stock counts. Used to decide frequency

### Three Types by Consumption Type (consumption_type)

tier 1/2/3 is the axis of "does variance occur". Separately from that,
**how consumption itself is counted differs by item.** We need one more axis.

Managing sauce in grams doesn't match reality.
Commercial sauce comes in bottles or packs. Nobody weighs what's inside.
If it's house-made, the batch size is the same every time.
**On the floor, the count is "how many servings per bottle", not "20g × N servings".**

| consumption_type | Examples | What the coefficient represents | Coefficient learning |
|---|---|---|---|
| count | Pita, napkins, items on sticks | — | **None. Fixed at 1.0** |
| weight | Meat, rice, cabbage | Actual consumption per serving | From stock-count differences |
| unit | Sauce, oil, seasonings | **How many servings one unit yields** | **Established when a unit is used up** |

Anything you can just count doesn't need a coefficient (same logic as the fit table in chapter 0).

#### Learning for the unit type

You can't measure mid-way. Nobody knows an open bottle is "30% left".
But **the moment you switch to a new one is known for certain.**

```
Bottle 1: opened → empty after 48 servings
Bottle 2: opened → empty after 52 servings
Bottle 3: opened → empty after 50 servings

→ 1 bottle ≈ 50 servings. With 1.5 bottles left, that's 75 more servings
```

Don't deal with fuzzy intermediate values; **learn only from established facts (it became empty).**
More accurate than the weight type, and lighter to implement.

#### "Can't be measured" doesn't mean "can get away with it"

Don't read this as "nobody knows until it's used up, so there's no catching it."

Skimming a little at a time is visible too. For the weight type it wouldn't stay within 3-4g/serving.
The unit type fits the same frame. If a bottle is 50 servings, the range is 48-52.

If `Bottle 4 → empty after 30 servings` shows up, that isn't a property of the sauce.
It was spilled, used for something else, or a record is missing.
**Just being visible is a deterrent.**

#### Additional data structure (unit type)

```json
{
  "id": "sauce_yogurt",
  "name": "ソース（ヨーグルト）",
  "consumption_type": "unit",
  "unit": "本",
  "coefficient": 50.0,
  "sales_count": 1250,
  "opened_at_sales_count": 1250,
  "unit_history": [48, 52, 50]
}
```

- `opened_at_sales_count` — cumulative serving count at the time the unit was opened.
  The difference from the cumulative count when it runs empty is exactly "how many servings this bottle lasted"
- `unit_history` — past results. Used as the baseline for the cap check
- `sales_count` — cumulative number of servings that used this item (an implementation counter)

#### Same vegetable, not necessarily the same type

Cabbage versus onions and tomatoes: all "vegetables", but they behave differently.

What follows is a tendency, not a hard rule.
Some shops count cabbage by the tub; some dice tomatoes, weigh them, and plate them.
**Never write code that infers the type from the item name.**

| | How it's counted | Type |
|---|---|---|
| Cabbage | Shredded and served from a pile. Amount varies | weight |
| Onions, tomatoes | **Servings per piece is fixed** | unit |

Cut one tomato into 8 slices, use 2 per serving, and one tomato is 4 servings.
**It's cut, not plated.** Cutting has little variance.

This is the same structure as sauce. It learns "how many servings per piece".

#### Shops that count by the tub (nakago)

Some operations put prepped food in a hotel pan or container and **use one full pan as the unit.**

```
Onion   1 tub → 60 servings
Tomato  1 tub → 45 servings
```

If you count by how many times you refill, the container becomes the unit.
**The prep unit is the stock unit.** The unit type handles it directly.

Which is right depends on the shop. The same onion
is counted by the piece in one shop and by the tub in another, and **teruo doesn't decide.**
Stage 5 of the onboarding interview decides (chapter 3).

### Coefficient Update Formula (Smoothing)

The measured coefficient obtained from a single stock count is:

```
measured coefficient = current coefficient × (actual consumption ÷ theoretical consumption)
```

But adopting this as-is means **it chases the day-to-day hand variance (roughly ±5%) in full and oscillates**
(confirmed with the convergence simulation tests/simulate_convergence.py; swing up to ±5%).

So we move only halfway toward the measurement:

```
new coefficient = current coefficient + 0.5 × (measured coefficient − current coefficient)
```

- The swing halves (±2.6%), and convergence still takes 3-5 stock counts
  → consistent with principle 9's "learning lasts up to 5 stock counts"
- Why a single measurement isn't adopted in full: what the measurement gets right is "the remaining amount that day",
  not "how hands will move from tomorrow on". Don't learn one day's variance

### Coefficient Cap

There's a physical limit to plating and shaving variance.
**3-4g per serving.** Beyond that, the hand notices.

On a day with 100 servings sold, the theoretical maximum discrepancy is 300-400g.
A gap larger than that doesn't come from plating.

| Type | Cap |
|---|---|
| count | Coefficient doesn't move |
| weight | **Recipe value ±4g/serving** |
| unit | **±20% of past results (unit_history)** |

The unit type has no initial value to anchor to, so a fixed cap can't be set.
Draw the range once three units' worth of results are in. Until then, skip the cap check.

#### Behavior when the cap is reached

**Stop learning.** It never exceeds the cap on its own.

```
"The chicken coefficient has reached the upper limit of what plating can explain.
 I won't adjust it automatically beyond this.

 The recipe itself may need to be reviewed."
```

Changing a recipe requires the passphrase (principle 4).
**This closes the back door where daily input effectively rewrites the recipe via the coefficient.**

#### Show the difference when learning ends

Principle 9 declares "the first two weeks will be off."
That's right for trust, but it also opens a window where anything "can be explained by learning".
It also coincides with when staff turn over.

When learning ends, always display the difference between the initial and final values. Never finalize silently.

```
"Learning is complete.
 Chicken: 75g → 82g (+9%)

 Please take a moment to confirm this range is acceptable."
```

### Products (products)

```json
{
  "id": "kebab_sand",
  "name": "ケバブサンド",
  "price": 600,
  "recipe": [
    { "item_id": "meat_chicken", "qty": 75 },
    { "item_id": "pita", "qty": 1 },
    { "item_id": "cabbage", "qty": 30 },
    { "item_id": "sauce_yogurt", "qty": 1 },
    { "item_id": "wrap_paper", "qty": 1 },
    { "item_id": "napkin", "qty": 1 }
  ]
}
```

Paper goods and containers are included in recipes. Their coefficients don't move, so they serve as a baseline for whether the meat coefficient is right.

For unit-type ingredients, qty is "servings' worth used per serving" (normally 1).
The reality lives in the coefficient (1 unit = N servings), not in an amount (g).

### Sales Records (history)

```json
{
  "recorded_at": "2026-09-01T20:14:00+09:00",
  "venue_type": "event",
  "product_id": "kebab_sand",
  "quantity": 35
}
```

venue_type is a binary choice, event / solo (principle 7).
Make it a single choice at record time. Averages are kept separately by this.

## 3. Onboarding Interview (7 Stages, Under 10 Minutes)

If they stop partway, everything up to that point is saved. Don't force them to fill everything in perfectly.

### Stage 1 — Outline of the shop

```
"What do you sell?"
"Walk me through your menu."
```

Even if the business type comes up, nothing is hard-coded from it internally (principle 6).

### Stage 2 — What goes into each menu item

```
"What goes into a kebab sandwich?"
→ Pita, meat, cabbage, sauce

"Is there anything with a set amount?"
→ Meat 75g

"I'll fill in the rest for now: cabbage 30g, sauce 20g. You can fix these later."
```

**Don't stop on blanks.** The AI fills them in and moves on.
The fill-in values reflect the shop's character (a Japanese street stall means modest portions).

### Stage 3 — Ask about variance (tier decision)

```
"When you plate it, is it the same amount every time? Does it vary by person?"
```

- Doesn't vary (take it out of a bag, hand over one piece) → coefficient fixed at 1.0
- Varies (scoop, shave, pour) → coefficient moves / Tier 2

### Stage 4 — Catch what's been overlooked (★ needs expanding)

Owners only mention ingredients. The agent has to go and ask about specifics.
"Anything else?" won't surface them.

```
"Do you fry anything?" → oil
"What about takeout containers?" → containers, bags, napkins
"Chopsticks or spoons?"
```

Note: this list is the system's single biggest asset. Expand it from field experience.

### Stage 5 — Purchase unit and counting unit

```
"How do you buy meat? Whole cones or packs?"
→ Whole → "Roughly how many kg is one cone?" → goes into unit_weight
```

The purchase unit alone isn't enough. The purchase unit and the counting unit are different.

```
"How do you buy onions?"                       → as before: bags, boxes
"When you use them, what do you count as one?" → new question

  One at a time        → unit = pc
  By the tub / tray    → unit = tub
  Diced and weighed    → weight
```

This one question decides consumption_type and unit at the same time.
Alongside stage 3 (the variance question for the tier decision), it's **the key branching question.**

### Stage 6 — Current stock

```
"Tell me what you have on hand right now. Rough numbers are fine."
```

**Don't demand accuracy.** Demand it and they can't get started. Stock counts will fix it.

### Stage 7 — Set the passphrase and notification address

```
"Please choose a passphrase that's used only when changing recipes or units.
 It isn't needed for daily input.
 It's there to keep staff from accidentally changing the settings."

"Please give me an email address to notify when settings change.
 That way, even if more people learn the passphrase, you'll still notice changes."
```

Used for the permission separation in principle 4. This is the one thing the owner must decide personally.
The email address lives in state.json, not Replit Secrets,
but replace it with a fictional demo address before publishing the repository.

## 4. Stock Count Frequency

The system doesn't set a uniform rule. The owner doesn't set it either. Ask only when needed.
Make them count everything every day and they'll quit in three days.

### Learning period (roughly the first 5 counts)

Ask after every service. Give a reason.

```
"I'm still learning, so could you count again today?"
```

### After stabilizing

Once coefficient movement has settled, drop to once a week.

```
"Sausages have stabilized, so no need to count them until next week."
```

### Ad hoc

- Theoretical and measured values suddenly diverged
- A new person joined
- Stock is about to run out

### Never make them count everything at once

Even with 20 items, ask for only 2-3 on any given day.
Choosing what to count is the agent's job.

## 5. When to Report

**During service, stay quiet as a rule.**

### Why not speak during service

Stock always runs out at the busiest moment. Being told in the middle of it, nobody can respond.
Information you can't act on is nothing but noise.

And the moment the peak passes isn't downtime either.
It's **"reloading" time** for the next rush (skewering meat, cutting vegetables, refilling sauce),
and hands are if anything busier. "Enter it once things calm down" doesn't work.

### Three timings

| When | What to say |
|---|---|
| Before opening | Today's forecast. Advance warning of what's short ← **this is the main event** |
| During service | Quiet as a rule. Only when urgent, just the fact: "10 servings left" |
| At closing | Results, stock count requests, ordering |

Before opening is the only time decisions can be made. Hands are free, and there's still time to buy more.
During service it's too late; at closing, later still.

### What's okay to say during service

Facts only. Don't ask for decisions.

```
○ "Sauce: 10 servings left."
× "Sauce: 10 servings left. Should I order more?"
× "What do you want to do?"
```

Knowing there are 10 servings left, there are things that can be done on the spot
(reduce portions, pull it from the menu, announce it). The decision takes a moment.

### Don't force input timing

Enter it when you can. If you can't, closing is fine.
The system adapts its behavior to the input frequency.

```
If days go by with only closing-time input
→ "Looks like you can't enter during the day. Closing only is fine."
→ switch to building the next day's forecast from closing data
```

Never demand "please enter it each time."

## 6. Making the Learning Phase Explicit

Reliability right after rollout differs from two weeks in. Show that to the owner (principle 9).

```
Week 1: "Learning (stock count 2 of 5). Treat the numbers as rough guidance only."
Week 2: "The chicken coefficient is stabilizing."
Week 3: "Stock is about to run out." ← ordering suggestions start here
```

Implementation just looks at the number of count_history entries and how much the coefficient is moving.

"Learning" is cut off at 2 weeks / 5 stock counts (principle 9).
Past that, don't say "learning"; report why it isn't stabilizing.

## 7. Concurrent Writes

Premise: with two inventory staff, simultaneous input will happen.
If the practice is to enter each order as it's taken, overlap is even more likely.

The current setup is a single JSON file, so the later write overwrites the earlier one and numbers get lost.

### What we do this time (minimum)

Re-read the file right before writing.
If it has changed since we read it, stop instead of overwriting.

```
"It looks like someone else entered data first. Please try again."
```

At least it prevents lost numbers. A few dozen lines to implement.

### What we don't do this time

No full locking mechanism. That's not something to fight for with JSON.
When it moves to a DB (SQLite / PostgreSQL) at the transfer / production stage, leave it to the DB.

## 8. Tool List

### Implemented (Design Doc A)

| Tool | Role |
|---|---|
| record_sales | Record sales, deduct stock |
| record_count | Stock count, coefficient update |
| get_stock_status | Stock list |

### To add (4 registration tools)

| Tool | Role |
|---|---|
| register_item | Add an item (name, unit, stock) |
| register_product | Add a product (name, recipe) |
| update_recipe | Modify recipe quantities |
| delete_product | Delete a product (confirmation required; items are never deleted) |

No item-deletion tool is built (principle 5).

### To add (other)

| Tool | Role |
|---|---|
| update_item | Modify an item's name or unit (confirmation required for unit changes) |
| record_purchase | Record a purchase. Accepts free text |
| record_unit_used | Record a used-up unit for unit-type items. Establishes "1 unit = N servings" |
| get_monthly_reconciliation | Monthly reconciliation. Cross-checks purchases, recipe-based theoretical consumption, and stock-count actuals (principle 12) |

### Permission classes

register_item / register_product / update_recipe / update_item / delete_product
— these five count as structural changes, so they require the passphrase (principle 4).

record_sales / record_count / record_purchase / record_unit_used /
get_stock_status / get_monthly_reconciliation can be used by anyone.

## 9. Input Entry Points

| Method | Implementation effort | Impact | Priority |
|---|---|---|---|
| Paste a note | Light | High | 1 |
| CSV / spreadsheet | Medium | Medium | 2 |
| Menu scan | Light (no screen needed after all) | High | Implemented |
| Delivery slip scan | — | Low | No separate build (same path) |

### Paste a note (record_purchase)

No fixed format. Reads one line or ten.

```
Owner: "Meat A 1 cone, pita 100pc, sauce 3 bottles, napkins 1000pc"
→ parse it and reply with a confirmation: "Is this correct?"
```

Works as-is in the CLI. No screen needed.

### Menu scan

Always confirm after reading. Never register silently.

```
"Here's what I read. Is this correct?"
 Kebab sandwich ¥600
 Kebab wrap ¥600
```

Once implemented, no screen was needed. Typing a file name on the CLI line
hands over a photo or a spreadsheet (`attachments.py`). The model reads it
directly, so no spreadsheet library and no OCR are involved. A delivery slip
goes through the same path, so a separate "delivery slip scan" is moot.

## 10. Demo Setup (Kebab Food Truck)

**This is the demo subject, not the specification.** The numbers can be swapped out.

### Products

| Product | Meat | Main ingredient | Paper goods |
|---|---|---|---|
| Kebab sandwich | Chicken 75g | Pita 1 | Wrap paper 1, napkin 1 |
| Kebab wrap | Chicken 75g | Tortilla 1 | Wrap paper 1, napkin 1 |
| Rice box | Chicken (TBC) | Rice 200g | Container 1, spoon 1, napkin 1 |
| Snack kebab mix | Beef 60g + chicken 60g | — | Container 1, napkin 1 |
| Kebab meat only | (TBC) | — | Container 1 |

### Items

| Item | tier | consumption_type | unit | purchase_unit | unit_weight |
|---|---|---|---|---|---|
| Kebab meat (chicken) | 1 | weight | g | cone | 10000 |
| Kebab meat (beef) | 1 | weight | g | cone | 10000 |
| Pita bread | 1 | count | pc | bag | — |
| Tortilla | 1 | count | pc | bag | — |
| Rice | 1 | weight | g | kg | — |
| Cabbage | 2 | weight | g | — | — |
| **Onions, tomatoes** | 2 | **unit** | **pc or tub** | — | — |
| **Sauce (yogurt / chili)** | 2 | **unit** | **bottle** | — | — |
| Oil | 3 | unit | can | can | — |
| Containers, wrap paper, paper bags, napkins | 3 | count | pc | box | — |

**This table is one example for the demo (kebab, solo pitch), not a default.**
consumption_type isn't determined by the item name. The same item differs from shop to shop
(chapter 2, "Same vegetable, not necessarily the same type").
Stage 5 of the onboarding interview decides (chapter 3).

### How purchasing actually works (researched)

- Whole cones are distributed in 10kg / 15kg / 20kg / 25kg / 30kg. Around ¥850 per kg
- For a food truck, 10-15kg is realistic given the grill size
- Some suppliers sell pre-cooked, pre-cut meat in 1kg vacuum packs (nearly zero variance)

→ The same item is purchased in different forms by different shops.
   That's why purchase_unit / unit_weight must be configurable by the owner.

**The demo uses a 10kg whole cone.** Variance makes the learning behavior visible.

### Rights notes

- Don't put real supplier names in state.json / README / the video. Use the fictional "A商店" (Store A)
- Kebab, pita bread, etc. are generic terms, so no issue

### Undecided (to be confirmed)

- Grams of meat in the rice box
- Grams in "kebab meat only"
- Is running both chicken and beef cones common?
- The range of discrepancy between a whole cone's labeled weight and its actual weight

## 11. Handling Oil (Tier 3)

This used to need a separate design, but the three consumption types (chapter 2) absorbed it into the unit type.

- Topping up is done by the bottle (can)
- The fryer runs one cycle per 18-liter can or per set amount
- Judge by "time since the last change" and "number of fry batches" rather than "amount used"

This logic **is the unit type itself.** It's no longer a special case for oil.
Not included in the demo's initial data (the implementation uses consumption_type: unit).

## 12. Notes (Out of Scope This Time)

- Disposal guidelines for dry goods and seasonings. Seasoning blends degrade faster than single spices
- Unit system conversion (g ↔ oz, L ↔ gal). Can be added later thanks to unit_type
- The idea that "the coefficient resets when a new hire joins"
- The "1 cone = N grams" average can also be learned with the same mechanism as the coefficient

## 13. Implementation Order

1. Swap in kebab and get the Tier 1 coefficient working (half a day)
2. The 4 registration tools (1 day)
3. record_purchase (paste a note)
4. Onboarding interview (1 day; 90% system prompt)
5. Learning phase display (half a day)
6. With what's left: Tier 2, video, README, architecture diagram

3 and 4 need almost no code, so they can go later and still make it.
**Don't start anything else until 1 works.**

### Where the addenda (2026-09-01) fit in

| Implementation | Effort | When |
|---|---|---|
| Three consumption types | Medium | **Include in 1** (core coefficient logic) |
| Coefficient cap | Light | **Include in 1** |
| Keeping and displaying negatives | Light | **Include in 1** |
| Not recording who entered data | Zero | As-is (not implementing it is the implementation) |
| Reconciling against paper | Light | After 1 works |
| Monthly reconciliation | Medium | **After 3 (record_purchase)**, if there's energy left |

Even unimplemented, having it in the design doc has value.
The very fact that we noticed "a single-shot threshold alone won't stop long-term skimming" and built it in
is itself something that gets evaluated. Separate from whether it's implemented.
