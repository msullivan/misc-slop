import importlib.util
import random
import sys

import zoo

PAY = {("C", "C"): 3, ("C", "D"): 0, ("D", "C"): 5, ("D", "D"): 1}


def load(path, name="Opus"):
    spec = importlib.util.spec_from_file_location("strat_" + str(abs(hash(path))), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = getattr(mod, name)
    return lambda rng: cls()


def draw_length(rng):
    n = 1
    while n < 2000 and rng.random() >= 1 / 200:
        n += 1
    return n


def play(fa, fb, n, rng):
    a, b = fa(rng), fb(rng)
    sa = sb = 0
    ma = mb = ""
    for _ in range(n):
        x, y = a.move(), b.move()
        a.observe(y); b.observe(x)
        sa += PAY[(x, y)]; sb += PAY[(y, x)]
        ma += x; mb += y
    return sa, sb, ma, mb


def main():
    paths = sys.argv[1:] or ["../strategy.py"]
    games = 40
    mine = [(p.split("/")[-1] if len(paths) > 1 else "opus", load(p)) for p in paths]
    for label, f in mine:
        rng = random.Random(1)
        tot = rds = 0
        rows = []
        opps = [(c.__name__, (lambda c: lambda r: c(r))(c)) for c in zoo.ZOO] + [("self", f)]
        for name, g in opps:
            s = o = r = 0
            for _ in range(games):
                n = draw_length(rng)
                a, b, _, _ = play(f, g, n, rng)
                s += a; o += b; r += n
            rows.append((name, s / r, o / r))
            tot += s; rds += r
        print(f"== {label}: overall {tot / rds:.4f}")
        for name, a, b in rows:
            print(f"  {name:20s} me {a:.3f}  them {b:.3f}")


if __name__ == "__main__":
    main()
