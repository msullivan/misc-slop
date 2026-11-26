# sol

Sol opens with cooperation and usually mirrors the opponent's last move. It
occasionally offers cooperation when a defection looks like retaliation. That
can restore mutual cooperation after an isolated defection, and a cooldown
limits how often an opponent can take advantage of the offer.

Five defections in the last twelve rounds put Sol on defense until the
opponent cooperates five times in a row.

The opening aims for three points per round against reciprocal opponents and
in self-play. A deliberate opening probe could cost the rest of the match
against an unforgiving opponent.

## Round two

Round one finished first at 2.8881 points per round. Four Terra matches
showed the same failure pattern. Sol counted cooperative replies to its own
defections across two incidents separated by more than 50 rounds. It kept
defecting after Terra resumed cooperation, and the exchanges that followed
settled into mutual defection. Sol now resumes cooperation when retaliation
ends, unless its recent history has already put it on defense. The opening,
repair cooldown, and defense thresholds carry over from round one.

## Final round

Round two finished fourth at 2.9962 points per round. Fifty of the 55
matches were all cooperation. The other five returned to cooperation after
a few probes. Sol keeps its response to those probes.

Sol now makes one two-round cooperation offer per match if it has seen at
least 12 consecutive rounds of mutual cooperation and later gets stuck in
eight consecutive rounds of mutual defection while on defense. Two rounds
give an opponent time to see the offer and respond. If the opponent
cooperates on the second round, Sol clears its defensive window. If the
opponent defects through both rounds, the offer costs Sol two points.
