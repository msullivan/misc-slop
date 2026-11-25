#!/usr/bin/env python3
"""Per-expression structure the analysis needs, computed once per census.

    pre.py RUN

subs.npy   for each expression, the census index of each proper
           subexpression (-1 where there are fewer, or it isn't in the census)
abst.npy   likewise, the census index of the expression with that
           subexpression replaced by a fresh variable
skel.npy   for each expression, the id of its skeleton: the expression with
           constants and shift amounts blanked out
skel.json  the skeleton strings
"""
import json
import multiprocessing as mp
import sys

import numpy as np

from compile import load_census
from terms import Lang, key_str, subterm, abstract

run = sys.argv[1]
lang = Lang.load(run)
packed, _, _, _ = load_census(run)
n = len(packed)
MAXSUB = 4


def keys_chunk(rng):
    lo, hi = rng
    return [key_str(lang, lang.unpack(p)) for p in packed[lo:hi]]


def struct_chunk(rng):
    lo, hi = rng
    subs = np.full((hi - lo, MAXSUB), -1, dtype=np.int32)
    abst = np.full((hi - lo, MAXSUB), -1, dtype=np.int32)
    skels = []
    for r, p in enumerate(packed[lo:hi]):
        ins = lang.unpack(p)
        skels.append(key_str(lang, ins, skeleton=True))
        for j in range(len(ins) - 1):
            subs[r, j] = index.get(key_str(lang, subterm(lang, ins, j)), -1)
            a = abstract(lang, ins, j)
            if a is not None:
                abst[r, j] = index.get(key_str(lang, a), -1)
    return subs, abst, skels


if __name__ == "__main__":
    size = lang.sizes(packed)
    kmax = int(size.max())
    small = np.flatnonzero(size < kmax)
    chunks = [(i, min(i + 20000, n)) for i in range(0, n, 20000)]
    with mp.Pool(60) as pool:
        # Subexpressions are always smaller than the largest size, and the
        # census is stored smallest first.
        nsmall = len(small)
        assert (small == np.arange(nsmall)).all()
        index = {}
        for (lo, hi), ks in zip(chunks, pool.imap(keys_chunk, [c for c in chunks if c[0] < nsmall])):
            for i, k in zip(range(lo, hi), ks):
                if i < nsmall:
                    index[k] = i
    with mp.get_context("fork").Pool(60) as pool:  # forked, so workers see `index`
        subs = np.empty((n, MAXSUB), dtype=np.int32)
        abst = np.empty((n, MAXSUB), dtype=np.int32)
        skel = np.empty(n, dtype=np.int32)
        names = {}
        for (lo, hi), (s, ab, sk) in zip(chunks, pool.imap(struct_chunk, chunks)):
            subs[lo:hi] = s
            abst[lo:hi] = ab
            skel[lo:hi] = [names.setdefault(x, len(names)) for x in sk]
    np.save(f"{run}/subs.npy", subs)
    np.save(f"{run}/abst.npy", abst)
    np.save(f"{run}/skel.npy", skel)
    with open(f"{run}/skel.json", "w") as f:
        json.dump(list(names), f)
    print(f"{n} expressions, {len(names)} skeletons, {(subs[:, 0] < 0).sum()} with a subexpression outside the census (incl. size 1)")
