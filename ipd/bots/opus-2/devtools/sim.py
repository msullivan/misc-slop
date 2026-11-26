import random
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, "/home/sully/src/misc-slop/ipd/bots/opus-2")
from strategy import Bot  # noqa

PAY = {("C", "C"): 3, ("C", "D"): 0, ("D", "C"): 5, ("D", "D"): 1}


class Fn:
    """opponent from fn(my_hist, their_hist, rng, state) -> move"""
    def __init__(self, fn, rng):
        self.fn, self.rng, self.me, self.op, self.st = fn, rng, [], [], {}

    def move(self):
        m = self.fn(self.me, self.op, self.rng, self.st)
        self.me.append(m)
        return m

    def observe(self, o):
        self.op.append(o)


def tft(me, op, r, s): return op[-1] if op else "C"
def tf2t(me, op, r, s): return "D" if op[-2:] == ["D", "D"] else "C"
def allc(me, op, r, s): return "C"
def alld(me, op, r, s): return "D"
def rnd(me, op, r, s): return r.choice("CD")
def rnd80(me, op, r, s): return "C" if r.random() < .8 else "D"
def grim(me, op, r, s): return "D" if "D" in op else "C"
def wsls(me, op, r, s):
    if not op: return "C"
    return me[-1] if op[-1] == "C" else ("D" if me[-1] == "C" else "C")
def gtft(me, op, r, s):
    if not op or op[-1] == "C": return "C"
    return "C" if r.random() < 1/3 else "D"
def joss(me, op, r, s):
    m = tft(me, op, r, s)
    return "D" if m == "C" and r.random() < .1 else m
def alt(me, op, r, s): return "CD"[len(me) % 2]
def stft(me, op, r, s): return op[-1] if op else "D"
def prober(me, op, r, s):
    n = len(me)
    if n < 3: return "DCC"[n]
    if op[1] == "C" and op[2] == "C": return "D"
    return op[-1]
def periodic_prober(me, op, r, s):
    if op and op[-1] == "D": return "D"
    return "D" if r.random() < .03 else "C"
def gradual(me, op, r, s):
    s.setdefault("punish", 0); s.setdefault("calm", 0); s.setdefault("nd", 0)
    if not op: return "C"
    if s["punish"] > 0:
        s["punish"] -= 1
        if s["punish"] == 0: s["calm"] = 2
        return "D"
    if s["calm"] > 0:
        s["calm"] -= 1
        return "C"
    if op[-1] == "D":
        s["nd"] += 1
        s["punish"] = s["nd"] - 1
        if s["punish"] == 0: s["calm"] = 2
        return "D"
    return "C"
def threshold_grim(me, op, r, s):
    if len(op) >= 10 and op.count("D") / len(op) > .1: return "D"
    return op[-1] if op else "C"
def exploit_allc(me, op, r, s):
    n = len(me)
    if n == 20: return "D"
    if n > 21 and op[21] == "C":
        if "D" in op[22:]: return op[-1]
        return "D" if n % 3 == 0 else "C"
    return op[-1] if op else "C"
def tit2(me, op, r, s): return "D" if "D" in op[-2:] else "C"
def grim3(me, op, r, s): return "D" if op.count("D") >= 3 else tft(me, op, r, s)
def luna(me, op, r, s):
    # WSLS with a probe at round 2; gives up (AllD) if we defect a lot
    n = len(me)
    if n == 0: return "C"
    if n == 2: return "D"
    if s.get("alld") or (n >= 20 and op[-10:].count("D") >= 6):
        s["alld"] = True
        return "D"
    return me[-1] if op[-1] == "C" else ("D" if me[-1] == "C" else "C")
def terra(me, op, r, s):
    n = len(me)
    if n >= 12 and (n - 12) % 60 in (0, 1): return "D"
    if n >= 2 and op[-1] == "D" and me[-2] == "C": return "D"
    return "C"
def haiku(me, op, r, s):
    n = len(me)
    if n in (1, 2, 12): return "D"
    return op[-1] if op else "C"
def sonnet(me, op, r, s):
    n = len(me)
    if n in (26, 27): return "D"
    return op[-1] if op else "C"
def selfbot(me, op, r, s):
    if "b" not in s: s["b"] = Bot(rng=r)
    b = s["b"]
    if op: b.observe(op[-1])
    return b.move()


OPP = dict(tft=tft, tf2t=tf2t, allc=allc, alld=alld, rnd=rnd, rnd80=rnd80,
           grim=grim, wsls=wsls, gtft=gtft, joss=joss, alt=alt, stft=stft,
           prober=prober, pprober=periodic_prober, gradual=gradual,
           thgrim=threshold_grim, expl=exploit_allc, tit2=tit2, grim3=grim3,
           luna=luna, terra=terra, haiku=haiku, sonnet=sonnet, self=selfbot)


def length(r):
    n = 1
    while n < 2000 and r.random() >= 1 / 200:
        n += 1
    return n


def play(a, b, n):
    sa = sb = 0
    for _ in range(n):
        x, y = a.move(), b.move()
        a.observe(y); b.observe(x)
        sa += PAY[(x, y)]; sb += PAY[(y, x)]
    return sa, sb


def main(games=200, show=None, **kw):
    r = random.Random(1)
    tot_p = tot_n = 0
    for name, fn in OPP.items():
        if show and name != show:
            continue
        ps = pt = ns = 0
        for g in range(games):
            n = length(r)
            a = Bot(rng=random.Random(r.random()), **kw)
            b = Fn(fn, random.Random(r.random()))
            x, y = play(a, b, n)
            ps += x; pt += y; ns += n
            if show:
                print("".join(a.me[:150])); print("".join(b.me[:150])); print()
        print(f"{name:8s} me {ps/ns:.3f}  them {pt/ns:.3f}")
        tot_p += ps; tot_n += ns
    print(f"overall {tot_p/tot_n:.4f}")


if __name__ == "__main__":
    kw = {}
    if len(sys.argv) > 1: kw["probe_prob"] = float(sys.argv[1])
    if len(sys.argv) > 2: kw["show"] = sys.argv[2]; kw["games"] = 3
    main(**kw)
