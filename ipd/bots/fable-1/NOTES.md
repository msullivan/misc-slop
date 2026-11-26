# fable-1

Nice, retaliatory, forgiving; adapts to opponents that do not respond to
cooperation; probes cautiously for opponents that never retaliate.

## Strategy (round 1 version)

1. **Core: tit-for-tat**, opening with C. No noise in this tournament, so plain
   reciprocity gets 3/round against every nice bot and against itself.
2. **Echo forgiveness.** If the opponent's D answers a D of mine that was played
   while they were cooperating, I play C instead of bouncing it back. This
   ends the CD/DC echo that TFT falls into with probers (and with my own
   probes). It is switched off when the opponent's decayed count of unprovoked
   defections exceeds 2.5, so a "D, apologise, D again" cycle cannot farm it.
3. **Peace offers.** After 6+ rounds without mutual cooperation I play C twice,
   with the gap doubling (6, 12, 24, ... 100). Escapes DD locks with
   suspicious/retaliatory bots; costs ~nothing against always-defect.
4. **Reactive model -> all-D.** I keep decayed estimates p = P(they C | I
   played C) and q = P(they C | I played D). When 1 + 4q > 3p + 0.5 (defecting
   out-earns cooperating; true of random and always-D style bots) I defect
   every round, with a single test C at widening intervals, and return to
   cooperation if the numbers flip.
5. **Probe for non-retaliators (25% of matches).** At a random round in 8..25,
   if nobody has defected yet, play D,C,D,C,D,C. Any retaliation ends the
   probe at once (and rule 2 absorbs the punishment: net cost about 1 point
   against TFT). If three probes go unanswered, defect every round; if that
   finally draws a D, apologise and fall back to alternating D/C (the best
   reply to tit-for-two-tats), and give up for good if that is punished too.

## Why

A field of agent-written bots is probably mostly TFT variants, so the main job
is never to lose mutual cooperation, and to recover it fast after someone
else's probe. Rules 2-3 do that. Rule 4 stops bleeding against random/hostile
bots. Rule 5 is a gamble: it pays +1 to +2/round against pushovers and costs
about -2/round for the rest of the match against a grim trigger. It is only
on in a quarter of matches, partly to learn from the round 1 transcripts
whether the field contains pushovers or grims; adjust PROBE_PROB accordingly.

## Local results (200 rounds, simulated)

always-C 3.0 (4.9 when probing), TFT 3.0, TF2T 3.0 (3.9 probing), grim 3.0
(1.1 probing), always-D 0.96, random ~2.8-3.0, self 3.0.
