# luna

## Round 2

Luna opens with cooperation and drops the forced round 3 defection. In
round 1, that probe and the repeated defections that followed often turned
an initially cooperative match into persistent mutual defection. Self play
also alternated mutual cooperation and mutual defection. Luna finished
with 1.4896 points per round, while most other pairings were near 3.

Luna now forgives an isolated defection. Two opposing defections in the
last eight rounds trigger two defensive rounds, followed by up to two
cooperative rounds to repair the relationship. If both offers fail, Luna
doubles the next defensive stretch, up to 64 rounds. Mutual cooperation
during repair resets the defense. This favors stable cooperation and limits
the cost of trying to recover against persistent defectors.

## Round 3

Round 2 earned 2.9900 points per round. Every match except the five
against Haiku was mutual cooperation throughout. Those five accounted for
the entire 97 point deficit relative to three points per round.

Luna keeps the cooperative opening and the round 2 repair policy. It now
looks for three defections separated by two identical gaps of at least
eight rounds. It defects once when the next defection is due, then
requires fresh observations. Haiku showed eight round gaps in round 2.
Correctly anticipating a defection earns one point instead of zero, but
an incorrect prediction can draw retaliation. Luna never probes a
partner that cooperates throughout.
