# haiku

An adaptive tit-for-tat. It opens cooperatively, recognises its own copies,
exploits unconditional cooperators, gives up on unconditional defectors, and
otherwise mirrors the opponent with a few repairs for mutual-defection traps.

## Round 3 changes (after round 2: 2.94, rank 11 of 11)

Round 2 was almost all mutual cooperation (every other entrant scored about
3.00 against the field). haiku's only real loss was `opus-1`: haiku scored
1.73 against it. In those matches `opus-1` cooperated, then started defecting
for long stretches after our probes. haiku kept cooperating in the gaps and
collected the sucker payoff.

The cause was the cumulative always-defector test. It diluted: roughly 30
cooperative rounds early in the match outweighed the defections that came
later, so the verdict fell below the threshold and haiku returned to
cooperating against a defector.

Changes:
- The defector test now uses a recent window: if at least 80% of the
  opponent's last 20 moves were defections, defect. It no longer depends on
  our past cooperations, so it cannot be diluted, and it does not need our
  cooperation to keep producing evidence.
- Because the rule is now sustained by the opponent's own recent moves, a
  tit-for-tat stuck in mutual defection could otherwise trap us. Every 20th
  round we therefore cooperate once. A tit for tat copies that cooperation
  and recovers; a true defector gives us one 0 every 20 rounds.
- The always-cooperator test and the probing rule are unchanged.

Offline checks (round 3 bot, 200 rounds): always-defect 0.92 (was 0.97),
grim trigger 0.96, a model of `opus-1` (defects for 12 rounds after each of
our defections, then forgives) 1.25 for haiku, tit for tat 2.98, Pavlov 2.61
(was 2.88 with a 0.85 threshold), self 2.95. The 0.8 threshold was chosen as a
compromise: 0.85 helps Pavlov but weakens the defector response.

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

`scratch/` holds the offline simulators, the round-1 analysis script and
earlier versions of `run` (`run_v1.py`, `run_v2.py`). The harness only runs `run`.
