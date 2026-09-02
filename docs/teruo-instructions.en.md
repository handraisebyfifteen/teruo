# teruo — Implementation Instructions (for Claude Code, steps 0–6)

> English translation of [teruo-instructions.md](teruo-instructions.md). The Japanese original is authoritative.

## 0. How to use these instructions

### Don't hand over everything at once

Cut out only the section for the current step and give that to Claude Code.
Hand over the full text at once and it will skip verifying the previous step, move on,
and you won't be able to tell where things broke.

Each step begins with "Prerequisites". Don't move on until they are met.

### Don't do anything that isn't written here

Left to their own devices, both Replit Agent and Claude Code will add a web UI and a database.
None of the following will be built, now or later.

- Web UI, HTML, React, Flask / FastAPI
- Databases (including PostgreSQL / SQLite / Firestore)
- Docker
- Authentication or user management (the passphrase is not authentication; see step 4)
- Weather APIs, fetching external data

### Don't rebuild what already exists

Before starting work on each step, first check whether the feature already exists.

- Exists and works as the design doc describes → leave it alone
- Exists but differs from the design doc → fix only the difference. Don't rewrite it wholesale
- Doesn't exist → build it new

Rebuilding something that worked and breaking it is the single most costly mistake in this process.
When in doubt, don't implement — check with chaosprank.

### A diff report at the end of every step

```
■ Differences from the design doc
  Location / what the design doc says / what was actually implemented / why the difference arose

■ Verdict
  Should the implementation be fixed, or the design doc?

■ Proposed fix
```

If implementing reveals that the design was wrong, update the design doc.
The design doc is not a one-way street.

## Overview

| Step | Content | Estimate | Position relative to the deadline |
|---|---|---|---|
| 0 | Take stock of the current state (no implementation) | 30 min | Always first. Don't skip it |
| 1 | Kebab data swap and Tier 1 verification | Half a day | Nothing starts until this passes |
| **1.5** | **Verify coefficient convergence (graph)** | Half a day | **Scores on technical judging. Also usable in the video** |
| 2 | Registration and editing tools (6) | 1 day | Required |
| 3 | Onboarding interview | 1 day | Demo centerpiece |
| 4 | Passphrase and change notifications | Half a day | Simplified version if time runs short |
| 5 | Learning phase and report timing | Half a day | Demo centerpiece |
| **5.5** | **Split the agent by role** | Half a day | Skip if time runs short |
| 6 | Deliverables (README, diagram, video) | 1 day | Required. Don't cut this |

Tier 2 / 3 / 4 are out of scope for this submission. Start on them only if time is left over.

### Priorities with the judging in mind

There are five judging criteria (technical, design, impact, originality, presentation).

- **Originality and impact are already strong** ← field experience, reloading, the 28 g sushi
- **1.5 and 5.5 are what lets us compete on technical merit** ← show not just "it works" but "it's correct"
- **Cut presentation (6) and nothing else lands, however good it is**

Cut in this order: 5.5 → 4 (to the simplified version) → parts of 2. **Never cut 6.**

## Confirming the prerequisites (do this before step 1)

### Step 0-A — Take stock of the current state (no implementation at all; report only)

Do not change any code in this step.
First understand what already exists.
Rebuilding something that is already implemented breaks what was working.

Investigate and report the following.

```
■ Tools already implemented
  Tool name / arguments / does it work / differences from the design doc

■ Current state of data/state.json
  Number and contents of items / number and contents of products / number of history entries
  List of keys each item has (is there a unit_type? is there a count_history?)

■ Current configuration
  Value of AWS_DEFAULT_REGION (in docs, .replit, and README, respectively)
  How dates are generated (by Python, or by the AI)
  How Secrets are read (os.environ, or hard-coded)

■ File layout
  Files referenced by the application itself
  Files not referenced (including leftovers from the Replit template)
  * Just list them. Deletion happens in step 6

■ Runtime check
  Does python main.py start?
  If it does, is there any history of a coefficient having moved (any item whose coefficient is not 1.0)?
```

### Step 0-B — Classifying the differences

Based on the report above, sort each task in these instructions into three categories and present them.

| Category | Meaning | Handling |
|---|---|---|
| Implemented | Works as the design doc describes | Leave alone |
| Partial | Exists but differs from the design doc | Fix only the difference |
| Not implemented | Doesn't exist | Build new |

Get chaosprank's confirmation before starting implementation.
Do not skip this classification and start implementing.

