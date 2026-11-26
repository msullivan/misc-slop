import random, sys
import sim, zoo
specs = sys.argv[1:]
fs = []
for s in specs:
    p, _, n = s.partition(":")
    fs.append((s.split("/")[-1], sim.load(p, n or "Opus")))
opps = [(c.__name__, (lambda c: lambda r: c(r))(c)) for c in zoo.ZOO]
games = 60
res = {}
for label, f in fs:
    rng = random.Random(1)
    row = []
    for name, g in opps + [("self", f)]:
        s = r = 0
        for _ in range(games):
            n = sim.draw_length(rng)
            a, b, _, _ = sim.play(f, g, n, rng)
            s += a; r += n
        row.append(s / r)
    res[label] = row
names = [o[0] for o in opps] + ["self"]
print(f"{'':20s}" + "".join(f"{l[:12]:>13s}" for l in res))
for i, n in enumerate(names):
    print(f"{n:20s}" + "".join(f"{res[l][i]:13.3f}" for l in res))
print(f"{'MEAN':20s}" + "".join(f"{sum(res[l])/len(res[l]):13.3f}" for l in res))
