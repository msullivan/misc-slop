# fable-1

Nice, retaliatory, forgiving; against opponents that do not reciprocate it
learns a small model of them and plays the best reply.

## Strategy (round 2 version)

1. **Core: tit-for-tat**, opening with C. No noise in this tournament, so plain
   reciprocity gets 3/round against every nice bot and against itself.
2. **Echo forgiveness.** If the opponent's D answers a D of mine that was played
   while they were cooperating, I play C instead of bouncing it back. Switched
   off when the opponent's decayed count of unprovoked defections exceeds 2.5.
3. **Peace offers.** After 6+ rounds without mutual cooperation I play C twice,
   with the gap doubling (6, 12, 24, ... 100).
4. **Model mode** for non-reciprocators. I keep decayed estimates
   p = P(they C | I played C) and q = P(they C | I played D). When p < 0.7 and
   1 + 4q > 3p + 0.5, TFT is abandoned. Instead I use a table of the
   opponent's P(C) given the last two rounds of joint history (16 states,
   recency-weighted, learned all match), solve the resulting MDP by value
   iteration (discount 0.95) every move and play the best action. Unseen
   states are assumed 10% cooperative, so against always-D/random this is
   simply all-D; a test C at widening intervals supplies exploration. Leaves
   model mode after 10 rounds of mutual cooperation or when the p/q numbers
   say reciprocity works.

## Changes after round 1 (rank 8 of 11, 2.781; leader 2.888)

Everyone except `luna` is essentially cooperative: 3.00 against seven
opponents. The whole spread came from luna, terra and haiku.

- **Probing removed.** Every probe (25% of matches) was punished at once by
  every opponent; nobody is a pushover. Each cost a point and risked more.
- **Model-mode entry now needs p < 0.7.** terra and haiku make short
  unprovoked defection bursts and then do not punish my retaliation. That
  inflated q, the old rule concluded "defecting pays", and I went all-D
  against basically cooperative bots until they hit back (2.87 vs terra, one
  very bad game vs haiku). Now such bots just get plain TFT retaliation.
- **All-D replaced by the learned-model best reply.** luna was all-D except
  that it played C right after a mutual defection that followed a C of mine.
  All-D got me 1.06; cycling C,D,D against that behaviour gets ~2.0 (what the
  bots that did best against luna scored). Rather than hard-coding the cycle
  the planner finds it from the two-round model, so it should carry over if
  luna is revised into something else with exploitable structure.

## Local results (300 rounds, scratch/sim.py)

TFT/TF2T/grim/pavlov/always-C 3.0, always-D 0.97, random ~2.85, self 3.0,
luna-like 1.99, terra-like 2.95.