### Step 0-C — Known items needing fixes

Problems identified in the past. Check their status in step 0-A.

- Is AWS_DEFAULT_REGION consistently us-east-2?
  - In all of docs/design.md, .replit, and Replit Secrets
- Is the date in record_sales datetime.now(ZoneInfo("Asia/Tokyo"))?
  - Is the AI being made to generate dates? (a bug that actually happened in the past)
  - Are the dates in data/state.json still stuck at the old wrong values?
- Are there Node.js / TypeScript leftovers from the Replit template?
  - List them. Deletion happens all at once in step 6

### Unverified items

The following have not been confirmed yet. Verify them without fail in step 1's completion criteria.

- Does the three-move coefficient test (stock count → sales → stock count) pass?
  → Was scheduled to run after the date fix, but not completed

## Step 1 — Kebab data swap and Tier 1 verification

**Prerequisites**: everything under "Confirming the prerequisites" above is done.

### 1-1. Name the project teruo

- Change the README.md heading to teruo
- Written in lowercase Latin letters. teruo even at the start of a sentence. Don't use Teruo / TERUO / テルオ
- Add one line in the README about where the name comes from

```
teruo — an inventory management agent for food trucks and street stalls
The name comes from the English 'tell'. It calculates, but it doesn't act. It only tells.
```

- Don't change package or directory names (display name only)

### 1-2. Swap data/state.json to the kebab data

Replace the existing hotdog / sausage / bun with the following.

#### items

| id | name | tier | unit | unit_type | purchase_unit | unit_weight | stock |
|---|---|---|---|---|---|---|---|
| meat_chicken | Kebab meat (chicken) | 1 | g | weight | cone | 10000 | 8500 |
| meat_beef | Kebab meat (beef) | 1 | g | weight | cone | 10000 | 6200 |
| pita | Pita bread | 1 | pc | count | — | — | 200 |
| tortilla | Tortilla | 1 | pc | count | — | — | 150 |
| rice | Rice | 1 | g | weight | — | — | 8000 |
| wrap_paper | Wrap paper | 1 | pc | count | — | — | 500 |
| napkin | Napkin | 1 | pc | count | — | — | 1000 |
| container | Container | 1 | pc | count | — | — | 300 |
| spoon | Spoon | 1 | pc | count | — | — | 300 |

For every item, coefficient is 1.0, last_counted is null,
count_history is [], and active is true.

Items whose purchase_unit and unit_weight are "—" must not have those keys at all.

#### products

| id | name | price | recipe |
|---|---|---|---|
| kebab_sand | Kebab sandwich | 600 | meat_chicken 75g / pita 1 / wrap_paper 1 / napkin 1 |
| kebab_wrap | Kebab wrap | 600 | meat_chicken 75g / tortilla 1 / wrap_paper 1 / napkin 1 |
| rice_box | Rice box | 700 | meat_chicken 110g / rice 200g / container 1 / spoon 1 / napkin 1 |
| kebab_mix | Snack kebab mix | 500 | meat_beef 60g / meat_chicken 60g / container 1 / napkin 1 |
| meat_only | Kebab meat only | 500 | meat_chicken 120g / container 1 |

Note: cabbage, onion, tomato, and sauce are Tier 2 and are not included this time.

### 1-3. Add venue_type to history

```json
{
  "recorded_at": "2026-09-01T20:14:00+09:00",
  "venue_type": "solo",
  "product_id": "kebab_sand",
  "quantity": 35
}
```

- The only allowed values are "event" and "solo"
- Add a venue_type argument to record_sales
- Default to "solo" when omitted (asking every time stalls input)

#### Background (for the implementer)

