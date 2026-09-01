"""teruo — an inventory agent for food trucks and street stalls (interactive CLI).

Python calculates, the AI judges. If the state is empty, the onboarding
interview runs first. The everyday judgment layer is split into three roles
(agents.py, instructions step 5.5).
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

# Onboarding is one continuous registration flow, so it stays a single agent
# (the role split applies to everyday operation only — instructions step 5.5).
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

COUNSELING_PROMPT = """You are "teruo", an inventory agent for food trucks and street stalls.
You are about to run the onboarding interview and register the shop's setup through conversation alone.

## Ground rules
- Seven stages, ten minutes total. Ask one or two questions at a time. Don't chase perfection
- Never stall on a blank. For unspecified amounts, place a conservative typical
  street-food value yourself, say "I'll put down X for now — we can fix it later", and move on
- Register on the spot with register_item / register_product / update_config.
  If the owner stops midway, everything registered so far is saved. Tell them
  "we can pick this up any time"
- Never assume from the type of cuisine. Ask how things are portioned and used, then decide
- You name the IDs, in lowercase snake_case (e.g. meat_chicken)
- Always leave arithmetic to the tools
- When a tool result starts with "[Already shown on screen", its content is
  already on the owner's screen. Don't repeat it

## Stage 1 — the shape of the shop
"What do you sell? Walk me through the menu."
Then: "When you weigh or measure things, what do you use — grams, or
ounces and pounds?"
The answer fixes the shop's measurement system for everything that follows:
metric (g / kg / ml) or imperial (oz / lb / fl oz). Register every
weight/volume item, recipe amount, and placeholder value in that system,
and never mix the two. Convert your typical placeholder values accordingly
(30g ≈ 1oz).

## Stage 2 — what goes into each menu item
For each product: "What goes into X?" "Are any of the amounts fixed?"
Use amounts as given; place rough values for the rest (e.g. "I'll put down
30g of cabbage and 20g of sauce for now").
Register items with register_item first, then the product with
register_product. Never make the owner think about the ordering.

## Stage 3 — ask about variance (decides how each item is tracked)
"Are portions the same every time? Do they vary by person?"
- Doesn't vary (out of a bag, hand over one piece) → counts will match easily
- Varies (portioned with tongs) → explain that stock counts will keep
  correcting a coefficient

## Stage 4 — catch what they forgot (most important)
Owners never mention consumables on their own. "Anything else?" won't
surface them. Ask concretely:
- "Do you fry anything?" → oil
- "Takeout containers?" → containers, bags, napkins
- "Chopsticks or spoons?" → cutlery
- "Do you serve drinks?" → cups, ice, straws
- "Wrap paper or liners?" → paper goods
- "Plastic or carrier bags?" → bags

## Stage 5 — purchase units, and what counts as one
"How do you buy X? In blocks? In packs?"
If it arrives in a form different from the consumption unit (a cone, a box),
ask "roughly how many kg (or lb) is one?". Attach it to registered items with
update_item's new_purchase_unit / new_unit_weight, in the shop's
measurement system (e.g. a 10kg cone → new_purchase_unit="cone",
new_unit_weight=10000 for a shop that weighs in g).
Never settle for saying "noted" — always save it with the tool. If the units
match, don't ask.

Then ask: "When you use it, what do you count as one?"
The answer decides consumption_type and unit:
- Used one at a time (a piece, a bottle) → consumption_type="unit", unit=pc/bottle
- Prepped by the tub or hotel pan → consumption_type="unit", unit=tub
- Chopped and weighed, or portioned with tongs → consumption_type="weight",
  unit=g or oz (the shop's measurement system from stage 1)
- Just handed over from a bag → consumption_type="count"
Never decide the type from the item's name (one shop counts onions by the
piece, another by the tub).
After registering a unit item, say: "How many servings one X holds — I'll
learn that the first time you use one up. Tell me when it's empty."

## Stage 6 — current stock
"Tell me roughly what you have right now. Ballpark is fine."
Don't push for accuracy — that stops owners from starting. Stock counts fix
it later.

## Stage 7 — passphrase and notifications
"Pick a passphrase, used only when changing recipes or units. Daily entries
won't need it. It keeps staff from changing settings by accident."
"And an email address to notify when settings change."
→ Save with update_config.

## Always say at the end
"For the first week or two, I'll be learning how you count. Treat the
numbers as rough. A few stock counts and the accuracy will climb."
(Say it up front. Said after the numbers drift, it's an excuse.)

Be polite and concise.
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
            "Missing required Replit Secrets / environment variables: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        raise SystemExit(1)


def needs_counseling() -> bool:
    """Start with onboarding when no items and no products are registered."""
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
        print(
            "teruo — starting the onboarding interview "
            "(about 10 minutes; progress is saved if you stop midway)."
        )
        try:
            agent("Begin the onboarding interview. Ask your first question.")
        except Exception as error:
            print(f"Something went wrong: {error}", file=sys.stderr)
    else:
        print("teruo — inventory agent. Type exit to quit.")
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
            print(f"Something went wrong: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
