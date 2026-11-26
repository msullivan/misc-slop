# opus-1

Python, no build step. `run` drives `strategy.py`. If the strategy throws, `run`
falls back to tit-for-tat for the rest of the match rather than forfeit it.

## Strategy (round 1)

The game has no noise and no known last round, so mutual cooperation (3/round)
is the baseline against any reciprocating bot. Most of the score difference
comes from (a) not losing rounds to echoes and lock-ups with other
reciprocators, (b) not being farmed, and (c) taking points from bots that
don't react to what I do.

1. **Base: tit-for-tat that absorbs retaliation.** Open with C and copy their last
   move, with one exception. A D that arrives within a few rounds of one of my
   own D's (one that landed on their C) is read as their retaliation, so I
   don't echo it. This ends CD/DC echoes with TFT-like bots in one round, and
   it also calms bots that punish twice. The allowance is rationed: an absorb
   that isn't followed by two of their C's costs credit, and when credit runs
   out I play plain TFT.
2. **Unresponsive-opponent detector.** Over the last 80 rounds I estimate
   p1 = P(they C | I just played C) and p0 = P(they C | I just played D).
   Always-C is worth about 3·p1 a round and always-D about 1 + 4·p0. When
   always-D is clearly better (random bots, always-defect, bots that mostly
   cooperate but ignore what I do), I defect.
3. **Overtures.** After several of their D's in a row I play C twice. The wait
   before the next overture doubles each time one is refused, up to 64 rounds.
   This gets me out of mutual-defection lock with model-based bots that have
   wrongly classified me. Against always-defect it costs about 0.05/round.
4. **Probe-and-exploit, in 20% of matches.** After at least round 40 and 20
   calm rounds, I defect once. Any answering D means I stop probing for good,
   and my absorb logic smooths over their retaliation. If they don't answer,
   I probe again, and if that also goes unanswered I defect periodically: every
   5th round, then more often while it stays unanswered. When they answer I
   back off a level and apologise.

The 20% is deliberate for round 1. It caps the cost against grim-trigger bots
at about a fifth of a ruined pairing, and the transcripts will show how each
opponent reacts to an unprovoked defection. If round 1 shows no pushovers, I
can set PROBE_P to 0. If it shows several, I can raise it.

Tested against a zoo of about 30 classic strategies (TFT, TF2T, GTFT, Grim,
Pavlov, Gradual, Tester, Detective, Joss, Random, extortionate ZD, model-based
detectors, over-punishers, probers) plus self-play. It is never the first to
defect except for the deliberate probe, it gets 3.0 against every nice bot,
and it gets 2.9 to 4.1 against random bots.

## Round 2 changes

Round 1: 9th of 11 at 2.760. Against everyone except luna I scored 2.89 to
3.00. Against luna I scored 1.07, while terra scored 2.01 and sonnet and
fable-2 1.82. That one pairing decided most of my rank.

What the transcripts showed:

- **No pushovers.** All six of my probes were answered with an immediate D.
  Probing is now off (`PROBE_P = 0`). The code is still there.
- **luna** played the same sequence in all five games. Against me, luna
  cooperated exactly when my previous two moves were C then D, and defected
  otherwise. Plain TFT plus overtures gets about 1 against that. The best
  periodic answer gets about 2.
- **terra** defects twice every 60 rounds and then returns to cooperation.
  My retaliation was right, but my "unresponsive opponent" detector saw
  "they cooperate after my D" and wrongly switched to defecting. That
  started a 5-round DD stretch each time (2.89 against terra instead of about
  2.95).
- haiku, sonnet and fable-1 probe early with one or two D's. TFT plus
  absorbing handles them, losing about 5 points a game, which I accept.

Changes:

1. **Detector gate.** The always-defect detector now fires only if, in the
   window, the opponent defected after two of my C's at least 15% of the time
   (out of at least 20 such chances). Bots that probe occasionally never reach
   that. Random-like bots do.
2. **Model mode for bad matches.** If my mean over the last 20 rounds drops
   below 1.6, the bot learns P(their next move | my last two moves, their last
   move). It uses decayed counts, with the opponent's recent cooperation rate
   as the prior for contexts it hasn't seen. It then plays the
   value-iteration optimum under that model (discount 0.97). It returns to the
   base strategy once recent play is good again (mean above 2.6 and six
   mutual-C rounds in a row). Against an emulation of luna as it played me,
   this goes from 1.08 to 1.97. It never activates in a cooperative match.

Simulation code (zoo of opponents, including emulations of the luna, terra,
haiku and sonnet patterns from my own transcripts) is in `sim/`. Run
`pypy3 cmp.py r1_strategy.py ../strategy.py` from there.
