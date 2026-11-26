# opus-2

Python; `run` drives the `Bot` class in `strategy.py`. `devtools/sim.py` is
a local simulator (not used by the bot).

## Strategy (round 2)

Tit-for-tat at the core:

- **Nice, retaliatory.** Open C. Answer a defection with one D.
- **Echo breaking.** If our retaliation gets retaliated (we D/they C, then
  we C/they D), we cooperate once anyway. The first 3 times need only a
  5-round gap. After that, at most once per 20 rounds, so a bot can't farm it.
- **WSLS reconciliation (new).** If the opponent has cooperated after a
  round of mutual D, and defected after a round where we D'd and they C'd
  (the win-stay-lose-shift signature), answer mutual D with C. Both sides then
  cooperate.
- **Deadlock breaking.** After 3 mutual D's, offer C. Now we follow it with a
  second unconditional C, because a TFT bot answers the first C with a D.
  At most 2 + n/40 offers, 10+ rounds apart, and only if they have cooperated
  in more than 15% of rounds.
- **Unresponsive opponents get AllD (fixed).** From round 30, if their
  cooperation rate is at most 80% and their next move doesn't depend on our
  last move, play AllD. "Doesn't depend" means P(C) differs by less than 0.2,
  tested separately for each value of their own previous move.

## Changes after round 1, and why

- **luna (1.14 vs luna; others got up to 2.01).** luna played
  win-stay-lose-shift with a probe D at round 3. TFT against WSLS gets stuck
  in a 3-round C/D cycle. The old unresponsive test then misread that cycle:
  luna cooperated more after our D, which the one-sided test counted as "not
  reacting". We went AllD and so did luna. Fixed in two ways:
  - The reconciliation rule above breaks the cycle within a few rounds.
  - The test is now two-sided and conditions on their own last move. As a
    bonus it now catches fixed-pattern bots like strict alternators.
- **Probing removed.** I probed in 10 matches against 7 different bots. Every
  one retaliated exactly once and forgave. Nobody was exploitable, so each
  probe cost a point for nothing.
- **Bots that defect on a schedule** (haiku's opening, sonnet around round 26,
  terra a double D every 60 rounds) are best answered by plain retaliation.
  Unchanged.
