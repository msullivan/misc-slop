#!/usr/bin/env python3
"""Prove the census's equivalence classes instead of trusting the tests.

    verify.py RUN [--max-size K] [--timeout MS]

Every expression (up to the given size) is proved equal to the smallest
member of its class. One that is shown different is moved to a class of its
own. One the solver can't settle in time stays where the tests put it, and
is counted. Writes RUN/key3.npy, the corrected class key per expression,
and RUN/verify.json, the tally.
"""
import argparse
import multiprocessing as mp
import sys
import time

import numpy as np

from analyze import Census
from prove import prove
from terms import Lang, swap_vars, infix

ap = argparse.ArgumentParser()
ap.add_argument("run")
ap.add_argument("--max-size", type=int, default=9)
ap.add_argument("--timeout", type=int, default=5000)
ap.add_argument("--jobs", type=int, default=60)
a = ap.parse_args()
lang = Lang.load(a.run)
cen = Census(a.run, proved=False)


def job(pair):
    i, r = pair
    t, tr = lang.unpack(cen.packed[i]), lang.unpack(cen.packed[r])
    if cen.fp[i] != cen.fp[r]:
        tr = swap_vars(lang, tr)
    return (i,) + tuple(prove(lang, t, tr, timeout_ms=a.timeout))


if __name__ == "__main__":
    # Representative: the first (smallest) member of each class.
    rep = cen.order[cen.starts][cen.cls]
    pending = np.flatnonzero((rep != np.arange(cen.n)) & (cen.size <= a.max_size))
    total = len(pending)
    print(f"{total} equalities to prove", file=sys.stderr)
    key3 = cen.key.copy()
    counts = dict(proved=0, refuted=0, unknown=0)
    cexs = []
    t0 = time.time()
    rounds = 0
    # Z3 never quite gives memory back; replace each worker after a while.
    with mp.get_context("fork").Pool(a.jobs, maxtasksperchild=40) as pool:
        while len(pending):
            rounds += 1
            refuted = []
            chunk = 200 if rounds == 1 else 8
            for n, (i, st, cex) in enumerate(pool.imap_unordered(job, zip(pending, rep[pending]), chunksize=chunk)):
                if rounds == 1 or st != "refuted":
                    counts[st] += 1
                if st == "refuted":
                    refuted.append(int(i))
                    if rounds == 1:
                        cexs.append(cex)
                        if len(cexs) <= 10:
                            print("  not equal:", infix(lang, lang.unpack(cen.packed[i])), "vs",
                                  infix(lang, lang.unpack(cen.packed[rep[i]])), file=sys.stderr)
                if rounds == 1 and n % 20000 == 0:
                    print(f"\r{n}/{total} {counts} {n / max(time.time() - t0, 1e-9):.0f}/s", end="", file=sys.stderr)
            # Everything that turned out different from its representative
            # leaves the class. The leavers from one class form a new one
            # around their smallest member, to be checked in the next round.
            groups = {}
            for i in sorted(refuted):
                groups.setdefault(int(rep[i]), []).append(i)
            nxt = []
            for members in groups.values():
                new = members[0]
                for i in members:
                    rep[i] = new
                    key3[i] = np.uint64(0xF000000000000000) + np.uint64(new)
                nxt.extend(members[1:])
            pending = np.array(nxt, dtype=np.int64)
    counts["rounds"] = rounds
    print(f"\n{counts} in {time.time() - t0:.0f}s", file=sys.stderr)
    np.save(f"{a.run}/key3.npy", key3)
    with open(f"{a.run}/cex.txt", "a") as f:
        for c in cexs:
            f.write(" ".join(map(str, c)) + "\n")
    with open(f"{a.run}/verify.json", "w") as f:
        import json
        json.dump(dict(counts, max_size=min(a.max_size, lang.k), total=int(total)), f)
