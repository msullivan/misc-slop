#!/usr/bin/env python3
"""Turn the analysis into the JSON the page reads.

    report.py OUT.json ID=RUNDIR [ID=RUNDIR ...]

For each census and compiler: how often the compiler's output for an
expression is beaten by its own output for an equivalent one, and a list of
the smallest, clearest examples. Every example is recompiled on its own,
run, and proved equivalent before it goes in.
"""
import json
import multiprocessing as mp
import re
import sys
from collections import defaultdict

import numpy as np

import compile as C
from asmcost import cost, BRANCHY, FAILED
from analyze import WRONG
from distill import Distilled, dominated
from prove import prove, is_trivially
from terms import Lang, infix, c_expr, go_expr, wat_expr, swap_vars, trivial, VARS

EXAMPLES = 400
REGRESSIONS = 120
AUDIT = 1500


def family_of(name):
    return name.rsplit("-", 1)[0]


def version_key(name):
    return [int(x) for x in re.findall(r"\d+", name.rsplit("-", 1)[1])]


def show(lang, ins, simplify=False, kind="c"):
    """-> (display text, C expression). With simplify, an expression that
    is really a constant or a bare variable is shown as that."""
    t = trivial(lang, ins) if simplify else None
    if t is not None and not is_trivially(lang, ins, t):
        t = None  # looked constant on a few inputs, isn't
    if t is not None:
        if t in VARS:
            return t, (f"(local.get {VARS.index(t)})" if kind == "wat" else t)
        v = int(t, 0) & 0xFFFFFFFF
        return t, {"c": f"{v}u", "go": str(v), "wat": f"(i32.const {v - (1 << 32) if v >> 31 else v})"}[kind]
    return infix(lang, ins), {"c": c_expr, "go": go_expr, "wat": wat_expr}[kind](lang, ins)


def nicest(D, c, w):
    """Among the expressions equivalent to w that compiler c compiled exactly
    as well, the shortest to read."""
    cen, x = D.cen, D.data[c]
    k = cen.cls[w]
    lo = cen.starts[k]
    members = cen.order[lo:lo + cen.cls_size[k]]
    same = members[(x["u"][members] == x["u"][w]) & (x["d"][members] == x["d"][w])
                   & (cen.fp[members] == cen.fp[w])]
    same = same[cen.size[same] == cen.size[same].min()][:200]
    return int(min(same, key=lambda i: (len(infix(D.lang, D.lang.unpack(cen.packed[i]))), int(i))))


HARNESS = r"""
#include <stdint.h>
#include <stdio.h>
__attribute__((noinline)) uint32_t f(%s) { return %s; }
int main(void) { uint32_t a[4] = {0}; while (scanf(%s) == %d) printf("%%u\n", f(%s)); return 0; }
"""


def miscompiles(lang, cen, comp, idx):
    """For each expression the compiler got wrong: recompile it alone and
    find an input where the result differs from what the expression means."""
    import os, shutil, subprocess, tempfile
    from terms import evaluate
    kind, cmd = C.COMPILERS[comp]
    out = []
    if kind != "c":
        return out
    nv = lang.nv
    for i in idx:
        t = lang.unpack(cen.packed[i])
        d = tempfile.mkdtemp(prefix="pc_", dir="/dev/shm")
        try:
            with open(f"{d}/a.c", "w") as f:
                f.write(HARNESS % (", ".join(f"uint32_t {VARS[v]}" for v in range(nv)), c_expr(lang, t),
                                   '"' + " ".join(["%u"] * nv) + '"' + "".join(f", &a[{v}]" for v in range(nv)), nv,
                                   ", ".join(f"a[{v}]" for v in range(nv))))
            rec = dict(e=infix(lang, t), ce=c_expr(lang, t), s=len(t), levels=[])
            stdin = "\n".join(" ".join(map(str, row)) for row in _INPUTS).encode()
            for opt in ("-O0", "-O1", "-O2"):
                subprocess.run(cmd + [opt, "a.c", "-o", "a"], cwd=d, check=True, capture_output=True)
                got = [int(x) for x in subprocess.run([f"{d}/a"], input=stdin, capture_output=True).stdout.split()]
                for row, g in zip(_INPUTS, got):
                    want = evaluate(lang, t, row)
                    if g != want:
                        rec["levels"].append(opt)
                        rec.update(input=row, want=want, got=g)
                        break
            if rec["levels"]:
                out.append(rec)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return out


def _prove(job):
    a, b = job
    return prove(_LANG, a, b, timeout_ms=30000)[0:2]


