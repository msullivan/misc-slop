#!/usr/bin/env python3
"""Turn census output into the site: rules, example seeds, finds.json, index.html.
Usage: build_site.py PREFIX NSEED   (expects PREFIX.rules.tsv, PREFIX.ships.x.tsv, PREFIX.osc.x.tsv, PREFIX.examples.bin)"""
import sys, json, struct, collections, os
prefix, nseed = sys.argv[1], int(sys.argv[2])
NR = 1 << 18
os.makedirs("site", exist_ok=True)

ships = collections.defaultdict(list)   # rule -> [a,b,p,count,seed,split,v,w,h,pat,minpop]
for line in open(prefix + ".ships.x.tsv"):
    f = line.rstrip("\n").split("\t")
    assert f[12] == "1", "unverified ship: " + line
    ships[int(f[0])].append([int(f[1]), int(f[2]), int(f[3]), int(f[4]), int(f[5]), int(f[6]), int(f[7]), int(f[8]), int(f[9]), f[11], int(f[10])])
osc = collections.defaultdict(list)     # rule -> [p,count,seed,split,v,w,h,pat]
for line in open(prefix + ".osc.x.tsv"):
    f = line.rstrip("\n").split("\t")
    assert f[12] == "1", "unverified oscillator: " + line
    osc[int(f[0])].append([int(f[3]), int(f[4]), int(f[5]), int(f[6]), int(f[7]), int(f[8]), int(f[9]), f[11]])
maxper = collections.defaultdict(int)
for line in open(prefix + ".osc.tsv"):
    if line[0] == "r": continue
    f = line.split("\t"); maxper[int(f[0])] = max(maxper[int(f[0])], int(f[1]))

totals = [0] * 6
out = bytearray()
nrules = 0
for line in open(prefix + ".rules.tsv"):
    if line[0] == "r": continue
    f = [int(x) for x in line.split("\t")]
    rule, c = f[0], f[1:7]
    assert rule == nrules and sum(c) == nseed
    nrules += 1
    for i in range(6): totals[i] += c[i]
    q = [min(65535, max(1, round(x * 65535 / nseed))) if x else 0 for x in c]
    out += struct.pack("<8H", *q, min(65535, max(maxper[rule], 1 if c[1] else 0)), min(65535, len(ships[rule])))
assert nrules == NR
import base64
open("site/rules.b64.txt", "wb").write(base64.b64encode(out))   # base64 so any static host serves it as text

# First seed that meets each fate, from examples.c: 6 u16 per rule.
ex = open(prefix + ".examples.bin", "rb").read()
assert len(ex) == NR * 12
for r in range(NR):
    for i in range(6):
        has = out[r * 16 + 2 * i] | out[r * 16 + 2 * i + 1]
        assert bool(has) == (ex[r * 12 + 2 * i: r * 12 + 2 * i + 2] != b"\xff\xff"), (r, i)
open("site/examples.b64.txt", "wb").write(base64.b64encode(ex))

def rs(rule):
    return "B" + "".join(str(i) for i in range(9) if rule >> i & 1) + "/S" + "".join(str(i) for i in range(9) if rule >> (9 + i) & 1)

with open("site/finds.json", "w") as fo:
    fo.write("[\n")
    first = True
    for rule in range(NR):
        s = sorted(ships.get(rule, []), key=lambda e: -e[3])
        o = sorted(osc.get(rule, []), key=lambda e: -e[0])[:3]
        if not s and not o: continue
        fo.write(("" if first else ",\n") + json.dumps([rule, s, o], separators=(",", ":")))
        first = False
    fo.write("\n]\n")

allships = [(r, e) for r, l in ships.items() for e in l]
def srow(r, e): return [r, e[0], e[1], e[2], e[3]]
vel = collections.Counter()
for r, e in allships: vel[(e[0], e[1], e[2])] += 1
notable = {
    "oblique": [srow(r, e) for r, e in sorted((x for x in allships if x[1][1] and x[1][0] != x[1][1]), key=lambda x: (-x[1][3], x[0]))][:200],
    "slow": [srow(r, e) for r, e in sorted(allships, key=lambda x: (x[1][0] / x[1][2], -x[1][2], x[0]))[:60]],
    "longship": [srow(r, e) for r, e in sorted(allships, key=lambda x: (-x[1][2], x[0]))[:60]],
    "longosc": [[r, e[0], e[1]] for r, e in sorted(((r, max(l)) for r, l in osc.items()), key=lambda x: (-x[1][0], x[0]))[:60]],
    "kinds": [[r, len(l)] for r, l in sorted(ships.items(), key=lambda x: (-len(x[1]), x[0]))[:60]],
}
meta = {"nseed": nseed, "jobs": nseed * NR, "totals": totals, "shipRules": sum(1 for l in ships.values() if l),
        "velocities": len(vel), "notable": notable}
page = open("page.html").read().replace("/*META*/null", json.dumps(meta, separators=(",", ":")))
open("site/artifact.html", "w").write(page)
open("site/index.html", "w").write('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<style>body{margin:0;font-size:14px}[hidden]{display:none!important}</style></head><body>\n' + page + "</body></html>\n")
print("rules with ships:", meta["shipRules"], "velocity classes:", len(vel), "totals:", totals)
for k, v in notable.items(): print(k, [(rs(x[0]), *x[1:]) for x in v[:6]])
for f in ("rules.b64.txt", "examples.b64.txt", "finds.json", "index.html"): print(f, os.path.getsize("site/" + f))
