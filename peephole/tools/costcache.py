#!/usr/bin/env python3
"""Precompute the per-body cost tables for a run (analysis does it lazily
otherwise) and report anything the cost model couldn't read.

    tools/costcache.py RUN
"""
import collections
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyze import Census, UNKNOWN
from asmcost import cost, Unknown, BRANCHY, FAILED

if __name__ == "__main__":
    run = sys.argv[1]
    cen = Census(run, proved=False)
    for comp in cen.compilers():
        fresh = not os.path.exists(f"{run}/asm/{comp}.cost.npy")
        ids, text, u, d, n = cen.load(comp, bodies=fresh)
        line = f"{comp}: branchy {int((u == BRANCHY).sum())}, failed {int((u == FAILED).sum())}, unknown {int((u == UNKNOWN).sum())}"
        if fresh:
            c = np.load(f"{run}/asm/{comp}.cost.npy")
            mn = collections.Counter()
            for i in np.flatnonzero(c[:, 0] == UNKNOWN)[:20000]:
                try:
                    cost(text[i])
                except Unknown as e:
                    mn[str(e).split()[0]] += 1
            line += f" {dict(mn.most_common(8))}"
        print(line, flush=True)