def _compile(job):
    name, terms = job
    bodies, fps = C.compile_split(name, _LANG, _INPUTS, terms, True)
    return bodies, fps


def build_run(rid, run, pool_n=48):
    global _LANG, _INPUTS
    D = Distilled(run)
    cen, lang = D.cen, D.lang
    _LANG = lang
    _INPUTS = [list(map(int, l.split())) for l in open(f"{run}/inputs.txt")]
    comps = sorted(D.comps, key=lambda c: (family_of(c), version_key(c)))
    meta = json.load(open(f"{run}/meta.json"))
    sizes = list(range(1, lang.k + 1))
    beaten = D.best_known()
    missmat = np.stack([D.data[c]["miss"] for c in comps])
    out = dict(id=rid, vars=lang.nv, consts=lang.consts, shifts=lang.shifts, ops=meta["ops"],
               levels=meta["levels"], n=int(cen.n), classes=int(len(cen.starts)),
               compilers=[], h2h=[], regressions=[])

    picks = {}  # compiler -> list of (i, w)
    for c in comps:
        x = D.data[c]
        u, d = x["u"], x["d"]
        stats = []
        for k in sizes:
            m = cen.size == k
            stats.append(dict(
                size=k, n=int(m.sum()),
                hard=int((x["hard"] & m).sum()), sched=int((x["miss"] & ~x["hard"] & m).sum()),
                root_hard=int((x["root"] & x["hard"] & m).sum()),
                root_sched=int((x["root"] & ~x["hard"] & m).sum()),
                branchy=int(((u == BRANCHY) & m).sum()), failed=int(((u == FAILED) & m).sum()),
                wrong=int(((u == WRONG) & m).sum()),
                beaten=int((beaten[c] & m).sum())))
        roots = np.flatnonzero(x["root"])
        w = x["wit"][roots]
        gain = (u[roots] - u[w]) * 4 + (d[roots] - d[w])
        order = np.lexsort((roots, -gain, cen.size[roots], ~x["hard"][roots]))
        seen, chosen = set(), []
        fam_count = defaultdict(int)
        for i in roots:
            fam_count[int(D.skel[i])] += 1
        for i in roots[order]:
            sk = int(D.skel[i])
            if sk in seen:
                continue
            seen.add(sk)
            chosen.append(int(i))
            if len(chosen) >= EXAMPLES:
                break
        picks[c] = [(i, nicest(D, c, int(x["wit"][i])), fam_count[int(D.skel[i])]) for i in chosen]
        out["compilers"].append(dict(name=c, kind=C.COMPILERS[c][0], stats=stats,
                                     wrong=miscompiles(lang, cen, c, np.flatnonzero(u == WRONG)), roots=int(len(roots)),
                                     families=len(fam_count), examples=[]))

    # Head to head: same source, whose code is strictly better.
    for a in comps:
        row = []
        for b in comps:
            A, B = D.data[a], D.data[b]
            ok = (A["u"] < 90) & (B["u"] < 90)
            row.append(int((dominated(B["u"], B["d"], A["u"], A["d"]) & ok).sum()))
        out["h2h"].append(row)

    # Regressions: the newer release of a compiler does worse than the one
    # before it on the very same source.
    reg_picks = []
    fams = defaultdict(list)
    for c in comps:
        fams[family_of(c)].append(c)
    for fam, cs in fams.items():
        for old, new in zip(cs, cs[1:]):
            A, B = D.data[old], D.data[new]
            ok = (A["u"] < 90) & (B["u"] < 90)
            worse = np.flatnonzero(dominated(B["u"], B["d"], A["u"], A["d"]) & ok)
            gain = (B["u"][worse] - A["u"][worse]) * 4 + (B["d"][worse] - A["d"][worse])
            order = np.lexsort((worse, -gain, cen.size[worse]))
            seen, chosen = set(), []
            for i in worse[order]:
                sk = int(D.skel[i])
                if sk not in seen:
                    seen.add(sk)
                    chosen.append(int(i))
                    if len(chosen) >= REGRESSIONS:
                        break
            better = int((dominated(A["u"], A["d"], B["u"], B["d"]) & ok).sum())
            reg_picks.append((old, new, chosen))
            out["regressions"].append(dict(old=old, new=new, worse=int(len(worse)), better=better, examples=[]))

    # Audit: the classes come from testing, not proof. Try to prove a
    # random sample of (expression, better equivalent) pairs.
    rng = np.random.default_rng(7)
    audit = []
    for c in comps[-2:] + comps[:1]:
        m = np.flatnonzero(D.data[c]["miss"])
        for i in rng.choice(m, min(AUDIT, len(m)), replace=False):
            w = int(D.data[c]["wit"][i])
            tw = lang.unpack(cen.packed[w])
            audit.append((lang.unpack(cen.packed[i]), swap_vars(lang, tw) if cen.fp[i] != cen.fp[w] else tw))

    # Recompile every example on its own and prove the pair equal.
    ctx = mp.get_context("fork")
    with ctx.Pool(pool_n) as pool:
        jobs, proofs = [], []
        for c in comps:
            terms = []
            for i, w, _ in picks[c]:
                t = lang.unpack(cen.packed[i])
                tw = lang.unpack(cen.packed[w])
                if cen.fp[i] != cen.fp[w]:
                    tw = swap_vars(lang, tw)
                terms += [t, tw]
                proofs.append((t, tw))
            jobs.append((c, terms))
        for old, new, chosen in reg_picks:
            terms = [lang.unpack(cen.packed[i]) for i in chosen]
            jobs.append((old, terms))
            jobs.append((new, terms))
        compiled = pool.map(_compile, jobs, chunksize=1)
        proved = pool.map(_prove, proofs, chunksize=4)
        audited = pool.map(_prove, audit, chunksize=4)
    tally = lambda rs: dict(z3=sum(1 for s, h in rs if h == "z3"),
                            polynomial=sum(1 for s, h in rs if h == "polynomial"),
                            unproved=sum(1 for s, h in rs if s == "unknown"),
                            refuted=sum(1 for s, h in rs if s == "refuted"))
    out["audit"] = tally(audited)
    for (a, b), (st, cex) in zip(audit, audited):
        if st == "refuted":
            print("  audit refuted:", infix(lang, a), " != ", infix(lang, b), "at", cex, file=sys.stderr)

    pi = 0
    dropped = defaultdict(int)
    for ci, c in enumerate(comps):
        bodies, fps = compiled[ci]
        terms = jobs[ci][1]
        for k, (i, w, famn) in enumerate(picks[c]):
            t, tw = terms[2 * k], terms[2 * k + 1]
            status, how = proved[pi]
            pi += 1
            ba, bw = bodies[2 * k], bodies[2 * k + 1]
            ca, cw = cost(ba), cost(bw)
            if fps[2 * k] != fps[2 * k + 1] or status == "refuted":
                dropped["not equivalent"] += 1
                continue
            if not (cw[0] <= ca[0] and cw[1] <= ca[1] and cw[:2] != ca[:2]) or ca[0] >= 90:
                dropped["not reproduced standalone"] += 1
                continue
            kind = C.COMPILERS[c][0]
            te, ce = show(lang, t, kind=kind)
            tw_, cw_ = show(lang, tw, simplify=True, kind=kind)
            out["compilers"][ci]["examples"].append(dict(
                e=te, ce=ce, a=ba, c=list(ca[:2]), w=tw_, cw=cw_, wa=bw, wc=list(cw[:2]),
                s=int(cen.size[i]), fam=famn, proof=(how if status == "proved" else "tested"),
                also=[cj for cj in range(len(comps)) if cj != ci and missmat[cj, i]]))
    for ri, (old, new, chosen) in enumerate(reg_picks):
        bo, _ = compiled[len(comps) + 2 * ri]
        bn, _ = compiled[len(comps) + 2 * ri + 1]
        for k, i in enumerate(chosen):
            co, cn = cost(bo[k]), cost(bn[k])
            if not (co[0] <= cn[0] and co[1] <= cn[1] and co[:2] != cn[:2]) or cn[0] >= 90:
                dropped["regression not reproduced"] += 1
                continue
            te, ce = show(lang, lang.unpack(cen.packed[i]), kind=C.COMPILERS[new][0])
            out["regressions"][ri]["examples"].append(dict(
                e=te, ce=ce, s=int(cen.size[i]), a=bn[k], c=list(cn[:2]), wa=bo[k], wc=list(co[:2])))
    out["dropped"] = dict(dropped)
    out["proofs"] = tally(proved)
    print(rid, "examples:", sum(len(c["examples"]) for c in out["compilers"]), "dropped:", dict(dropped),
          "proofs:", out["proofs"], "audit:", out["audit"], file=sys.stderr)
    return out


def main():
    outp = sys.argv[1]
    runs = [build_run(*a.split("=", 1)) for a in sys.argv[2:]]
    with open(outp, "w") as f:
        json.dump(dict(runs=runs), f, separators=(",", ":"))


if __name__ == "__main__":
    main()
