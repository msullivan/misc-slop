# fable-2

Nice, retaliatory, quick to make up, and it measures before it changes course.
Deterministic; Python, no dependencies.

## Strategy

Base behaviour is tit-for-tat (open with C, never defect first), with three
repairs and two measured fallback modes.

1. **Echo breaking.** If their D is a plain answer to my own retaliation
   (I played D, they were cooperating before it), I accept it instead of
   re-punishing. This ends the CD/DC echo that TFT-vs-suspicious-TFT or
   TFT-vs-prober falls into (2.5/round instead of 3). Budgeted
   (3 + one per 40 rounds) so it can't be farmed.
2. **Peace offers.** After a mutual-defection streak I play C twice (two are
   needed to turn a TFT around). The required streak doubles after every
   offer (2, 4, 8, ...) so always-defect loses almost nothing to it; it resets
   after 20 rounds of mutual cooperation.
3. **Defect mode (measured).** If the last 40 rounds average under 2.4, or a
   memory-1 estimate says the opponent cooperates just as often after my D
   (random-ish / unresponsive bots), I defect for 20 rounds and compare the
   actual payoff with what I had before. Better by 0.25 -> keep defecting while
   it stays better; otherwise offer peace and go back to TFT. Retry cooldown
   doubles.
4. **Absorb mode (measured).** If the opponent mostly cooperates after my C
   but throws in occasional defections, and my retaliation is just costing me
   (their counter-retaliation makes each incident worth less than swallowing
   it), I stop retaliating for 30 rounds and keep that up only while the
   measured payoff beats the previous baseline. An opponent who answers this by
   defecting more pushes the average down and I go back to TFT, with a doubling
   cooldown.

## Why

- No noise in this game, and the field is a dozen agent-written bots, most of
  which will be TFT relatives, some grim-like, some probing for pushovers.
  Never defecting first keeps 3/round against all the nice ones (including
  grim and my own copy); always retaliating at least initially makes probers
  conclude I am not exploitable.
- With no known last round (1/200 stop chance) there is no endgame to defect in.
- The fallback modes decide on realised payoff rather than on a guess about
  what the opponent is, so a wrong guess costs a bounded number of rounds.
- Round 1 is deliberately conservative (no first defections, so nothing learnt
  about who tolerates them). The transcripts decide whether targeted
  exploitation is worth adding later.

## Local results (in-process sim, 60 matches each, points/round)

TFT, grim, TF2T, generous TFT, Pavlov, always-C, threshold-grim, self: 3.00;
suspicious TFT 2.98; prober 2.99; random 2.78; alternator 2.69; always-D 0.94;
joss (10% sneaky D) 2.52; periodic tester 2.77; 85%-C unresponsive 3.91.
