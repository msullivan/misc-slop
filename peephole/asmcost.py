"""A deliberately simple cost for a straight-line x86-64 function body.

    cost(body) -> (uops, depth, n)

uops   instructions that do work: everything except register-to-register
       moves and zeroing idioms (xor eax,eax), which every current x86 core
       removes at rename.
depth  length of the dependency chain from the arguments to the return
       value, in cycles: 3 for a multiply, 1 for everything else, 0 for a
       register move. Constants are ready at time 0.
n      instructions, moves included.

One body is better than another only if it is no worse on both uops and
depth and strictly better on one, so the verdict doesn't depend on how the
two are weighed against each other.
"""
import re

_REG = {}
for i, base in enumerate(["ax", "cx", "dx", "bx", "sp", "bp", "si", "di"]):
    for name in ("r" + base, "e" + base, base):
        _REG[name] = "r" + base
for b in "abcd":
    _REG[b + "l"] = _REG[b + "h"] = "r" + b + "x"
for b in ("si", "di", "sp", "bp"):
    _REG[b + "l"] = "r" + b
for i in range(8, 16):
    for suf in ("", "d", "w", "b"):
        _REG[f"r{i}{suf}"] = f"r{i}"

# 32- and 64-bit register names.
_WIDE = {n for n in _REG if n[0] == "e" or (n[0] == "r" and n[-1] not in "bw")}
_TOK = re.compile(r"[a-z][a-z0-9]*")
LAT = {"imul": 3, "mul": 3, "popcnt": 3, "lzcnt": 3, "tzcnt": 3, "bsr": 3, "bsf": 3,
       "pdep": 3, "pext": 3, "mulx": 4}
RW = {"add", "sub", "and", "or", "xor", "shl", "sal", "shr", "sar", "rol", "ror",
      "adc", "sbb", "bts", "btr", "btc", "shld", "shrd"}
UNARY = {"not", "neg", "inc", "dec", "bswap"}
PURE3 = {"andn", "shlx", "shrx", "sarx", "rorx", "bextr", "bzhi", "pdep", "pext"}
PURE2 = {"mov", "movzx", "movsx", "movsxd", "lea", "popcnt", "lzcnt", "tzcnt", "bsr", "bsf",
         "blsi", "blsr", "blsmsk"}
NOFLAGS = {"mov", "movzx", "movsx", "movsxd", "lea", "not", "bswap", "shlx", "shrx", "sarx", "rorx"}
USES_CF = {"adc", "sbb"}


FAILED = 99
BRANCHY = 98
_JUMP = re.compile(r"(^|;)(j[a-z]+|call|loop) ")


class Unknown(Exception):
    pass


def _split(ops):
    out, depth, cur = [], 0, ""
    for ch in ops:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return [o.strip() for o in out]


def _operand(o):
    """-> (kind, regs) with kind in reg/imm/mem."""
    if "[" in o:
        inner = o[o.index("[") + 1:o.rindex("]")]
        return "mem", [_REG[t] for t in _TOK.findall(inner) if t in _REG]
    if o in _REG:
        return "reg", [_REG[o]]
    return "imm", []


def cost(body):
    if body.startswith("!"):
        return FAILED, FAILED, FAILED  # the compiler failed on this one
    if _JUMP.search(body):
        # Not straight-line. How good a branch is depends on how predictable
        # the data is, so these are set aside rather than ranked.
        return BRANCHY, BRANCHY, body.count(";") + 1
    ready = {}
    uops = n = 0
    if body:
        for ins in body.split(";"):
            n += 1
            sp = ins.find(" ")
            mn, rest = (ins, "") if sp < 0 else (ins[:sp], ins[sp + 1:])
            ops = [_operand(o) for o in _split(rest)]
            lat = LAT.get(mn, 1)
            reads, writes = [], []
            wflags = mn not in NOFLAGS
            if mn in ("cwde", "cdqe", "cbw"):
                reads = writes = ["rax"]
                wflags = False
            elif mn == "cdq":
                reads, writes = ["rax"], ["rdx"]
                wflags = False
            elif mn in ("cmp", "test"):
                for k, r in ops:
                    reads += r
            elif mn.startswith("set"):
                reads, writes, wflags = ["F"], ops[0][1], False
            elif mn.startswith("cmov"):
                reads, writes, wflags = ["F"] + ops[0][1] + ops[1][1], ops[0][1], False
            elif mn in PURE2 or mn in PURE3 or (mn == "imul" and len(ops) == 3):
                if ops[0][0] != "reg":
                    raise Unknown(ins)
                writes = ops[0][1]
                for k, r in ops[1:]:
                    reads += r
                    if k == "mem" and mn != "lea":
                        lat += 4
                if mn == "mov" and ops[1][0] == "reg":
                    lat = 0
            elif mn in RW or (mn == "imul" and len(ops) == 2):
                if ops[0][0] != "reg":
                    raise Unknown(ins)
                writes = ops[0][1]
                # Same register on both sides, at full width: `xor al,al`
                # clears a byte and still depends on the rest.
                raw = _split(rest)
                same = len(raw) == 2 and raw[0] == raw[1] and raw[0] in _WIDE
                if mn in ("xor", "sub") and same:
                    reads = []  # zeroing idiom: handled at rename, like a move
                    uops -= 1
                elif mn == "sbb" and same:
                    reads = ["F"]
                else:
                    reads = list(ops[0][1])
                    for k, r in ops[1:]:
                        reads += r
                        if k == "mem":
                            lat += 4
                    if mn in USES_CF:
                        reads.append("F")
            elif mn in UNARY:
                if ops[0][0] != "reg":
                    raise Unknown(ins)
                reads = writes = ops[0][1]
            elif mn == "bt":
                reads = ops[0][1] + ops[1][1]
            elif mn == "xchg":
                # Two registers trade places: three uops on Intel.
                a, b = ops[0][1][0], ops[1][1][0]
                ta, tb = ready.get(a, 0), ready.get(b, 0)
                ready[a], ready[b] = tb + 1, ta + 1
                uops += 3
                continue
            else:
                raise Unknown(ins)
            if not (mn == "mov" and lat == 0):
                uops += 1
            t = max((ready.get(r, 0) for r in reads), default=None)
            t = 0 if t is None else t + lat
            for w in writes:
                ready[w] = t
            if wflags:
                ready["F"] = t
    return uops, ready.get("rax", 0), n
