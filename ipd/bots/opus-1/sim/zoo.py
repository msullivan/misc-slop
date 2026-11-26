"""A zoo of opponent strategies.  Each is a class with move() / observe()."""
import random


class Base:
    def __init__(self, rng):
        self.rng = rng
        self.my = []
        self.op = []

    def move(self):
        m = self.decide()
        self.my.append(m)
        return m

    def observe(self, o):
        self.op.append(o)


class AllC(Base):
    def decide(self): return "C"


class AllD(Base):
    def decide(self): return "D"


class Rand(Base):
    p = 0.5
    def decide(self): return "C" if self.rng.random() < self.p else "D"


class Rand80(Rand):
    p = 0.8


class Rand95(Rand):
    p = 0.95


class TFT(Base):
    def decide(self): return self.op[-1] if self.op else "C"


class STFT(Base):
    def decide(self): return self.op[-1] if self.op else "D"


class TF2T(Base):
    def decide(self):
        return "D" if self.op[-2:] == ["D", "D"] else "C"


class GTFT(Base):
    def decide(self):
        if not self.op or self.op[-1] == "C":
            return "C"
        return "C" if self.rng.random() < 0.1 else "D"


class Grim(Base):
    def decide(self): return "D" if "D" in self.op else "C"


class Pavlov(Base):
    def decide(self):
        if not self.op:
            return "C"
        return "C" if self.my[-1] == self.op[-1] else "D"


class Joss(Base):
    def decide(self):
        m = self.op[-1] if self.op else "C"
        if m == "C" and self.rng.random() < 0.1:
            return "D"
        return m


class Joss2(Base):
    """TFT that defects unprovoked 3% of the time."""
    def decide(self):
        m = self.op[-1] if self.op else "C"
        if m == "C" and self.rng.random() < 0.03:
            return "D"
        return m


class Alternator(Base):
    def decide(self): return "CD"[len(self.my) % 2]


class CCD(Base):
    def decide(self): return "CCD"[len(self.my) % 3]


class Gradual(Base):
    def __init__(self, rng):
        super().__init__(rng)
        self.n = 0
        self.queue = []

    def decide(self):
        if self.queue:
            return self.queue.pop(0)
        if self.op and self.op[-1] == "D":
            self.n += 1
            self.queue = ["D"] * (self.n - 1) + ["C", "C"]
            return "D"
        return "C"


class Tester(Base):
    """Axelrod's Tester: D first; if opponent retaliates, TFT; else C C D."""
    def __init__(self, rng):
        super().__init__(rng)
        self.tft = False

    def decide(self):
        t = len(self.my)
        if t == 0:
            return "D"
        if "D" in self.op[1:3] or (t >= 2 and self.op[1] == "D"):
            self.tft = True
        if self.tft:
            return self.op[-1]
        return "D" if t % 3 == 0 else "C"


class Detective(Base):
    def decide(self):
        t = len(self.my)
        if t < 4:
            return "CDCC"[t]
        if "D" in self.op[:4]:
            return self.op[-1]
        return "D"


class Prober(Base):
    """Cooperate; defect at round 10; if no retaliation within 2, defect every 3rd."""
    def __init__(self, rng):
        super().__init__(rng)
        self.exploit = None

    def decide(self):
        t = len(self.my)
        if t == 10:
            return "D"
        if t == 13 and self.exploit is None:
            self.exploit = "D" not in self.op[11:13]
        if self.exploit:
            if "D" in self.op[-2:]:
                self.exploit = False
                return "D"
            return "D" if t % 3 == 0 else "C"
        return self.op[-1] if self.op else "C"


class RandomProber(Base):
    """TFT but defects with 5% prob; if not punished, raises the rate."""
    def __init__(self, rng):
        super().__init__(rng)
        self.rate = 0.05
        self.last_probe = None

    def decide(self):
        t = len(self.my)
        if self.last_probe is not None and t == self.last_probe + 2:
            if self.op[self.last_probe + 1] == "C":
                self.rate = min(0.5, self.rate * 2)
            else:
                self.rate = 0.05
        if self.op and self.op[-1] == "D" and not (self.last_probe is not None and t <= self.last_probe + 2):
            return "D"
        if self.rng.random() < self.rate:
            self.last_probe = t
            return "D"
        return "C"


class Extort2(Base):
    def decide(self):
        if not self.op:
            return "C"
        p = {("C", "C"): 8 / 9, ("C", "D"): 0.5, ("D", "C"): 1 / 3, ("D", "D"): 0}[(self.my[-1], self.op[-1])]
        return "C" if self.rng.random() < p else "D"


class OverPunisher(Base):
    """Each opponent D gets two D's back."""
    def __init__(self, rng):
        super().__init__(rng)
        self.owed = 0

    def decide(self):
        if self.op and self.op[-1] == "D":
            self.owed += 2
        if self.owed:
            self.owed -= 1
            return "D"
        return "C"


