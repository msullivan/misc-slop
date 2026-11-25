#!/usr/bin/env python3
"""Find where a compiler disagrees with itself.

    analyze.py RUN [COMPILER ...]

Census expressions with the same fingerprint compute the same function. For
each compiler, an expression is a miss if the same compiler produced strictly
better code for another expression in its class.
"""
import json
import os
import sys

import numpy as np

import multiprocessing as mp

from asmcost import cost, Unknown
from compile import load_census
from terms import Lang


UNKNOWN = 97
WRONG = 96


def cost_or_unknown(body):
    try:
        return cost(body)
    except Unknown:
        return UNKNOWN, UNKNOWN, body.count(";") + 1


class Census:
    def __init__(self, run, proved=True):
        self.run = run
        self.packed, self.fp, self.key, self.cost = load_census(run)
        self.n = len(self.packed)
        if os.path.exists(f"{run}/key2.bin"):
            # The stronger key: equal on ~130k more inputs, not just 160.
            k2 = np.fromfile(f"{run}/key2.bin", dtype=np.uint64)
            assert len(k2) == self.n
            self.key = k2 ^ (self.key * np.uint64(0x9E3779B97F4A7C15))
        if proved and os.path.exists(f"{run}/key3.npy"):
            # Classes whose every equality was proved by verify.py.
            self.key = np.load(f"{run}/key3.npy")
        self.size = Lang.load(run).sizes(self.packed)
        self.order = np.argsort(self.key, kind="stable")
        ks = self.key[self.order]
        self.starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
        self.cls = np.empty(self.n, dtype=np.int64)  # class number per expression
        self.cls[self.order] = np.repeat(np.arange(len(self.starts)), np.diff(np.r_[self.starts, self.n]))
        self.cls_size = np.diff(np.r_[self.starts, self.n])

    def compilers(self):
        return sorted(f[:-8] for f in os.listdir(f"{self.run}/asm") if f.endswith(".ids.npy"))

    def load(self, comp, bodies=False):
        """-> ids, bodies, uops, depth, ninstr (per expression). The bodies
        (one string per distinct piece of machine code) are only read if
        asked for; their costs are computed once and cached."""
        ids = np.load(f"{self.run}/asm/{comp}.ids.npy")
        cache = f"{self.run}/asm/{comp}.cost.npy"
        text = None
        if bodies or not os.path.exists(cache):
            text = json.load(open(f"{self.run}/asm/{comp}.bodies.json"))
        if os.path.exists(cache):
            c = np.load(cache)
        else:
            with mp.Pool(min(60, max(1, len(text) // 20000))) as pool:
                c = np.array(pool.map(cost_or_unknown, text, chunksize=20000), dtype=np.int32)
            np.save(cache, c)
            unk = int((c[:, 0] == UNKNOWN).sum())
            if unk:
                print(f"{comp}: {unk} bodies with instructions the cost model doesn't know", file=sys.stderr)
        u, d, n = c[ids, 0], c[ids, 1], c[ids, 2]
        # Code that computes the wrong thing isn't better code.
        wrong = json.load(open(f"{self.run}/asm/{comp}.wrong.json"))
        u[wrong] = d[wrong] = WRONG
        return ids, text, u, d, n

    def class_best(self, uops, depth):
        """For each class, the member with fewest uops (ties: shallowest) and
        the shallowest member (ties: fewest uops). -> (iA, iB) member indices."""
        out = []
        for score in (uops.astype(np.int64) * 1000 + depth, depth.astype(np.int64) * 1000 + uops):
            o = np.lexsort((np.arange(self.n), score, self.key))
            out.append(o[self.starts])  # lexsort groups by key in the same class order
        return out

    def misses(self, uops, depth):
        """Per expression: is it beaten by its class's best, by which member,
        and is it beaten on uops (rather than only on depth)?"""
        res = np.zeros(self.n, dtype=bool)
        hard = np.zeros(self.n, dtype=bool)
        wit = np.full(self.n, -1, dtype=np.int64)
        for i in self.class_best(uops, depth):
            w = i[self.cls]
            u2, d2 = uops[w], depth[w]
            dom = (u2 <= uops) & (d2 <= depth) & ((u2 < uops) | (d2 < depth)) & (uops < 90)
            wit[dom & ~res] = w[dom & ~res]
            res |= dom
            hard |= dom & (u2 < uops)
        return res, wit, hard


def main():
    run = sys.argv[1]
    cen = Census(run)
    comps = sys.argv[2:] or cen.compilers()
    multi = cen.cls_size[cen.cls] > 1
    print(f"{cen.n} expressions in {len(cen.starts)} classes; {multi.sum()} share a class with another")
    for comp in comps:
        ids, bodies, u, d, n = cen.load(comp)
        miss, wit, _ = cen.misses(u, d)
        np.save(f"{run}/asm/{comp}.miss.npy", miss)
        np.save(f"{run}/asm/{comp}.wit.npy", wit)
        by = [f"{k}:{(miss & (cen.size == k)).sum()}/{(multi & (cen.size == k)).sum()}" for k in range(1, 5)]
        print(f"{comp:10s} misses {miss.sum():9d} ({100 * miss.sum() / multi.sum():.2f}%)  by size {' '.join(by)}")


if __name__ == "__main__":
    main()
