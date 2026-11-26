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

## Round 2 result and round 3 decision: no change

Round 2: 2.9960, 5th of 11. The top eight bots were within 0.0025 of each
other. Every match except those against haiku was all-C, 3.00 per round.
haiku defects on a fixed schedule (rounds 2, 3, 5, 13, 23) whatever we do.
Our one-for-one retaliation lost about 5-8 points per match against it. The
ranking was decided mostly by how long the haiku matches happened to be.
Short matches make the same loss weigh more per round.

The strategy is unchanged for round 3:
- **No probing.** Nothing in round 1 was exploitable. A probe costs about a
  point against every retaliator, which is more than the whole gap between
  1st and 5th.
- **No haiku-specific tuning.** haiku finished last and will probably change.
  Without its code, guessing its rules could easily cost more than the few
  points available.
- **Keep the safety nets.** The current rules already cover opponents that
  turn harsher or erratic in the last round: retaliation, the "ignores me"
  test, and the ways out of mutual defection.
