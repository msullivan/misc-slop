#!/usr/bin/env python3
"""Boil the misses down.

    distill.py RUN

A miss is a *root* if it isn't explained by a smaller one: no proper
subexpression is itself a miss for that compiler, and neither is the
expression you get by replacing a subexpression with a plain variable. Roots are
grouped into families by skeleton (constants and shift amounts blanked).
"""
import json
import sys
from collections import defaultdict

import numpy as np

from analyze import Census
from terms import Lang, infix


def dominated(u, d, u2, d2):
    return (u2 <= u) & (d2 <= d) & ((u2 < u) | (d2 < d))


class Distilled:
    def __init__(self, run, comps=None):
        self.run = run
        self.lang = Lang.load(run)
        cen = self.cen = Census(run)
        self.comps = comps or cen.compilers()
        self.subs = np.concatenate([np.load(f"{run}/subs.npy"), np.load(f"{run}/abst.npy")], axis=1)
        self.skel = np.load(f"{run}/skel.npy")
        self.multi = cen.cls_size[cen.cls] > 1
        self.data = {}
        for c in self.comps:
            ids, bodies, u, d, n = cen.load(c)
            miss, wit, hard = cen.misses(u, d)
            sub_miss = np.zeros(cen.n, dtype=bool)
            for j in range(self.subs.shape[1]):
                s = self.subs[:, j]
                sub_miss |= (s >= 0) & miss[np.maximum(s, 0)]
            self.data[c] = dict(ids=ids, bodies=bodies, u=u, d=d, n=n, miss=miss, wit=wit, hard=hard,
                                root=miss & ~sub_miss)

    def best_known(self):
        """Per expression: is each compiler's code beaten by the best code
        any compiler produced for anything in the class?"""
        cen = self.cen
        allu = np.stack([self.data[c]["u"] for c in self.comps])
        alld = np.stack([self.data[c]["d"] for c in self.comps])
        out = {}
        for score_first in (0, 1):
            a, b = (allu, alld) if score_first == 0 else (alld, allu)
            score = a.astype(np.int64) * 1000 + b
            best = score.min(axis=0)
            cls_best = np.minimum.reduceat(best[cen.order], cen.starts)
            out[score_first] = cls_best[cen.cls]
        res = {}
        for ci, c in enumerate(self.comps):
            u, d = allu[ci], alld[ci]
            bu, bd = out[0] // 1000, out[0] % 1000
            beaten = dominated(u, d, bu, bd)
            bd2, bu2 = out[1] // 1000, out[1] % 1000
            beaten |= dominated(u, d, bu2, bd2)
            res[c] = beaten
        return res


def main():
    run = sys.argv[1]
    D = Distilled(run, sys.argv[2:] or None)
    cen, lang = D.cen, D.lang
    sizes = range(1, int(cen.size.max()) + 1)
    print(f"{cen.n} expressions, {len(cen.starts)} functions")
    beaten = D.best_known()
    for c in D.comps:
        x = D.data[c]
        fam = np.unique(D.skel[x["root"]])
        print(f"\n{c}: {x['miss'].sum()} misses, {x['root'].sum()} roots, {len(fam)} families; "
              f"beaten by best known: {beaten[c].sum()}")
        for k in sizes:
            m = cen.size == k
            print(f"   size {k}: {m.sum():9d} exprs  miss {100 * (x['miss'] & m).sum() / max(m.sum(), 1):6.2f}%  "
                  f"root {(x['root'] & m).sum():8d}  beaten {100 * (beaten[c] & m).sum() / max(m.sum(), 1):6.2f}%")
    # Head to head on identical source.
    print("\nrow strictly better than column, % of expressions")
    print(" " * 10 + "".join(f"{c:>10s}" for c in D.comps))
    for a in D.comps:
        row = []
        for b in D.comps:
            A, B = D.data[a], D.data[b]
            row.append(100 * dominated(B["u"], B["d"], A["u"], A["d"]).mean())
        print(f"{a:10s}" + "".join(f"{v:10.2f}" for v in row))


if __name__ == "__main__":
    main()
