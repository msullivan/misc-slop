"""Prove two expressions equal for all 32-bit inputs.

Z3 does most of it. Multiplication is where SAT solvers go to die, so
identities Z3 can't settle in time are retried as polynomial identities:
if both sides use only + - * and left shifts, they are equal whenever
their expanded polynomials are equal modulo 2^32.
"""
import itertools
from collections import Counter

import numpy as np
import z3

from terms import OPS, M32, SHIFTS


def to_z3(lang, ins, xs):
    one, zero = z3.BitVecVal(1, 32), z3.BitVecVal(0, 32)
    b2i = lambda c: z3.If(c, one, zero)
    f = {
        "add": lambda x, y: x + y, "sub": lambda x, y: x - y, "mul": lambda x, y: x * y,
        "and": lambda x, y: x & y, "or": lambda x, y: x | y, "xor": lambda x, y: x ^ y,
        "eq": lambda x, y: b2i(x == y), "ne": lambda x, y: b2i(x != y),
        "lts": lambda x, y: b2i(x < y), "ltu": lambda x, y: b2i(z3.ULT(x, y)),
        "les": lambda x, y: b2i(x <= y), "leu": lambda x, y: b2i(z3.ULE(x, y)),
        "smin": lambda x, y: z3.If(x < y, x, y), "smax": lambda x, y: z3.If(x > y, x, y),
        "umin": lambda x, y: z3.If(z3.ULT(x, y), x, y), "umax": lambda x, y: z3.If(z3.UGT(x, y), x, y),
    }
    vals = list(xs) + [z3.BitVecVal(c, 32) for c in lang.consts]
    for op, a, b in ins:
        name = OPS[op]
        x = vals[a]
        if name == "shl":
            r = x << lang.shifts[b]
        elif name == "lshr":
            r = z3.LShR(x, lang.shifts[b])
        elif name == "ashr":
            r = x >> lang.shifts[b]
        else:
            r = f[name](x, vals[b])
        vals.append(r)
    return vals[-1]


def to_poly(lang, ins):
    """-> {monomial (tuple of var exponents): coeff mod 2^32}, or None."""
    def var(i):
        e = [0] * lang.nv
        e[i] = 1
        return {tuple(e): 1}
    vals = [var(i) for i in range(lang.nv)] + [{(0,) * lang.nv: c} if c else {} for c in lang.consts]
    for op, a, b in ins:
        name = OPS[op]
        x = vals[a]
        if name == "shl":
            r = {m: (c << lang.shifts[b]) & M32 for m, c in x.items()}
        elif name in ("add", "sub"):
            r = Counter(x)
            for m, c in vals[b].items():
                r[m] = (r[m] + c if name == "add" else r[m] - c) & M32
        elif name == "mul":
            r = Counter()
            for (m1, c1), (m2, c2) in itertools.product(x.items(), vals[b].items()):
                m = tuple(i + j for i, j in zip(m1, m2))
                r[m] = (r[m] + c1 * c2) & M32
        else:
            return None
        vals.append({m: c for m, c in r.items() if c})
    return vals[-1]


def prove(lang, a, b, swap_b=False, timeout_ms=10000):
    """-> ("proved", how) | ("refuted", counterexample) | ("unknown", None).
    With swap_b, b's variables are exchanged first (two variables only)."""
    xs = [z3.BitVec(f"v{i}", 32) for i in range(lang.nv)]
    ys = xs[::-1] if swap_b else xs
    if not swap_b:
        pa, pb = to_poly(lang, a), to_poly(lang, b)
        if pa is not None and pb is not None and pa == pb:
            return "proved", "polynomial"
    s = z3.SolverFor("QF_BV")
    s.set("timeout", timeout_ms)
    s.add(to_z3(lang, a, xs) != to_z3(lang, b, ys))
    r = s.check()
    if r == z3.unsat:
        return "proved", "z3"
    if r == z3.sat:
        m = s.model()
        return "refuted", [m.eval(x, model_completion=True).as_long() for x in xs]
    if not swap_b:
        cex = random_test(lang, a, b)
        if cex is not None:
            return "refuted", cex
    if swap_b:
        pa = to_poly(lang, a)
        pb = to_poly(lang, b)
        if pa is not None and pb is not None and lang.nv == 2:
            if pa == {(m[1], m[0]): c for m, c in pb.items()}:
                return "proved", "polynomial"
    return "unknown", None


