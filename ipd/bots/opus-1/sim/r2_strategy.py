"""opus-1 strategy.  See NOTES.md for the reasoning.

Layers, highest priority first:

0. Model mode (round 2).  When my recent mean is poor, learn their reply as a
   function of (my last two moves, their last move) and play the optimal
   policy for that model; drop back to the layers below once play is calm.

1. Overtures.  When the opponent has defected several rounds running (a
   mutual-defection lock, or an always-defector) play C twice; the wait before
   the next overture doubles each time one is refused.
2. Unresponsive-opponent detector.  Over a recent window estimate
     p1 = P(they cooperate next | I cooperated)
     p0 = P(they cooperate next | I defected)
   Always cooperating is worth about 3*p1 a round, always defecting about
   1 + 4*p0.  When defecting is clearly better (random, always-defect, bots
   that ignore what I do) defect.
3. Probe-and-exploit.  In a minority of matches, after a long run of mutual
   cooperation, defect once.  If they do not retaliate, defect once more; if
   that also goes unanswered they are a pushover, and I defect periodically,
   more often while it stays unanswered, backing off when it is answered.
4. Base: tit-for-tat, except that a D which follows shortly after one of my
   own D's (one that hit their C) is taken as a retaliation and absorbed
   instead of echoed.  Absorbing is rationed: when absorbing fails to restore
   cooperation, the ration shrinks.
"""

import os
import random

WINDOW = 80
ENTER_MARGIN = 0.4
EXIT_MARGIN = 0.0
MIN_ROUND = 10
MIN_N = 4
UNPROVOKED_MIN = 0.15   # detector needs them to defect this often unprovoked
UNPROVOKED_OPP = 20     # ... out of at least this many chances

# model mode: when the match is going badly, learn their reply as a function
# of (my last two moves, their last move) and plan against that model.
BAD_WINDOW = 20
BAD_ENTER = 1.6         # mean points/round over BAD_WINDOW to switch on
GOOD_EXIT = 2.6         # ... and to switch back to the base strategy,
CALM_EXIT = 6           # once this many rounds running were mutual C
MODEL_DECAY = 0.99
GAMMA = 0.97

TOL_PER_HIT = 2         # retaliations I absorb per D of mine that hit a C
TOL_WINDOW = 5          # ... if they come within this many rounds of it
ABSORB_CREDIT = 2.0     # a failed absorb costs 1, a successful one earns 0.5

LOCK_WAIT = 4           # opponent D's in a row before an overture
LOCK_WAIT_MAX = 64
OFFER_LEN = 2

PROBE_P = 0.0           # fraction of matches in which I probe (r1: 0.2)
PROBE_FROM, PROBE_TO = 40, 100
PROBE_CALM = 20         # rounds of unbroken mutual cooperation before probing
EXPLOIT_GAPS = [5, 4, 3, 2, 1]
EXPLOIT_STEP = 3        # unanswered exploit D's before trying a shorter gap


