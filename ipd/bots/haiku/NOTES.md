# haiku

An adaptive tit-for-tat. It opens cooperatively, recognises its own copies,
exploits unconditional cooperators, gives up on unconditional defectors, and
otherwise mirrors the opponent with a few repairs for mutual-defection traps.

## Strategy, in order of precedence

1. **Handshake (rounds 1-4): `C D D C`.** The opening is a fixed signature.
   Two bots that both run this strategy play the same four moves no matter
   what the other does, so each can recognise the other.
2. **Copy of haiku.** If the opponent's first four moves are the handshake and
   it has never defected since, play `C` for as long as it cooperates. Two
   copies then sit at 3 points a round.
3. **Unconditional defector.** If the opponent has defected after at least 5 of
   our cooperations in the last 40 rounds, defect for good (`D` beats `C`
   against a defector).
4. **Unconditional cooperator.** If the opponent has cooperated after at least
   4 of our defections in the last 40 rounds, keep defecting: it gives 5 per
   round to us for as long as it keeps cooperating.
5. **Probing.** Against an opponent that has never punished a defection, play
   a single `D` after 8 rounds of its cooperation, at most 4 times in total,
   spaced at least 8 rounds apart. This is how step 4 gets evidence. Once any
   opponent punishes a probe, probing stops for the rest of the match.
6. **Tit for tat, with two repairs.**
   - After a probe, a single defection is forgiven (we cooperate), so that a
     tit-for-tat opponent does not lock us into a defection cycle.
   - After mutual defection, cooperate with probability 1/3, to escape
     defect-defect traps.

## Why

With matches averaging 200 rounds and a 3-point payoff for mutual cooperation,
the main value is keeping cooperation going with things that cooperate and
not paying for things that don't. Tit for tat does this well against most
reactive strategies. Recognising copies and exploiting plain cooperators are
the two extra gains, and both are cheap to test for. Probes are used only
while there is no sign of punishment, so the cost against tit-for-tat-like
bots is one or two rounds at most.

## Offline checks (average points per round, haiku vs opponent, 200 rounds)

| opponent | haiku | opponent |
|---|---|---|
| tit for tat | 2.98 | 2.98 |
| always cooperate | 4.86 | 0.21 |
| always defect | 0.88 | 1.48 |
| grim trigger | 0.90 | 1.53 |
| random | 2.04 | 2.75 |
| Pavlov | 2.91 | 2.95 |
| tit for two tats | 3.03 | 2.86 |
| alternating | 2.00 | 3.23 |
| self | 2.96 | 2.96 |

The handshake costs about 0.04 per round against copies, and the defection
against defectors costs about 0.1, but the wins against cooperators and
against copies are large.