def np_eval(lang, ins, xs):
    """Evaluate on numpy uint32 arrays."""
    u, i = np.uint32, np.int32
    f = {
        "add": lambda x, y: x + y, "sub": lambda x, y: x - y, "mul": lambda x, y: x * y,
        "and": lambda x, y: x & y, "or": lambda x, y: x | y, "xor": lambda x, y: x ^ y,
        "eq": lambda x, y: (x == y).astype(u), "ne": lambda x, y: (x != y).astype(u),
        "lts": lambda x, y: (x.view(i) < y.view(i)).astype(u), "ltu": lambda x, y: (x < y).astype(u),
        "les": lambda x, y: (x.view(i) <= y.view(i)).astype(u), "leu": lambda x, y: (x <= y).astype(u),
        "smin": lambda x, y: np.minimum(x.view(i), y.view(i)).view(u),
        "smax": lambda x, y: np.maximum(x.view(i), y.view(i)).view(u),
        "umin": np.minimum, "umax": np.maximum,
    }
    vals = list(xs) + [np.full_like(xs[0], c) for c in lang.consts]
    for op, a, b in ins:
        name = OPS[op]
        x = vals[a]
        if name == "shl":
            r = x << u(lang.shifts[b])
        elif name == "lshr":
            r = x >> u(lang.shifts[b])
        elif name == "ashr":
            r = (x.view(i) >> i(lang.shifts[b])).view(u)
        else:
            r = f[name](x, vals[b])
        vals.append(r)
    return vals[-1]


def random_test(lang, a, b, n=1 << 22, seed=1):
    """-> a counterexample, or None if a and b agree on n random inputs
    (uniform, sparse, dense, and values near each other)."""
    rng = np.random.default_rng(seed)
    xs = []
    base = rng.integers(0, 1 << 32, n, dtype=np.uint32)
    for v in range(lang.nv):
        r = rng.integers(0, 1 << 32, n, dtype=np.uint32)
        kind = rng.integers(0, 6, n)
        r = np.where(kind == 1, r & rng.integers(0, 1 << 32, n, dtype=np.uint32), r)
        r = np.where(kind == 2, r | rng.integers(0, 1 << 32, n, dtype=np.uint32), r)
        r = np.where(kind == 3, base + rng.integers(-2, 3, n).astype(np.uint32), r)
        r = np.where(kind == 4, (0 - base) + rng.integers(-2, 3, n).astype(np.uint32), r)
        r = np.where(kind == 5, np.uint32(1) << rng.integers(0, 32, n).astype(np.uint32), r) + \
            np.where(kind == 5, rng.integers(-2, 3, n).astype(np.uint32), np.uint32(0))
        xs.append(r.astype(np.uint32))
    with np.errstate(over="ignore"):
        d = np.flatnonzero(np_eval(lang, a, xs) != np_eval(lang, b, xs))
    return [int(x[d[0]]) for x in xs] if len(d) else None


def is_trivially(lang, ins, text):
    """Is the expression exactly the constant or variable named by `text`,
    for every input? Proved, not sampled."""
    from terms import VARS
    xs = [z3.BitVec(f"v{i}", 32) for i in range(lang.nv)]
    target = xs[VARS.index(text)] if text in VARS else z3.BitVecVal(int(text, 0) & M32, 32)
    s = z3.SolverFor("QF_BV")
    s.set("timeout", 20000)
    s.add(to_z3(lang, ins, xs) != target)
    return s.check() == z3.unsat
