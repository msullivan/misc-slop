"""opus-2: an iterated prisoner's dilemma strategy.  See NOTES.md."""

import os
import random


class Bot:
    def __init__(self, rng=None, probe_prob=0.0):
        self.rng = rng or random.Random(int.from_bytes(os.urandom(8), "big"))
        self.me = []        # my moves
        self.op = []        # opponent moves
        # normal | alld | contrite | exploit_alt | exploit_all
        self.mode = "normal"
        self.echo_forgives = 0
        self.last_echo_forgive = -100
        self.deadlock_tries = 0
        self.last_deadlock_try = -100
        self.pavlov_tries = 0
        self.followup = -1      # round where we cooperate regardless
        # contrite phase: after our own unprovoked defection(s)
        self.contrite_start = None
        # probing for opponents that do not retaliate
        self.probe_round = None
        if self.rng.random() < probe_prob:
            self.probe_round = self.rng.randint(40, 100)
        self.probed = False
        self.exploit_start = None
        self.all_failed = False

    # ------------------------------------------------------------ helpers
    def unresponsive(self):
        """Their next move does not depend on our last move.

        Split rounds by their own previous move (so that fixed patterns such
        as alternation are not mistaken for reactions to us), then compare
        P(their C | we played C) with P(their C | we played D)."""
        n = len(self.op)
        if n < 30:
            return False
        if self.op.count("C") / n > 0.8:
            return False
        cnt = {}
        for t in range(1, n):
            k = (self.op[t - 1], self.me[t - 1])
            c = cnt.setdefault(k, [0, 0])
            c[0] += self.op[t] == "C"
            c[1] += 1
        tested = False
        for x in "CD":
            a, b = cnt.get((x, "C"), [0, 0]), cnt.get((x, "D"), [0, 0])
            if a[1] < 6 or b[1] < 6:
                continue
            if abs(a[0] / a[1] - b[0] / b[1]) >= 0.2:
                return False
            tested = True
        return tested

    def after(self, mine, theirs):
        """How often they cooperated right after a round (mine, theirs)."""
        c = k = 0
        for t in range(1, len(self.op)):
            if self.me[t - 1] == mine and self.op[t - 1] == theirs:
                k += 1
                c += self.op[t] == "C"
        return c, k

    # ------------------------------------------------------------ protocol
    def move(self):
        m = self._move()
        self.me.append(m)
        return m

    def observe(self, their):
        self.op.append(their)

    # ------------------------------------------------------------ strategy
    def _move(self):
        n = len(self.op)
        if n == 0:
            return "C"

        if self.mode == "alld":
            return "D"

        if self.mode in ("normal", "contrite") and self.unresponsive():
            self.mode = "alld"
            return "D"

        if self.mode in ("exploit_alt", "exploit_all"):
            m = self._exploit(n)
            if m is not None:
                return m

        if self.mode == "contrite":
            m = self._contrite(n)
            if m is not None:
                return m

        # probe: one defection inside a long run of pure mutual cooperation
        if (self.probe_round is not None and not self.probed
                and n >= self.probe_round
                and "D" not in self.op and "D" not in self.me):
            self.probed = True
            self.exploit_start = n + 1
            self.mode = "watch"
            return "D"
        if self.mode == "watch":
            # round right after the probe: cooperate, then see their answer
            if n == self.exploit_start:
                return "C"
            if self.op[self.exploit_start] == "C":
                # they let our defection pass: keep testing
                self.mode = "exploit_alt"
                self.exploit_start = n
                return "D"
            self._enter_contrite(self.exploit_start)
            m = self._contrite(n)
            if m is not None:
                return m

        return self._normal(n)

    def _enter_contrite(self, start):
        self.mode = "contrite"
        self.contrite_start = start

    def _contrite(self, n):
        """We defected unprovoked; accept some punishment to get back to C.

        Cooperate for three rounds from contrite_start.  If they cooperate
        anywhere in there, resume normal play.  If they defect all three
        times (win-stay-lose-shift does this), play D once then C."""
        s = self.contrite_start
        seen = self.op[s:]
        if "C" in seen:
            self.mode = "normal"
            return "C" if self.op[-1] == "C" else None
        k = n - s
        if k < 3:
            return "C"
        if k == 3:
            return "D"
        if k == 4:
            return "C"
        self.mode = "normal"
        return None

    def _normal(self, n):
        me, op = self.me, self.op
        last_op = op[-1]
        if last_op == "C":
            return "C"
        if n == self.followup:
            return "C"

        # Win-stay-lose-shift style opponents cooperate after mutual D and
        # defect after being suckered.  If they've shown both, answer a
        # mutual D with C: they'll play C too.
        if me[-1] == "D":
            c1, k1 = self.after("D", "D")
            c2, k2 = self.after("D", "C")
            if (k1 and k2 and c1 / k1 >= 0.5 and c2 / k2 < 0.5
                    and self.pavlov_tries < 3 + n // 30):
                self.pavlov_tries += 1
                return "C"

        # C/D echo: (me D, them C) then (me C, them D).  Our retaliation
        # is being retaliated; take the sucker payoff once to stop it.
        if (n >= 2 and me[-2] == "D" and op[-2] == "C" and me[-1] == "C"):
            gap = 4 if self.echo_forgives < 3 else 20
            if n - self.last_echo_forgive > gap:
                self.echo_forgives += 1
                self.last_echo_forgive = n
                return "C"

        # D/D deadlock
        if n >= 3 and all(me[-k] == "D" and op[-k] == "D" for k in (1, 2, 3)):
            budget = 2 + n // 40
            if (self.deadlock_tries < budget
                    and n - self.last_deadlock_try > 10
                    and op.count("C") / n > 0.15):
                self.deadlock_tries += 1
                self.last_deadlock_try = n
                # a TFT-like bot answers this with D (copying our last D);
                # cooperate once more so it can follow our C
                self.followup = n + 1
                return "C"

        return "D"

    def _exploit(self, n):
        """Opponent let a defection pass; take advantage while it lasts.

        Returns None to fall back to normal play."""
        me, op = self.me, self.op
        start = self.exploit_start
        if "D" in op[start:]:
            if self.mode == "exploit_all":
                # too greedy: apologise, then go back to alternating
                self.mode = "exploit_alt"
                self.all_failed = True
                self.exploit_start = n + 1
                return "C"
            # they do react after all: make peace
            self._enter_contrite(n)
            return self._contrite(n)
        if self.mode == "exploit_alt":
            if n - start >= 20 and not self.all_failed:
                self.mode = "exploit_all"
                self.exploit_start = n
                return "D"
            return "C" if me[-1] == "D" else "D"
        return "D"
