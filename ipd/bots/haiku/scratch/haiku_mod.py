#!/usr/bin/env python3
"""haiku (round 2): an adaptive iterated prisoner's dilemma strategy.

See NOTES.md for the reasoning.  decide() is a pure function of the two move
histories (plus a coin flip), so the same code is used in offline simulation.
"""
import random
import sys

HANDSHAKE = "CDDC"   # our opening; a deterministic copy of haiku replies with it
N = len(HANDSHAKE)
PROBE_GAP = 8        # rounds between exploitation probes
PROBE_AFTER = 8      # only probe after this many rounds of opponent cooperation
MAX_PROBES = 4       # cap on our defections after the handshake while probing
FORGIVE = 1 / 3      # chance to restart cooperation after mutual defection


def decide(mine, theirs, rng):
    t = len(mine)
    if t < N:
        return HANDSHAKE[t]

    # 1. A copy of haiku: it opened with the same handshake and cooperates
    #    while we do. Cooperate for as long as it does not defect.
    if theirs[:N] == HANDSHAKE and "D" not in theirs[N:]:
        return "C"

    # Their reply to each of our moves, counted from the first round after the
    # handshake. Cumulative over the whole match, so verdicts persist even when
    # we stop playing the move that produced the evidence.
    c_total = c_punished = 0   # rounds after our C, and how often they defected
    d_total = d_punished = 0   # rounds after our D, and how often they defected
    for i in range(N, t):
        if mine[i - 1] == "C":
            c_total += 1
            c_punished += theirs[i] == "D"
        else:
            d_total += 1
            d_punished += theirs[i] == "D"

    # 2. Unconditional defector: defects after most of our cooperations.
    #    Defecting back is then strictly better (1 beats 0, and their cooperation
    #    is rare).
    if c_total >= 4 and c_punished >= 0.75 * c_total:
        return "D"

    # 3. Unconditional cooperator: still cooperates after (nearly) all of our
    #    defections. Keep defecting to collect 5 a round.
    if d_total >= 4 and d_punished <= 0.1 * d_total:
        return "D"

    # 4. Probe for exploitable cooperators. Only while the opponent has punished
    #    at most one of our defections (a tit-for-tat punisher answers every one).
    probes = sum(1 for i in range(N, t) if mine[i] == "D")
    last_d = max((i for i in range(N, t) if mine[i] == "D"), default=-PROBE_GAP)
    if (d_punished <= 1 and probes < MAX_PROBES and t >= PROBE_AFTER
            and t - last_d >= PROBE_GAP
            and all(r == "C" for r in theirs[-PROBE_AFTER:])):
        return "D"

    # 5. Tit for tat, with two repairs.
    if theirs[-1] == "C":
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
