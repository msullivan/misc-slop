#!/usr/bin/env python3
"""Split report.py's JSON into the files the page fetches.

    build_site.py REPORT.json SITE_DIR

summary.json              everything but the examples
ex-RUN-COMPILER.json      one compiler's examples, one record per line
reg-RUN.json              regression examples between releases
"""
import json
import os
import sys

rep = json.load(open(sys.argv[1]))
site = sys.argv[2]
os.makedirs(site, exist_ok=True)


def lines(path, records):
    with open(path, "w") as f:
        f.write("[\n" + ",\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n]\n")


for run in rep["runs"]:
    for c in run["compilers"]:
        ex = c.pop("examples")
        c["nexamples"] = len(ex)
        lines(f"{site}/ex-{run['id']}-{c['name']}.json", ex)
    regs = []
    for r in run["regressions"]:
        for e in r.pop("examples"):
            regs.append(dict(e, old=r["old"], new=r["new"]))
    lines(f"{site}/reg-{run['id']}.json", regs)
with open(f"{site}/summary.json", "w") as f:
    json.dump(rep, f, separators=(",", ":"))
print("wrote", site, sum(os.path.getsize(f"{site}/{x}") for x in os.listdir(site)) // 1024, "KB")
