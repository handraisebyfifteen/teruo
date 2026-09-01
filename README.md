# teruo

An inventory agent for food trucks and street stalls.
The name comes from the English "tell". It doesn't calculate for show, it doesn't act — it only tells.

An interactive CLI that reduces stock from sales via recipes, and keeps
learning and correcting consumption coefficients from real measurements —
stock counts and emptied units.

*日本語版は [README.ja.md](README.ja.md) にあります。*

## Why it exists

Food-truck inventory never shrinks the way the books say. Meat portioned
with tongs varies by hand — the recipe's 75g becomes 80g or 90g in practice.
So teruo never trusts the theoretical number; it learns a consumption
coefficient from physical counts and keeps correcting it.

The other reason is timing. An alert in the middle of the lunch rush cannot
be acted on — information you can't act on is just noise. The only time
decisions can be made is before opening, so during service teruo states
short facts only and never asks for a decision. Fitting the way time works
on a food truck is the center of the design.

Saying "still learning" forever is also banned. Learning is cut off after
5 stock counts or 2 weeks; if the coefficient still hasn't settled, teruo
reports candidate causes instead of excuses.

## Every item counts differently

Managing all stock in grams doesn't match the counter. Sauce arrives as one
commercial bottle and nobody ever weighed its contents. An onion has a fixed
"servings per piece". The real-world unit isn't "20g × N servings" —
**it's "how many servings does one bottle last?"**

So consumption counting splits three ways, and the coefficient logic
branches with it.

| consumption_type | Examples | What the coefficient means | How it's learned |
|---|---|---|---|
| `count` | pita bread, napkins | — | it isn't (fixed at 1.0) |
| `weight` | meat, rice | real consumption per serving | from stock-count differences |
| `unit` | sauce, oil, onions | servings per unit | settled the moment a unit is emptied |

Unit-tracked items never measure partial contents — nobody knows whether an
open bottle is "30% left". But the moment it goes empty is certain, so
**teruo learns from confirmed facts only.** More accurate than weighing, and
lighter to implement.

The type is never guessed from the item's name. The same onion is used by
the piece in one shop and by the hotel-pan tub in another. Which one it is
comes from the onboarding question: "When you use it, what do you count
as one?"

The measurement system is also decided at onboarding — grams or ounces
(g/kg/ml or oz/lb/fl oz). Everything after that stays in the shop's own
system, and same-kind unit conversions (g→kg, oz→g, ...) are automatic.

## When the numbers don't add up

Coefficient learning is itself an attack surface. Under-report a stock count
and the coefficient rises — from then on that much consumption looks
"normal" and disappears. So corrections beyond the physical limit of
portioning variance (±4g per serving — about 0.14oz; the cap is defined in
grams and converted to whichever measurement system the shop chose at
onboarding, metric or imperial) are refused. At the cap, learning
stops and teruo says the recipe itself may need a review.

When the book value dips below zero, it is neither clamped to 0 nor treated
as an error. A negative number is information — "the estimate ran ahead of
reality" — and rounding it away destroys the very material that corrects the
coefficient. What would actually hurt is being unable to enter sales
mid-service. The number is never displayed; teruo only says a recount is
needed.

And **who entered a number is never recorded.** The moment an entry can be
held against you, people stop entering honestly, the coefficient learns
nonsense, and teruo stops working. It's an ethical stance and a functional
requirement at the same time.

Gaps that stay inside the daily threshold still show up when accumulated
over a month (2g/serving × 100 servings × 25 days = 5kg).
`get_monthly_reconciliation` cross-checks purchases, recipe-basis
consumption, and physical counts. But teruo cannot tell causes apart —
missed records, waste, and shrinkage all surface as the same "less than the
books say". So it never points at a culprit; it states the facts and the
out-of-band gap, nothing more.

## Required environment variables

Register these as Replit Secrets. Never put the values in code or a `.env`.

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION` (`us-east-2`)

## Running

```bash
python main.py
```

- With no items and no products registered (an empty `data/state.json`),
  the onboarding interview starts
- `python main.py --setup` forces the onboarding interview to run again
- Type `exit` or `quit` to leave

## Files

- `main.py`: the interactive loop (operations mode / onboarding mode)
- `agents.py`: the judgment layer's three agents (reporter, record keeper, observer)
- `tools.py`: the calculation tools (recording, registration, queries)
- `store.py`: reads/writes `data/state.json` (atomic writes, concurrent-write detection)
- `data/state.json`: stock, recipes, history, settings
- `tests/simulate_convergence.py`: the coefficient convergence simulation

## Architecture

![teruo architecture](docs/architecture.svg)

All calculation (stock reduction, coefficient learning) happens in Python
tools; the AI handles judgment only. The judgment layer follows the design
doc's three judgments, split into three agents (Strands' agents-as-tools
pattern):

- **Reporter (front desk)**: decides when to say what. Stays quiet during
  service. Structure changes (passphrase) go through it directly with the owner
- **Record keeper**: takes sales, stock counts, and purchases and records
  them via Python tools. Makes no judgments
- **Observer**: spots anomalies and narrows today's stock-count request to
  2-3 items

## Does the coefficient actually converge?

The core claim — "it learns the hand's error" — is verified with machine-
generated data over 20 business days against a known true coefficient
(`python tests/simulate_convergence.py`).

![coefficient convergence chart](tests/convergence.png)

- With portioning drift inside the cap (recipe ±4g/serving), the
  coefficient converges to the true value within 3-5 stock counts
  (the mean from count 5 on is 0.6% off the true value)
- Drift beyond the cap stops at the cap and becomes a recipe-review warning
  (principle 12)
- One-sheet-per-serving paper goods (`count` type) never move from 1.0
- Adopting a single count in full chased daily variance (±5%) and
  oscillated, so the update rule moves halfway toward the measured value
  (found in verification, folded back into the design doc)

## Design principles

The authoritative source is `docs/teruo-design.md` (design doc B).

- Python calculates, AI judges. Never let the model do mental math
- Book values are placeholders; real measurements (stock counts, emptied
  units) correct them
- The coefficient has a physical cap — closing the loophole where daily
  entries quietly rewrite the recipe
- Structure changes (recipes, units, item registry) require a passphrase and
  log before/after values
- Nothing is deleted. Items are hidden with `active: false`; history is
  append-only

## License

MIT License (see `LICENSE`).
Uses the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) (Apache 2.0).
