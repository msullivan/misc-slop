#!/usr/bin/env python3
"""haiku: an adaptive iterated prisoner's dilemma strategy.

See NOTES.md for the reasoning.  decide() is a pure function of the two move
histories (plus a coin flip), so the same code is used in offline simulation.
"""
import random
import sys

HANDSHAKE = "CDDC"   # our opening; a deterministic copy of haiku replies with it
WINDOW = 40          # how far back the opponent-behaviour tests look
PROBE_GAP = 8        # rounds between exploitation probes
PROBE_AFTER = 8      # only probe after this many rounds of opponent cooperation
MAX_PROBES = 4
FORGIVE = 1 / 3      # chance to restart cooperation after mutual defection


def decide(mine, theirs, rng):
    t = len(mine)
    n = len(HANDSHAKE)
    if t < n:
        return HANDSHAKE[t]

    # 1. A copy of haiku: it opened with the same handshake and cooperates
    #    while we do. Cooperate for as long as it does not defect.
    if theirs[:n] == HANDSHAKE and "D" not in theirs[n:]:
        return "C"

    lo = max(1, t - WINDOW)
    after_c = [theirs[i] for i in range(lo, t) if mine[i - 1] == "C"]
    after_d = [theirs[i] for i in range(lo, t) if mine[i - 1] == "D"]

    # 2. Unconditional defector: defects after (nearly) every cooperation of ours.
    if len(after_c) >= 5 and after_c.count("D") == len(after_c):
        return "D"

    # 3. Unconditional cooperator: still cooperates after our defections.
    if len(after_d) >= 4 and after_d.count("C") == len(after_d):
        return "D"

    # 4. Probe for exploitable cooperators, but only while no opponent has ever
    #    answered one of our defections with a defection (a punisher).
    ever_punished = any(theirs[i] == "D" for i in range(n, t) if mine[i - 1] == "D")
    probes = sum(1 for i in range(n, t) if mine[i] == "D")
    last_d = max((i for i in range(n, t) if mine[i] == "D"), default=-PROBE_GAP)
    if (not ever_punished and probes < MAX_PROBES and t >= PROBE_AFTER
            and t - last_d >= PROBE_GAP
            and all(r == "C" for r in theirs[-PROBE_AFTER:])):
        return "D"

    # 5. Tit for tat, with two repairs:
    last = theirs[-1]
    if last == "C":
        return "C"
    if mine[-1] == "D":
        # Mutual defection: restart cooperation sometimes, so two defectors can
        # climb back out of the mutual-defection trap.
        return "C" if rng.random() < FORGIVE else "D"
    if t >= 2 and mine[-2] == "D" and theirs[-2] == "C":
        # Their defection answers our probe: forgive it.
        return "C"
    return "D"


def main():
    rng = random.Random()
    mine, theirs = [], []
    while True:
        move = decide(mine, theirs, rng)
        sys.stdout.write(move + "\n")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            break
        theirs.append(line.strip())
        mine.append(move)


if __name__ == "__main__":
    main()