Event booths have a known attendance in advance, so a forecast is possible.
Solo pitches (farmers' markets, etc.) have an unknown crowd and unknown competition.
Mix them into one average and both come out wrong.
For now, only record it. Separating the averages is step 5.

### 1-4. Prevent numbers from being lost on concurrent writes

With two stock staff, simultaneous input will happen.
Since it's a single JSON file, whoever writes last overwrites the other.

Right before writing state.json, read the file again.
If the contents have changed since you read them, abort instead of overwriting.

```
"It looks like someone else entered data first. Please try again."
```

- Checking by mtime or by hash is fine
- Don't build a full locking mechanism. Preventing lost numbers is enough
- When moving to a DB for production, leave this to the DB

### 1-5. Don't hard-code units

- unit_type is one of weight / volume / count
- Don't hard-code "g" or "pc" in code. Always refer to item["unit"]
- Without this, adding oz or lb later means a full rewrite

### Step 1 completion criteria

```
$ python main.py

> Sold 40 kebab sandwiches today
  → Kebab meat (chicken) 8500 → 5500g
  → Pita bread 200 → 160pc
  → Wrap paper 500 → 460pc, Napkin 1000 → 960pc

> Show me the stock
  → A list of all items is returned

> Weighed the chicken and got 5200g
  → The coefficient updates from 1.0 to about 1.06
  → Stock is overwritten to 5200

> 20 kebab sandwiches and 5 rice boxes today
  → Chicken: (20×75 + 5×110) × 1.06 ≒ 2173g decrease
```

- [ ] python main.py starts
- [ ] The coefficient moves away from 1.0
- [ ] Paper items' coefficients stay at 1.0 and don't move
      (one sheet per serving, so there is nothing to drift. If it moves, the calculation is wrong)
- [ ] Dates are recorded correctly in the 2026-09-01 format (not generated by the AI)
- [ ] venue_type is present in history
- [ ] No Secrets are hard-coded

## Step 1.5 — Verify coefficient convergence

**Prerequisites**: step 1's completion criteria are met.

**Why here**: the calculation layer gets touched in the steps that follow.
Build the verification mechanism first, and you can confirm that changes haven't broken anything.
Do it in the other order and you won't notice when something breaks.

**Where it stands for judging**: "showing it's correct", not just "it works",
counts in the technical implementation evaluation. And it makes a picture you can put in the video.

### 1.5-1. What to verify

teruo's core claim is that it "learns the error of the hand". Show that this is true with real data.

```
1. Decide a "true coefficient" (the state where, on the floor, a quantity different from the recipe is actually used)
2. Mechanically generate 20 business days of sales and stock counts using that coefficient
3. Feed them into teruo (the real record_sales / record_count tools) in order
4. See whether the coefficient moves from 1.0 toward the true value
```

Two scenarios. **Inside** the cap (recipe ±4g per serving) (e.g. 1.04 → should converge) and
**outside** it (e.g. 1.15 → should stop at the cap and emit a warning. Verifies principle 12).

### 1.5-2. Implementation

Put it at `tests/simulate_convergence.py`. **Do not change the main code.**

- Call the existing record_sales / record_count as-is
- Use a state file separate from production (tests/sim_state.json)
- Actual consumption is `theoretical value × true coefficient × noise (about ±5%)`
  — on the floor, it's never exactly the same amount every day
- Output: a CSV of the coefficient per stock count, and a graph (matplotlib / PNG.
  x-axis = number of stock counts, y-axis = coefficient, with a horizontal line at the true coefficient)

### 1.5-3. Checklist

- [ ] The coefficient moves from 1.0 toward the true value
- [ ] It roughly converges in about 5 counts
      → If not, the design doc's "learning lasts up to 5 stock counts" is wrong. Fix it to match the measurement
- [ ] The coefficient doesn't keep oscillating even with noise
      → If it oscillates, add smoothing to the update formula and reflect it in the design doc
- [ ] Paper items (one sheet per serving) keep a coefficient of 1.0
- [ ] Production data/state.json has not been modified

### 1.5-4. If it doesn't converge

**That's a result too.** Report it without hiding it. "Converges in 5" was a design-time assumption, not a verified result.
If it actually takes 7, rewrite the design doc to the measured value. Matching the numbers to the measurement is the correct order.

### Verification results (run on 2026-09-01)

- The raw update formula (adopting the measurement in full) chased day-to-day noise and **oscillated at ±5%**
  → Added smoothing to the update formula (move halfway toward the measurement each time). Already reflected in chapter 2 of the design doc
- After smoothing: converges in 3–5 counts; the average from the 5th count onward differs from the true value by 0.6%, with a swing of ±2.6%
- The over-the-cap scenario stopped at the cap and warned every time (as in principle 12)
- Paper items (count type) stayed at 1.0
- Output: tests/convergence.csv / tests/convergence.png

## Step 2 — Registration and editing tools

**Prerequisites**: all of step 1's completion criteria are met.
Don't move on while the coefficient still doesn't move.

### 2-1. Tools to add (6)

| Tool | Role | Permission |
|---|---|---|
| register_item | Add an item (name, unit, stock) | Owner only |
| register_product | Add a product (name, recipe) | Owner only |
| update_recipe | Change recipe quantities | Owner only |
| update_item | Change an item's name or unit | Owner only |
| delete_product | Delete a product | Owner only |
| record_purchase | Record a purchase | Stock staff |

Don't build an item deletion tool (design doc, principle 5).
Items no longer in use are just set to active: false. Stock and history are linked,
so deleting one breaks the past.

### 2-2. register_item

Only three things are required.

- Name
- Unit (unit and unit_type)
- Current stock

Not asked for

- tier — the agent judges it from the item's nature and sets a provisional value
- coefficient — always starts at 1.0. Don't let the owner decide it

Ask about purchase_unit / unit_weight only when the purchase unit differs from the consumption unit.

```
"How do you buy the meat? Whole, or in packs?"
→ Whole → "Roughly how many kg is one cone?" → unit_weight
→ Packs → set neither purchase_unit nor unit_weight
```

### 2-3. register_product

A product can't be created without its items existing. But don't make the owner think about the order.

```
Owner: "Add a kebab sandwich. One pita and 75g of meat."
→ "Pita bread and kebab meat aren't registered yet. Register them first?"
→ Behind the scenes, register_item twice, then register_product
```

From the owner's point of view, it's one conversation.

Ingredients with no quantity decided are filled in by the AI

```
Owner: "The sandwich is pita, meat, cabbage, and sauce."
→ "I'll put down cabbage 30g and sauce 20g for now. You can change them later."
```

Don't stop on a blank. If it stops, the owner walks away.
Fill in values that reflect the character of the shop (a Japanese street stall means modest portions).

### 2-4. update_item (handling unit changes)

Changing a unit is a special case.

- Within the same kind (g → kg), convert
- Across kinds (g → cone), don't convert. Have them re-enter it with a stock count

```
"Change the meat's unit from g to cone?
 The current stock of 5,200g will need to be recounted.
 How many cones do you have now?"
```

Always do the following on a unit change

- Keep the pre-change unit, stock, and timestamp in history
  → so that later you can trace "which unit the past numbers were recorded in"
- Reset that item's coefficient to 1.0
  → if the unit changes, the meaning of the coefficient changes. It must not be carried over
- Treat it as back in the learning period (don't clear count_history; keep the records)

### 2-5. delete_product

- Confirmation required. Never delete in one go
- Deleting a product doesn't delete its items
- history is never deleted

### 2-6. record_purchase (paste a note)

Don't fix a format. Read it whether it's 1 line or 10.

```
Owner: "Meat A 1 cone, pita 100pc, sauce 3 bottles, napkins 1000pc"
→ Parse it and reply with "Is this right?" to confirm
→ Once approved, add to stock
```

Handling "1 cone = how many g"

- If they can give the measured weight, use it → add that value to stock
- If not, use the unit_weight estimate as a placeholder value
- When a measured stock count arrives, it always wins (design doc, principle 2)

```
Owner: "One cone of meat came in. It was 3,850g."
→ Add 3850 to stock
→ Record it as an actual unit_weight (update the average)

Owner: "One cone of meat came in."
→ Placeholder value of 10000 from the estimate
→ "If you find out the actual weight, let me know. It can also be corrected at a stock count."
```

### 2-7. CSV / spreadsheet import

If there's spare time. Low priority. Pasting a note covers it.

Don't implement delivery-note scanning. Pasting a note is enough.

### Step 2 completion criteria

```
> I want to add an item. Yogurt sauce, g, I have 3000g
  → register_item works. coefficient is 1.0

> Add 20g of sauce to the kebab sandwich
  → update_recipe works

> I want to change the sauce's unit to bottles
  → A confirmation appears. The pre-change values remain in history. The coefficient resets to 1.0

> One cone of meat came in. It was 3850g
  → Added to stock. The actual unit_weight is recorded

> Delete Kebab meat only
  → A confirmation appears. After approval, only the product is gone. The items remain
```

- [ ] All 6 tools work
- [ ] No item deletion tool exists
- [ ] A unit change resets the coefficient to 1.0
- [ ] The unit change history is retained
- [ ] history has never been deleted

## Step 3 — Onboarding interview

**Prerequisites**: step 2's completion criteria are met.

This step needs almost no code. 90% of it is the system prompt.

### 3-1. Design principles

#### Don't decide by business type

Don't do "it's a kebab shop, so this is the setup". Ask how things are made and judge from that.

Even two "ice cream shops" are completely different if one scoops (error) and the other sells
ice cream bars (zero error). Don't build business-type templates.

#### Don't force a complete fill-in

- All 7 stages in under 10 minutes
- If they quit partway, everything up to that point is saved
- More can be added later with register_item

### 3-2. Stage 1 — The shape of the shop

```
"What do you sell?"
"Walk me through your menu."
```

Even if you ask the business type, don't hard-wire anything on it internally.

### 3-3. Stage 2 — What goes into each menu item

```
"What goes into a kebab sandwich?"
→ Pita, meat, cabbage, sauce

"Are there any with a fixed amount?"
→ Meat 75g

"I'll fill in the rest for now. Cabbage 30g, sauce 20g. You can change them later."
```

Don't stop on a blank. The AI fills it in and moves on.

### 3-4. Stage 3 — Ask about error (tier decision)

This one question decides the tier.

```
"When you plate it up, is it the same amount every time? Or does it vary by person?"
```

| Answer | Decision |
|---|---|
| Doesn't vary (taken out of a bag, one piece handed over) | Tier 1, coefficient fixed at 1.0 |
| Varies (scooped, shaved, poured) | Tier 1 but the coefficient moves / Tier 2 |

### 3-5. Stage 4 — Catch what's been overlooked (★ this list is the system's single biggest asset)

Owners only mention ingredients. "Anything else?" will never surface these.
The agent has to go and ask concretely.

```
"Do you deep-fry anything?"          → Oil
"What about takeout containers?"     → Containers, bags, napkins
"Chopsticks or spoons?"              → Cutlery
"Do you serve drinks?"               → Cups, lids, straws
"Wrap paper or liner paper?"         → Paper goods
"Plastic bags?"                      → Carrier bags
```

★ This section needs expanding. Grow the list from field experience.
This is where the difference from other implementations lies. Write it from imagination and things will be missed, guaranteed.

### 3-6. Stage 5 — Purchase units

```
"How do you buy the meat? Whole, or in packs?"
→ Whole → "Roughly how many kg is one cone?" → goes into unit_weight
```

#### Reference: how kebab meat is actually distributed (researched)

- Whole cones are sold at 10kg / 15kg / 20kg / 25kg / 30kg. Around 850 yen per kg
- For a food truck, 10–15kg is realistic given the grill size
- Some wholesalers supply cooked and cut meat in 1kg vacuum packs (almost zero error)

→ The same item is purchased in different forms at different shops.
   That's why purchase_unit / unit_weight must be configurable by the owner.

### 3-7. Stage 6 — Current stock

```
"Tell me what you have on hand now. Rough numbers are fine."
```

Don't demand accuracy. Demand it and they can't get started. A stock count will correct it.

### 3-8. Stage 7 — Passphrase and notification address

```
"Please choose a passphrase to use only when changing recipes or units.
 It isn't needed for day-to-day input.
 It's to stop staff from accidentally changing the settings."

"Please give me an email address to notify when settings change.
 That way, even if more people learn the passphrase, you'll still notice changes."
```

The email address is kept in state.json.
Replace it with a fictitious demo address before publishing the repository.

### 3-9. What to always say at the end (design doc, principle 9)

```
"For the first week or two, I'm learning how you count.
 Treat the numbers as rough guides.
 Once you've done a few stock counts, the accuracy will improve."
```

Saying it up front is what earns trust. Saying it after being wrong is an excuse.

### Step 3 completion criteria

- [ ] All 7 stages run through to the end
- [ ] No logic exists that branches on business type
- [ ] The AI fills in ingredients with unspecified quantities and moves on
- [ ] In stage 4, items the owner didn't mention get picked up
- [ ] If interrupted partway, everything up to that point is saved
- [ ] The "learning" explanation appears at the end

## Step 4 — Passphrase and change notifications

**Prerequisites**: step 3's completion criteria are met.

If time runs short, switch to the simplified version (4-4).
Prioritize steps 5 and 6.

### 4-1. Three permission levels

| Level | Who | What they can do |
|---|---|---|
| Owner | The owner | Everything. Structural changes require the passphrase |
| Stock staff | Senior staff entrusted with it | Enter sales, stock counts, and purchases |
| General | Everyone else | Nothing |

Not "anyone". Someone who just started doesn't enter stock.

### 4-2. Handling per operation

| Operation | Who | Before running | After running |
|---|---|---|---|
| Enter sales | Stock staff | — | — |
| Enter a stock count | Stock staff | — | Notify only on an abnormal value |
| Enter a purchase | Stock staff | — | — |
| Change recipe quantities | Owner only | Passphrase + confirmation | Notify |
| Change a unit | Owner only | Passphrase + confirmation | Notify (with before/after values) |
| Add an item | Owner only | Passphrase + confirmation | Notify |
| Delete a product | Owner only | Passphrase + confirmation | Notify |

#### Why two layers

The passphrase is the lock on the door; the notification is how you find out afterward.
They serve different roles, so both are needed.

The passphrase will leak, without fail. The owner is busy and tells an employee; staff turn over and everyone knows it —
this genuinely happens. The notification is the last line of defense that remains when it does.

The passphrase is not authentication. All it prevents is "oops".
Proper permission management gets added in production.

### 4-3. Notification content

```
[Settings changed]
2026-09-01 14:32

Kebab sandwich recipe
  Kebab meat (chicken) 75g → 90g

If you don't recognize this change, please check.
```

- Write both the before and the after. "Settings changed" alone doesn't tell you what happened
- Don't build a feature to block changes. Let them through, then notify.
  Blocking stalls the floor while waiting for the owner's reply
- Reverting is done by hand by the owner (possible because the pre-change values remain in history)

Delivery is by email. LINE / Slack are skipped because the integration effort doesn't fit the deadline.

### 4-4. Simplified version if time runs short

Sending email requires SES setup, which adds AWS-side work.
If it threatens the deadline, replace notifications with a history view only.

- Make the "settings change history" viewable from get_stock_status

This achieves 80% of the goal — "you can find out afterward that someone changed a setting".
Implementation: 30 minutes.

### Step 4 completion criteria

- [ ] The 5 structural-change tools ask for the passphrase
- [ ] The 4 day-to-day input tools don't ask for the passphrase
- [ ] Both before and after values are recorded
- [ ] Notifications (or the simplified version) work
- [ ] The passphrase is not hard-coded

## Step 5 — Learning phase and report timing

**Prerequisites**: step 4 (simplified version acceptable) is finished.

This is the demo's centerpiece. The implementation is light, but the effect is large.

### 5-1. Showing the learning phase

Confidence right after onboarding and two weeks later are different. Show that to the owner.

```
Week 1: "Learning (stock count 2 of 5). Treat the numbers as rough guides."
Week 2: "The chicken coefficient is settling down."
Week 3: "Stock is about to run out." ← ordering suggestions start here
```

The implementation just looks at the number of count_history entries and the coefficient's range of variation.

#### Put a deadline on "learning"

If it's still saying "learning" after a month, that's the same as not learning.
And "learning" becomes an escape hatch for excuses. Wrong numbers can be waved away.

- The deadline is 2 weeks or 5 stock counts, whichever comes first
- Past the deadline, don't say "learning" even if accuracy hasn't improved
- Instead, report why it isn't settling

```
× "Still learning."          ← excuse

○ "The chicken numbers aren't settling.
   Likely either the person shaving the meat differs by day,
   or the stock counts are done at inconsistent times."  ← information
```

#### Always show progress

Learning with no end in sight is just unsettling. Show what's left.

```
"Learning (stock count 2 of 5)."
```

### 5-2. Report timing

During service, stay silent as a rule.

#### Why not speak during service

Stock runs out at the busiest moment, always. Told in the middle of it, nobody can respond.
Information that can't be acted on is nothing but a nuisance.

And the moment the peak subsides isn't free time either.
It's **"reloading" time** for the next rush (skewering meat, cutting vegetables, filling sauce) —
hands are, if anything, even busier. "Enter it once things calm down" doesn't hold.

#### Three timings

| When | What to say |
|---|---|
| Before opening | Today's forecast. Advance warning of what will run short ← this is the main event |
| During service | Silent as a rule. Only when critical, the bare fact: "10 servings left" |
| At closing | Results, stock count request, ordering |

Before opening is the only time a decision can be made. Hands are free and there's still time to buy more.
During service is too late; closing is later still.

#### What may be said during service

Facts only. Don't ask for a decision.

```
○ "Sauce: 10 servings left."
× "Sauce: 10 servings left. Should I order more?"
× "What would you like to do?"
```

Knowing there are 10 servings left, there are things that can be done on the spot
(reduce the portion, pull it from the menu, put up a notice). The decision takes an instant.

### 5-3. Don't enforce input frequency

Enter it when you can. If you can't, closing is fine.
The system adapts its behavior to the input frequency.

```
If days with only closing input keep coming
→ "Looks like you can't enter data during the day. Closing only is fine."
→ Switch to building tomorrow's forecast from closing data
```

Don't demand "enter it each time".

### 5-4. Stock count frequency

The system doesn't set a uniform rule. Nor does the owner decide. Ask only when needed.
Make them count everything every day and they'll quit in three days.

| Period | Frequency | How to say it |
|---|---|---|
| Learning period (first 5 or so) | Every time after service | "I'm still learning, so could you count again today?" |
| After settling | Weekly | "Chicken has settled, so no need to count until next week." |
| Ad hoc | As needed | Large discrepancy / new person joined / about to run out |

#### Don't make them count everything at once

Even with 20 items, ask for only 2–3 on any given day.
Choosing what to count is the agent's job.

### 5-5. Separate averages by venue_type

Now use the venue_type recorded in step 1.

- Keep separate averages for event and solo
- Mix them into one average and both come out wrong

#### Handling prep quantities (important)

Prep quantity is a "quantity of ambition" — it reflects the size of the venue.

- Prepping a lot for an event is normal
- Only a solo pitch day with a lot of prep is a misjudgment

Don't use prep quantity as a signal on its own. Always look at it together with the venue type.

### 5-6. Protect only the stock (design doc, principle 8)

- Be conservative about remaining stock. Predict run-outs early
- Don't be conservative about the sales forecast. Whether it sells is the owner's domain

For someone who thinks "today's going to be good", if the stock calculation runs on the same optimism,
nothing is left when it goes wrong. But being pessimistic about sales too oversteps.

### Step 5 completion criteria

- [ ] The stock count number is shown in the form "2 of 5"
- [ ] After 5 counts (or 2 weeks), it stops saying "learning"
- [ ] When not settling, candidate causes are listed
- [ ] It never asks "what would you like to do?" during service
- [ ] Stock counts requested at one time are limited to 2–3 items
- [ ] Averages are separated for event / solo

## Step 5.5 — Split the agent by role

**Prerequisites**: step 5's completion criteria are met,
and the step 1.5 convergence graph can be produced.

**After splitting, always re-run the step 1.5 simulation
and confirm the coefficient converges to the same result.** It's the only guarantee that nothing broke.

### 5.5-1. Why split

To be honest: there's little technical necessity. A single agent can behave the same way.

But the Strands Agents SDK has multi-agent coordination as a headline feature,
and with a single agent plus tools, the point of using the SDK is hard to convey.
On top of that, **the split lines up with the design**. Rather than forcing something in,
it just turns the three judgments already in the design doc into three agents.

### 5.5-2. The three roles

| Agent | Job | Design doc counterpart |
|---|---|---|
| **Record keeper** | Receives sales, stock counts, and purchases, and calculates with the Python tools | Principle 3, "calculation is Python" |
| **Observer** | Finds anomalies. Chooses which items to ask for a count today | Chapter 4, "don't make them count everything at once" |
| **Reporter** | Decides when to say what. Silent during service | Chapter 5, "report timing" |

- The record keeper makes no judgments. Even odd numbers are recorded as-is (anomaly detection is the observer's job)
- The observer looks at the coefficient's range of variation to judge settled/unsettled, and narrows today's stock count request to 2–3 items
- The reporter keeps to the three timings — before opening / during service / at closing — and during service gives only facts, only when critical

### 5.5-3. Implementation approach

- **Do not change anything at all** in the Python tools (calculation layer), the state.json structure, or the coefficient update formula
- Split only the judgment layer that sits on top into three
- Follow the Strands Agents SDK's conventions for agent-to-agent coordination
  → **Check the SDK documentation before implementing.** Don't build your own inter-process communication

### Completion criteria

- [ ] Split into three agents
- [ ] The step 1.5 simulation is re-run and converges to the same coefficient as before the split
- [ ] The calculation layer (Python tools) is unchanged
- [ ] The behavior of never asking "what would you like to do?" during service is preserved
- [ ] The architecture diagram reflects the three agents

### If time runs short

**This step may be skipped.** The single-agent version can still be submitted.
If skipping, add one line to the README — "single-agent architecture; splitting by role is future work" —
to convey that **the design was considered and deliberately not chosen**.

## Step 6 — Deliverables

**Prerequisites**: everything through step 5 is finished.
Even if time is short, don't cut this. One fifth of the judging criteria is "presentation".

### 6-1. Repository cleanup

```
1. Delete the Node.js / TypeScript leftovers from the Replit template
   (use the list produced in "Confirming the prerequisites")
2. Delete files not referenced by the application itself
3. Check .gitignore so that real data from data/state.json isn't included
```

#### Required checks before publishing

- [ ] No Secrets have leaked into the code or commit history
- [ ] The email address in state.json has been replaced with a fictitious one
- [ ] The passphrase is not hard-coded
- [ ] No real supplier names appear anywhere (code, README, comments, video)

### 6-2. License

- MIT or Apache 2.0 (hackathon requirement)
- The Strands Agents SDK is Apache 2.0, so there's no conflict
- Put a LICENSE file at the repository root

### 6-3. README

```markdown
# teruo

An inventory management agent for food trucks and street stalls.
The name comes from the English 'tell'. It calculates, but it doesn't act. It only tells.

## What it does
(3 lines or fewer)

## Why it was built
(Field experience. This is what counts in judging)

## How to run it
(AWS setup, Secrets, python main.py)

## Design philosophy
(Link to the design doc. Quote just 3 principles)

## License
```

Write "Why it was built" at length. The "impact" and "originality" criteria are where
the gap between something built by someone with experience and something built from imagination shows most.

### 6-4. Architecture diagram

A required deliverable. Put the following on one page.

```
Owner / stock staff
  ↓ (conversation)
Strands Agent (Bedrock / Claude Sonnet, us-east-2)
  ↓ (tool calls)
Python tools ─── all calculation happens here. The AI never does mental arithmetic
  ↓
data/state.json
```

Draw it so that the separation "calculation is Python, judgment is AI" is visible in the diagram.
This is the core of the technical claim.

### 6-5. Demo video (5 minutes max)

Proposed structure.

| Time | Content |
|---|---|
| 0:00-0:30 | The problem. Why food-truck stock can't be predicted |
| 0:30-1:30 | Onboarding interview. Set up the shop just by talking |
| 1:30-3:00 | Enter sales → stock decreases → stock count → the coefficient learns |
| 3:00-4:00 | Showing the learning phase. "Learning (2 of 5)" |
| 4:00-5:00 | Design philosophy. Silent during service, speaks before opening |

#### What to talk about (where the difference is made)

- The 28 g sushi — after 20 pieces the body remembers. At first it's anywhere from 20 to 30 g.
  The amount shaved off a kebab is the same. A machine learns it
- Reloading time — even when the peak subsides, hands aren't free. That's why it stays silent during service
- Learning has a deadline — so it can't become an excuse

#### What must not be said in the video

- Real supplier names
- Real shop names (safer not to mention 宮地亭 / ごちそうや by fifteen either)
- "It works for any shop" (stating the conditions under which it works earns more trust)

### 6-6. Devpost submission

- [ ] Public repository (MIT / Apache)
- [ ] Architecture diagram
- [ ] Demo video (5 minutes max)
- [ ] AWS Builder ID
- [ ] Use of the Strands Agents SDK is stated explicitly
- [ ] Category: Professional agent

Deadline: September 14, 2026

## Appendix A — What we won't do (final check)

| Item | Reason |
|---|---|
| Web UI | The CLI is self-contained. Time would evaporate |
| Database | One JSON file is enough. Consider it when moving to production |
| Authentication / user management | The passphrase prevents "oops" |
| Tier 2 / 3 / 4 | Out of scope this time |
| Weather API | Not worth the complexity |
| Delivery-note scanning | Pasting a note covers it |
| Automatic order execution | Handing the decision back to a person is the core of the design |
| Oil management | Different in nature from other items. Design separately |

## Appendix B — Undecided items

Demo numbers that need a field-sense sanity check.

- Is 110g of meat in the rice box reasonable?
- Is 120g for Kebab meat only reasonable?
- Is a chicken-and-beef two-cone setup common?
- The range of error between the stated and actual weight of a whole cone

All of these are numbers in state.json and can be changed later.
They're no reason to delay starting step 1.

## Appendix C — Future work (out of scope this time)

- Disposal guidelines for dry goods and seasonings. Seasoning blends degrade faster than single spices
- Unit system conversion (g ↔ oz, L ↔ gal). Can be added later since unit_type exists
- The idea that "when a new person joins, the coefficient resets"
- Learn the "1 cone = how many g" average with the same mechanism as the coefficient
- Oil management (judge by time since replacement and number of fry cycles)
