#!/usr/bin/env python3
"""Turn evolution archives into the files the web page loads.

usage: tools/pack.py OUT_DIR task=archive.json [task=archive.json ...]

Writes OUT_DIR/<task>.json for each archive and OUT_DIR/index.json listing
them. Existing files for tasks not named are kept and stay in the index.
"""
import json
import os
import sys

# Evaluation details the page never reads.
DROP_EVAL = {"joint_err", "straightness", "kick", "valid"}


def slim_elite(e):
    e = dict(e)
    e["eval"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in e["eval"].items() if k not in DROP_EVAL}
    e["fitness"] = round(e["fitness"], 4)
    return e


def main():
    out_dir, *pairs = sys.argv[1:]
    os.makedirs(out_dir, exist_ok=True)
    for pair in pairs:
        task, path = pair.split("=", 1)
        with open(path) as f:
            arch = json.load(f)
        assert arch["task"] == task, (arch["task"], task)
        families = [
            {"evals": fam["evals"], "elites": [slim_elite(e) for e in fam["elites"]]}
            for fam in arch.get("families", [])
        ]
        if families:
            # The merged map just points into the families.
            merged = [{"family": e["family"], "cell": e["cell"]} for e in arch["elites"]]
        else:
            merged = [slim_elite(e) for e in arch["elites"]]
        out = {
            "evals": arch["evals"],
            "seed": arch["seed"],
            "dims": arch["dims"],
            "elites": merged,
            "families": families,
            "lineages": arch["lineages"],
        }
        dest = os.path.join(out_dir, f"{task}.json")
        with open(dest, "w") as f:
            json.dump(out, f, separators=(",", ":"))
        n_fam = len(out["families"])
        print(f"{dest}: {len(out['elites'])} cells, {n_fam} families, {os.path.getsize(dest) / 1e6:.2f} MB")
    order = ["walk", "sprint", "rough", "chase", "shove", "swim", "jump"]
    have = [t for t in order if os.path.exists(os.path.join(out_dir, f"{t}.json"))]
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump({"tasks": have}, f)
    print("index:", ", ".join(have))


if __name__ == "__main__":
    main()
