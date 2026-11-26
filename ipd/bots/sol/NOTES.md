# sol

Sol opens with cooperation and usually mirrors the opponent's last move. It
occasionally offers cooperation when a defection looks like retaliation. That
can restore mutual cooperation after an isolated defection, and a cooldown
limits how often an opponent can take advantage of the offer.

Five defections in the last twelve rounds put Sol on defense until the
opponent cooperates five times in a row. Sol also defects when the opponent has
answered its last three defections with cooperation. It measures those replies
with a one-round lag because moves are simultaneous.

The opening aims for three points per round against reciprocal opponents and
in self-play. Sol waits for defections to arise naturally before testing
whether an opponent will tolerate them. A deliberate opening probe could cost
the rest of the match against an unforgiving opponent.
