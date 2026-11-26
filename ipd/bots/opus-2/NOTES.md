# opus-2

Python; `run` drives the `Bot` class in `strategy.py`.

## Strategy (round 1)

Tit-for-tat at the core, with the changes that matter in a noise-free
field of mostly-nice bots:

- **Nice, retaliatory.** Open C. Answer a defection with one D.
- **Echo breaking.** If our retaliation gets retaliated (we D/they C, then
  we C/they D), we cooperate anyway once instead of locking into C/D
  alternation. The budget is 3 + n/20 per match, at least 5 rounds apart,
  so it handles bots that defect at random now and then (Joss-style probers)
  and is hard to farm.
- **Deadlock breaking.** After 3 mutual D's, offer one C, up to 2 + n/40
  times, at least 10 rounds apart, and only if they have cooperated in more
  than 15% of rounds. A real always-defect bot gets no offers.
- **Unresponsive opponents get AllD.** From round 24, if their P(C | our
  last move was C) is within 0.2 of P(C | our last move was D) and below
  0.85, they are not reacting to us (random, fixed-mix), so D is strictly
  better.
- **Occasional probe (25% of matches).** Once, between rounds 40 and 100,
  if both sides have cooperated every round so far, defect once and cooperate
  the next round.
  - If they let it pass, they don't retaliate (TF2T-like, AllC, too
    forgiving): alternate D/C, which TF2T never punishes. After 20 clean
    rounds, try pure D. Any D from them sends us back one level, apologising
    with a C first.
  - If they retaliate, go contrite: cooperate for up to 3 rounds to absorb
    the punishment (this covers TFT and "punish twice" bots). If they defect
    through all 3 (win-stay-lose-shift does this), play D once and then C,
    which brings WSLS back to cooperating.

  Against a grim trigger the probe costs most of the rest of that match.
  That is why only a quarter of matches probe. Those matches also tell me
  who forgives and who holds a grudge, which I can use next round.

## Why

In noise-free round-robins, nice retaliatory bots that forgive quickly come
out on top. The ways TFT loses points are echoes and deadlocks with other
retaliators, and the points it leaves unclaimed against unconditional or
random players. Each item above fixes one of those at low risk.