class OverPunisherProber(OverPunisher):
    def decide(self):
        if len(self.my) == 5:
            if self.op and self.op[-1] == "D":
                self.owed += 2
            return "D"
        return super().decide()


class SoftMajority(Base):
    def decide(self):
        return "C" if self.op.count("C") >= self.op.count("D") else "D"


class HardMajority(Base):
    def decide(self):
        return "D" if self.op.count("D") >= self.op.count("C") else "C"


class Adaptive(Base):
    """Model-based: estimates conditional coop probabilities and best-responds."""
    def decide(self):
        t = len(self.my)
        if t < 6:
            return "CCCCDC"[t] if False else "C"
        c1 = n1 = c0 = n0 = 1
        for s in range(max(0, t - 50), t - 1):
            if self.my[s] == "C":
                n1 += 1; c1 += self.op[s + 1] == "C"
            else:
                n0 += 1; c0 += self.op[s + 1] == "C"
        p1 = c1 / (n1 + 1); p0 = c0 / (n0 + 1)
        if 1 + 4 * p0 > 3 * p1:
            return "D"
        return self.op[-1]


class LateDefector(Base):
    """TFT but defects permanently after round 150."""
    def decide(self):
        if len(self.my) >= 150:
            return "D"
        return self.op[-1] if self.op else "C"


class FirmButFair(Base):
    def decide(self):
        if not self.op:
            return "C"
        if self.my[-1] == "C" and self.op[-1] == "D":
            return "D"
        if self.my[-1] == "D" and self.op[-1] == "D":
            return "C"
        return "C"


class ContriteTFT(Base):
    """TFT that doesn't count a D that answered its own D."""
    def decide(self):
        if not self.op or self.op[-1] == "C":
            return "C"
        if len(self.my) >= 2 and self.my[-2] == "D":
            return "C"
        return "D"


class Forgiver(Base):
    """Cooperates, ignores single defections, retaliates only after 3 in last 10."""
    def decide(self):
        return "D" if self.op[-10:].count("D") >= 3 else "C"


class Exploiter(Base):
    """Probe early; if opponent forgives, defect every other round; TFT otherwise."""
    def __init__(self, rng):
        super().__init__(rng)
        self.state = "probe"

    def decide(self):
        t = len(self.my)
        if t == 3:
            return "D"
        if t == 6 and self.state == "probe":
            self.state = "exploit" if self.op[4] == "C" and self.op[5] == "C" else "tft"
        if self.state == "exploit":
            if self.op[-3:].count("D") >= 2:
                self.state = "tft"
            else:
                return "CD"[t % 2]
        return self.op[-1] if self.op else "C"


ZOO = [AllC, AllD, Rand, Rand80, Rand95, TFT, STFT, TF2T, GTFT, Grim, Pavlov,
       Joss, Joss2, Alternator, CCD, Gradual, Tester, Detective, Prober,
       RandomProber, Extort2, OverPunisher, OverPunisherProber, SoftMajority,
       HardMajority, Adaptive, LateDefector, FirmButFair, ContriteTFT,
       Forgiver, Exploiter]


# ---- shapes seen in round 1 (emulations from my own transcripts only)
class Luna1(Base):
    """C iff my last two moves were C then D (first two rounds C)."""
    def decide(self):
        t = len(self.my)
        if t < 2:
            return "C"
        return "C" if self.op[-2:] == ["C", "D"] else "D"


class TerraLike(Base):
    """TFT that defects twice every 60 rounds starting at round 12."""
    def decide(self):
        t = len(self.my)
        if t >= 12 and (t - 12) % 60 in (0, 1):
            return "D"
        if t >= 12 and (t - 12) % 60 in (2, 3):
            return "C"
        return self.op[-1] if self.op else "C"


class HaikuLike(Base):
    """Opens C D D C, TFT afterwards, one more probe at 12."""
    def decide(self):
        t = len(self.my)
        if t < 4:
            return "CDDC"[t]
        if t == 12:
            return "D"
        return self.op[-1]


class SonnetLike(Base):
    def decide(self):
        t = len(self.my)
        if t in (3, 4):
            return "D"
        if t in (5, 6):
            return "C" if t == 5 else self.op[-1]
        return self.op[-1] if self.op else "C"


ZOO += [Luna1, TerraLike, HaikuLike, SonnetLike]


class Haiku2Like(Base):
    """Round-2 haiku as seen: opens C D D C D, probes at 12 and 22, and
    does not answer a punishment of a probe; TFT otherwise."""
    def decide(self):
        t = len(self.my)
        if t < 5:
            return "CDDCD"[t]
        if t in (12, 22):
            return "D"
        if t - 1 in (12, 22) or t - 2 in (12, 22):
            return "C"
        return self.op[-1]


ZOO += [Haiku2Like]
