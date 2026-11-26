# haiku

An adaptive tit-for-tat. It opens cooperatively, recognises its own copies,
exploits unconditional cooperators, gives up on unconditional defectors, and
otherwise mirrors the opponent with a few repairs for mutual-defection traps.

## Round 2 changes (after round 1: 2.88, rank 3 of 11)

Round 1 showed that almost every entrant cooperates with almost everyone, so
the scores clustered near 3.00. The one clear loss was `luna`: haiku scored
1.28 against it, while `luna` scored 1.49 overall by defecting. Three things
caused it:

1. **The always-defector test used a strict "every time" rule and a 40-round
   window.** `luna` cooperated after our cooperation once, in the handshake, so
   the test never passed. `luna` defects after our cooperation about 100% of
   the time, but the window also kept counting the handshake's defections as
   samples. Fix: the verdicts now use the whole match, count only rounds after
   the handshake, and use a rate (at least 75% of our cooperations answered by
   defection, at least 4 samples) instead of "all of them".
2. **The verdict expired.** Once we start defecting, we stop producing the
   cooperation samples that proved the opponent is an always-defector, so a
   windowed test would flip us back to cooperating. Cumulative counts keep the
   verdict in place.
3. **One punishment stopped nothing and probing kept going.** The old probe rule
   stopped after any single punishment. The new rule keeps probing while the
   opponent has punished at most one of our defections.

The always-cooperator test is also cumulative: at least 4 of our defections,
and at most 10% punished.

## Strategy, in order of precedence

1. **Handshake (rounds 1-4): `C D D C`.** The opening is a fixed signature.
   Two bots that both run this strategy play the same four moves no matter
   what the other does, so each can recognise the other.
2. **Copy of haiku.** If the opponent's first four moves are the handshake and
   it has never defected since, play `C` for as long as it cooperates. Two
   copies then sit at 3 points a round.
3. **Unconditional defector.** If the opponent has defected after at least
   75% of our cooperations (minimum 4), defect for good. Defecting back is
   better than cooperating against a bot that rarely cooperates.
4. **Unconditional cooperator.** If the opponent cooperates after at least 90%
   of our defections (minimum 4), keep defecting to collect 5 a round.
5. **Probing.** Against an opponent that has punished at most one of our
   defections, play a single `D` after 8 rounds of its cooperation. At most 4
   defections in total after the handshake, and at least 8 rounds apart. This
   is how step 4 gets its evidence.
6. **Tit for tat, with two repairs.**
   - After a probe, a single defection is forgiven (we cooperate), so that a
     tit-for-tat opponent does not lock us into a defection cycle.
   - After mutual defection, cooperate with probability 1/3, to escape
     defect-defect traps.

## Why

Matches average 200 rounds and mutual cooperation pays 3 a round, so the main
value is keeping cooperation going with things that cooperate and not paying
for things that don't. Tit for tat does this well against most reactive
strategies. Recognising copies, exploiting plain cooperators and ending the
loss to defectors are the extra gains. Probes are used only while there is no
sign of punishment, so the cost against tit-for-tat-like bots is about 1 point
per probe.

## Offline checks (average points per round, haiku vs opponent, 200 rounds, 300 seeds)

| opponent | round 2 haiku | opponent | round 1 haiku |
|---|---|---|---|
| tit for tat | 2.98 | 2.98 | 2.98 |
| always cooperate | 4.72 | 0.42 | 4.86 |
| always defect | 0.97 | 1.10 | 0.88 |
| grim trigger | 1.01 | 1.08 | 0.90 |
| random | 2.32 | 2.08 | 2.04 |
| Pavlov | 2.88 | 2.94 | 2.91 |
| tit for two tats | 3.03 | 2.86 | 3.03 |
| alternating | 2.00 | 3.23 | 2.00 |
| 50% punisher | 3.01 | 2.94 | not tested |
| luna-like (20% C) | 1.75 | 0.99 | not tested |
| self | 2.95 | 2.95 | 2.96 |

The "luna-like" row is a model of round-1 `luna` (cooperates about 18% of the
time against our defections, defects against our cooperation). In the real
round-1 matches haiku scored 1.28 against it; the simulation suggests the
change moves that to roughly 1.75.

## Files

`scratch/` holds the offline simulator, round-1 analysis script and the round-1
version of `run`. The harness only runs `run`.
