#!/usr/bin/env python3
"""Iterated prisoner's dilemma tournament harness.

    tournament.py match DIR_A DIR_B [-n ROUNDS] [--games K]   play and print
    tournament.py run --round N [--games K]                    full round-robin

A bot is a directory holding an executable `run`.  See RULES.md for the
protocol.
"""

import argparse
import concurrent.futures
import json
import os
import random
import select
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# payoff[(mine, theirs)] -> my points
PAYOFF = {("C", "C"): 3, ("C", "D"): 0, ("D", "C"): 5, ("D", "D"): 1}

END_PROB = 1 / 200      # chance the match stops after each round
MAX_ROUNDS = 2000
FIRST_MOVE_TIMEOUT = 5.0
MOVE_TIMEOUT = 1.0
BUILD_TIMEOUT = 120.0


def draw_length(rng):
    n = 1
    while n < MAX_ROUNDS and rng.random() >= END_PROB:
        n += 1
    return n


class Player:
    def __init__(self, botdir):
        self.dir = os.path.abspath(botdir)
        self.err = tempfile.TemporaryFile()
        self.buf = b""
        self.failure = None
        try:
            self.proc = subprocess.Popen(
                [os.path.join(self.dir, "run")], cwd=self.dir,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.err, bufsize=0, start_new_session=True)
        except OSError as e:
            self.proc = None
            self.failure = f"could not start: {e}"

    def read_move(self, timeout):
        """Return 'C' or 'D', or None after recording a failure."""
        if self.failure:
            return None
        deadline = time.monotonic() + timeout
        fd = self.proc.stdout.fileno()
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                return self.fail(f"timeout (>{timeout:g}s) waiting for a move")
            chunk = os.read(fd, 4096)
            if not chunk:
                return self.fail("exited / closed stdout before the match ended")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        move = line.decode("latin-1").strip()
        if move not in ("C", "D"):
            return self.fail(f"invalid move {move[:40]!r}")
        return move

    def send(self, move):
        if self.failure:
            return
        try:
            os.write(self.proc.stdin.fileno(), move.encode() + b"\n")
        except OSError:
            self.fail("closed stdin before the match ended")

    def fail(self, why):
        self.failure = why
        self.kill()
        return None

    def kill(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                pass

    def finish(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            self.kill()
            self.proc.wait()
            self.proc.stdout.close()
        self.err.seek(0)
        stderr = self.err.read()[-2000:].decode("utf-8", "replace")
        self.err.close()
        return stderr


def play_match(dir_a, dir_b, rounds):
    """Play one match.  A failed bot plays D and scores 0 from then on."""
    players = [Player(dir_a), Player(dir_b)]
    moves = ["", ""]
    scores = [0, 0]
    failed_at = [None, None]
    for r in range(rounds):
        timeout = FIRST_MOVE_TIMEOUT if r == 0 else MOVE_TIMEOUT
        got = [p.read_move(timeout) for p in players]
        for i in (0, 1):
            if got[i] is None and failed_at[i] is None:
                failed_at[i] = r
        cur = [g or "D" for g in got]
        for i in (0, 1):
            moves[i] += cur[i]
            if got[i] is not None:
                scores[i] += PAYOFF[(cur[i], cur[1 - i])]
        players[0].send(cur[1])
        players[1].send(cur[0])
    stderrs = [p.finish() for p in players]
    return {
        "rounds": rounds, "moves": moves, "scores": scores,
        "failures": [
            None if p.failure is None or failed_at[i] is None else
            {"round": failed_at[i] + 1, "why": p.failure, "stderr": stderrs[i]}
            for i, p in enumerate(players)],
    }


# ---------------------------------------------------------------- reporting

def match_text(m, side, opp_label):
    me, them = side, 1 - side
    out = [f"== vs {opp_label}: {m['rounds']} rounds, "
           f"you {m['scores'][me]}, them {m['scores'][them]}",
           f"you : {m['moves'][me]}",
           f"them: {m['moves'][them]}"]
    for who, i in (("YOU", me), ("THEY", them)):
        f = m["failures"][i]
        if f:
            out.append(f"!! {who} FAILED at round {f['round']}: {f['why']} "
                       f"(scored 0 and counted as D from there on)")
            if who == "YOU" and f["stderr"].strip():
                out.append("!! your stderr (tail):\n" + f["stderr"].rstrip())
    return "\n".join(out)


def cmd_match(args):
    rng = random.Random()
    for g in range(args.games):
        n = args.n or draw_length(rng)
        m = play_match(args.a, args.b, n)
        print(f"game {g + 1}: {n} rounds   A={m['scores'][0]}  B={m['scores'][1]}")
        print(f"A: {m['moves'][0]}")
        print(f"B: {m['moves'][1]}")
        for label, f in zip("AB", m["failures"]):
            if f:
                print(f"!! {label} FAILED at round {f['round']}: {f['why']}")
                if f["stderr"].strip():
                    print(f["stderr"].rstrip())


def cmd_run(args):
    bots_dir = os.path.join(HERE, "bots")
    names = sorted(d for d in os.listdir(bots_dir)
                   if os.access(os.path.join(bots_dir, d, "run"), os.X_OK))
    if args.only:
        names = [n for n in names if n in args.only]
    for n in names:
        build = os.path.join(bots_dir, n, "build")
        if os.access(build, os.X_OK):
            print(f"building {n}", file=sys.stderr)
            subprocess.run([build], cwd=os.path.dirname(build),
                           timeout=BUILD_TIMEOUT, stdin=subprocess.DEVNULL)

    seed = int.from_bytes(os.urandom(8), "big")
    rng = random.Random(seed)
    jobs = []
    for i, a in enumerate(names):
        for b in names[i:]:
            for g in range(args.games):
                jobs.append((a, b, g, draw_length(rng)))

    def work(job):
        a, b, g, n = job
        m = play_match(os.path.join(bots_dir, a), os.path.join(bots_dir, b), n)
        m.update(a=a, b=b, game=g + 1)
        return m

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as ex:
        matches = list(ex.map(work, jobs))
    print(f"{len(matches)} matches in {time.time() - t0:.1f}s", file=sys.stderr)

    out_dir = os.path.join(HERE, "results", f"round{args.round}")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "matches.jsonl"), "w") as f:
        for m in matches:
            f.write(json.dumps(m) + "\n")

    pts = {n: 0 for n in names}
    rds = {n: 0 for n in names}
    pair = {}          # (me, opp) -> [points, rounds]
    fails = {n: 0 for n in names}
    for m in matches:
        sides = [(m["a"], m["b"], 0)]
        if m["a"] != m["b"]:
            sides.append((m["b"], m["a"], 1))
        for me, opp, i in sides:
            # a self-play match counts once, as the mean of its two seats
            p = (sum(m["scores"]) / 2) if me == opp else m["scores"][i]
            pts[me] += p
            rds[me] += m["rounds"]
            cell = pair.setdefault((me, opp), [0, 0])
            cell[0] += p
            cell[1] += m["rounds"]
        for i, n in enumerate((m["a"], m["b"])):
            if m["failures"][i]:
                fails[n] += 1

    order = sorted(names, key=lambda n: -pts[n] / rds[n])
    lines = [f"# Round {args.round} standings", "",
             f"{len(names)} bots, {args.games} games per pairing "
             f"(including one pairing against a copy of itself), "
             f"{len(matches)} matches, seed {seed}.", "",
             "Score is mean points per round over all of a bot's matches.", "",
             "| rank | bot | points/round | total points | rounds | failed matches |",
             "|---|---|---|---|---|---|"]
    for k, n in enumerate(order):
        lines.append(f"| {k + 1} | {n} | {pts[n] / rds[n]:.4f} | {pts[n]:g} "
                     f"| {rds[n]} | {fails[n]} |")
    lines += ["", "## Points per round, row against column", "",
              "| | " + " | ".join(order) + " |",
              "|---|" + "---|" * len(order)]
    for a in order:
        cells = [f"{pair[(a, b)][0] / pair[(a, b)][1]:.2f}" for b in order]
        lines.append(f"| **{a}** | " + " | ".join(cells) + " |")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "standings.md"), "w") as f:
        f.write(text)
    print(text)

    for n in names:
        tdir = os.path.join(bots_dir, n, "transcripts")
        os.makedirs(tdir, exist_ok=True)
        parts = [f"# {n}: all matches of tournament round {args.round}",
                 f"# overall: {pts[n] / rds[n]:.4f} points/round, "
                 f"rank {order.index(n) + 1} of {len(names)}", ""]
        for m in matches:
            if m["a"] == n:
                opp = m["b"] if m["b"] != n else f"{n} (a copy of yourself)"
                parts.append(match_text(m, 0, f"{opp}, game {m['game']}"))
            elif m["b"] == n:
                parts.append(match_text(m, 1, f"{m['a']}, game {m['game']}"))
            else:
                continue
            parts.append("")
        with open(os.path.join(tdir, f"round{args.round}.txt"), "w") as f:
            f.write("\n".join(parts))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("match", help="play two bot directories against each other")
    m.add_argument("a")
    m.add_argument("b")
    m.add_argument("-n", type=int, help="fixed number of rounds (default: random)")
    m.add_argument("--games", type=int, default=1)
    m.set_defaults(fn=cmd_match)
    r = sub.add_parser("run", help="run a full tournament round")
    r.add_argument("--round", type=int, required=True)
    r.add_argument("--games", type=int, default=5)
    r.add_argument("--jobs", type=int, default=16)
    r.add_argument("--only", nargs="*", help="restrict to these bots (testing)")
    r.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