class Opus:
    def __init__(self, rng=None):
        self.rng = rng or random.Random(os.urandom(16))
        self.my = []
        self.op = []
        self.mode = "normal"
        self.tolerance = 0
        self.last_hit = -100
        self.absorb_credit = ABSORB_CREDIT
        self.absorb_log = []
        self.offer_left = 0
        self.lock_wait = LOCK_WAIT
        self.dry = 0
        # probe / exploit machine
        self.probe_at = (self.rng.randint(PROBE_FROM, PROBE_TO)
                         if self.rng.random() < PROBE_P else None)
        self.stage = "wait" if self.probe_at is not None else "off"
        self.probes = []
        self.level = 0
        self.level_cap = len(EXPLOIT_GAPS) - 1
        self.unanswered = 0
        self.next_exploit = None
        self.apology = 0
        self.points = []
        self.model_on = False
        self.counts = {}             # (m2, m1, o1) -> [weight C, weight D]

    # ------------------------------------------------------------ helpers
    def advantage(self):
        """Estimated (always-defect value) - (always-cooperate value)."""
        my, op = self.my, self.op
        n = len(op)
        c1 = n1 = c0 = n0 = 0
        for s in range(max(0, n - 1 - WINDOW), n - 1):
            if my[s] == "C":
                n1 += 1
                c1 += op[s + 1] == "C"
            else:
                n0 += 1
                c0 += op[s + 1] == "C"
        if n1 < MIN_N or n0 < MIN_N:
            return None
        # Only an opponent that defects of its own accord is a candidate:
        # count D's that followed two C's of mine.
        u = k = 0
        for s in range(max(2, n - WINDOW), n):
            if my[s - 1] == "C" and my[s - 2] == "C":
                k += 1
                u += op[s] == "D"
        if k < UNPROVOKED_OPP or u < UNPROVOKED_MIN * k:
            return None
        p1 = (c1 + 0.5) / (n1 + 1)
        p0 = (c0 + 0.5) / (n0 + 1)
        return (1 + 4 * p0) - 3 * p1

    def tft_move(self):
        t = len(self.my)
        if self.op[-1] == "C":
            return "C"
        if (self.tolerance > 0 and t - self.last_hit <= TOL_WINDOW
                and self.absorb_credit > 0):
            self.tolerance -= 1
            self.absorb_log.append(t)
            return "C"
        return "D"

    def calm(self, k):
        return (len(self.my) >= k and "D" not in self.my[-k:]
                and "D" not in self.op[-k:])

    def probe_move(self):
        """Return 'D' to probe/exploit this round, or None."""
        t = len(self.my)
        op = self.op
        st = self.stage
        if st == "wait":
            if t >= self.probe_at and self.calm(PROBE_CALM):
                self.probes.append(t)
                self.stage = "judge"
                return "D"
            if t > self.probe_at + 150:
                self.stage = "off"
            return None
        if st == "judge":
            p = self.probes[-1]
            if "D" in op[p + 1:]:
                self.stage = "off"          # they hit back: never again
                return None
            if t < p + 4:
                return None
            if len(self.probes) < 2:
                self.probes.append(t)
                return "D"
            self.stage = "exploit"
            self.next_exploit = t + EXPLOIT_GAPS[0]
            return None
        if st == "exploit":
            if op[-1] == "D":
                # answered: back off a level (or stop) and apologise
                if self.level == 0:
                    self.stage = "off"
                    return None
                self.level -= 1
                self.level_cap = self.level
                self.unanswered = 0
                self.apology = 2
                self.next_exploit = t + 2 + EXPLOIT_GAPS[self.level]
                return None
            if self.apology > 0:
                self.apology -= 1
                return None
            if t >= self.next_exploit:
                self.unanswered += 1
                if self.unanswered > EXPLOIT_STEP and self.level < self.level_cap:
                    self.level += 1
                    self.unanswered = 0
                self.next_exploit = t + EXPLOIT_GAPS[self.level]
                return "D"
        return None

    def learn(self):
        """Fold the latest round into the opponent model."""
        my, op = self.my, self.op
        t = len(op)
        for v in self.counts.values():
            v[0] *= MODEL_DECAY
            v[1] *= MODEL_DECAY
        if t >= 3:
            key = (my[t - 3], my[t - 2], op[t - 2])
            self.counts.setdefault(key, [0.0, 0.0])[op[t - 1] == "D"] += 1

    def p_coop(self, key, prior):
        c, d = self.counts.get(key, (0.0, 0.0))
        return (c + prior) / (c + d + 1.0)

    def model_move(self):
        """Best move under the learned memory-(2,1) model, by value iteration."""
        keys = [(a, b, c) for a in "CD" for b in "CD" for c in "CD"]
        recent = self.op[-BAD_WINDOW:]
        prior = (recent.count("C") + 0.5) / (len(recent) + 1.0)
        pc = {k: self.p_coop(k, prior) for k in keys}
        v = {k: 0.0 for k in keys}
        q = {}
        for _ in range(200):
            nv = {}
            for k in keys:
                _, m1, _ = k
                p = pc[k]
                best = None
                for a in "CD":
                    r = (p * (3 if a == "C" else 5)
                         + (1 - p) * (0 if a == "C" else 1))
                    val = r + GAMMA * (p * v[(m1, a, "C")]
                                       + (1 - p) * v[(m1, a, "D")])
                    q[(k, a)] = val
                    if best is None or val > best:
                        best = val
                nv[k] = best
            delta = max(abs(nv[k] - v[k]) for k in keys)
            v = nv
            if delta < 1e-3:
                break
        k = (self.my[-2], self.my[-1], self.op[-1])
        return "C" if q[(k, "C")] >= q[(k, "D")] else "D"

    # ------------------------------------------------------------ main
    def next_move(self):
        t = len(self.my)
        if t == 0:
            return "C"
        my, op = self.my, self.op

        self.dry = self.dry + 1 if op[-1] == "D" else 0
        if my[-1] == "D" and op[-1] == "C":
            self.last_hit = t - 1
            self.tolerance = min(self.tolerance + TOL_PER_HIT, 2 * TOL_PER_HIT)
        # An absorb worked if they then cooperated twice running.
        while self.absorb_log and t >= self.absorb_log[0] + 3:
            a = self.absorb_log.pop(0)
            if op[a + 1] == "C" and op[a + 2] == "C":
                self.absorb_credit = min(ABSORB_CREDIT, self.absorb_credit + 0.5)
            else:
                self.absorb_credit -= 1
        if self.calm(3):
            self.lock_wait = LOCK_WAIT
        self.points.append({("C", "C"): 3, ("C", "D"): 0, ("D", "C"): 5,
                            ("D", "D"): 1}[(my[-1], op[-1])])
        self.learn()
        if t >= BAD_WINDOW:
            recent = sum(self.points[-BAD_WINDOW:]) / BAD_WINDOW
            if not self.model_on and recent < BAD_ENTER:
                self.model_on = True
            elif self.model_on and recent > GOOD_EXIT and self.calm(CALM_EXIT):
                self.model_on = False
        if self.model_on and t >= 2:
            return self.model_move()

        if self.offer_left > 0:
            self.offer_left -= 1
            return "C"

        if t >= MIN_ROUND and self.stage != "exploit":
            adv = self.advantage()
            if adv is not None:
                if self.mode == "normal" and adv > ENTER_MARGIN:
                    self.mode = "defect"
                elif self.mode == "defect" and adv < EXIT_MARGIN:
                    self.mode = "normal"

        if self.dry >= self.lock_wait:
            self.lock_wait = min(self.lock_wait * 2, LOCK_WAIT_MAX)
            self.dry = 0
            self.offer_left = OFFER_LEN - 1
            return "C"

        if self.mode == "defect":
            return "D"
        if self.stage != "off":
            m = self.probe_move()
            if m:
                return m
        return self.tft_move()

    def move(self):
        m = self.next_move()
        self.my.append(m)
        return m

    def observe(self, their):
        self.op.append(their)
