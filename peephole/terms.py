"""Decode the enumerator's packed expressions and render them."""
import itertools
import json

OPS = ["add", "mul", "and", "or", "xor", "sub", "shl", "lshr", "ashr",
       "eq", "ne", "lts", "ltu", "les", "leu", "smin", "smax", "umin", "umax"]
SHIFTS = {"shl", "lshr", "ashr"}
COMM = {"add", "mul", "and", "or", "xor", "eq", "ne", "smin", "smax", "umin", "umax"}
MINMAX = {"smin", "smax", "umin", "umax"}
SIGNED = {"lts", "les", "smin", "smax", "ashr"}
# Display. `>>` is logical and `>>s` arithmetic; `<` is unsigned, `<s` signed.
SYM = {"add": "+", "mul": "*", "and": "&", "or": "|", "xor": "^", "sub": "-",
       "shl": "<<", "lshr": ">>", "ashr": ">>s", "eq": "==", "ne": "!=",
       "lts": "<s", "ltu": "<", "les": "<=s", "leu": "<="}
# C spelling and precedence (higher binds tighter).
CSYM = {"add": "+", "mul": "*", "and": "&", "or": "|", "xor": "^", "sub": "-",
        "shl": "<<", "lshr": ">>", "ashr": ">>", "eq": "==", "ne": "!=",
        "lts": "<", "ltu": "<", "les": "<=", "leu": "<=",
        "smin": "<", "umin": "<", "smax": ">", "umax": ">"}
PREC = {"mul": 10, "add": 9, "sub": 9, "shl": 8, "lshr": 8, "ashr": 8,
        "lts": 7, "ltu": 7, "les": 7, "leu": 7, "eq": 6, "ne": 6,
        "and": 5, "xor": 4, "or": 3}
VARS = "xyzw"
M32 = 0xFFFFFFFF


def s32(x):
    return x - (1 << 32) if x >> 31 else x


class Lang:
    def __init__(self, meta):
        self.nv = meta["vars"]
        self.consts = meta["consts"]
        self.shifts = meta["shifts"]
        self.ibits = meta.get("ibits", 12)
        self.k = meta["k"]
        self.nleaf = self.nv + len(self.consts)

    @classmethod
    def load(cls, rundir):
        with open(f"{rundir}/meta.json") as f:
            return cls(json.load(f))

    def unpack(self, p):
        """-> list of (op, a, b) with op an index into OPS."""
        p = int(p)
        ib = self.ibits
        for n in range(1, 6):
            if p >> (ib * n) == n:
                return [((p >> (ib * (n - 1 - i) + 8)) & ((1 << (ib - 8)) - 1),
                         (p >> (ib * (n - 1 - i) + 4)) & 15,
                         (p >> (ib * (n - 1 - i))) & 15) for i in range(n)]
        raise ValueError(p)

    def sizes(self, packed):
        """Vectorized instruction count for a numpy array of packed values."""
        import numpy as np
        size = np.zeros(len(packed), dtype=np.uint8)
        for k in range(1, 6):
            size[(packed >> np.uint64(self.ibits * k)) == k] = k
        return size


def const_str(c):
    if c == M32:
        return "-1"
    if c == 0x80000000:
        return "0x80000000"
    if c > 0xFFFF or c == 0xFF:
        return hex(c)
    return str(c)


def infix(lang, ins, swap=False):
    """Human-readable expression over x, y."""
    def go(i):
        if i < lang.nv:
            if swap and lang.nv == 2:
                i = 1 - i
            return VARS[i], 99
        if i < lang.nleaf:
            return const_str(lang.consts[i - lang.nv]), 99
        op, a, b = ins[i - lang.nleaf]
        name = OPS[op]
        sa, pa = go(a)
        if name in SHIFTS:
            sb, pb = str(lang.shifts[b]), 99
        else:
            sb, pb = go(b)
        if name in MINMAX:
            return f"{name}({sa}, {sb})", 99
        p = PREC[name]
        # Unary forms read better.
        if name == "sub" and sa == "0":
            return ("-" + (sb if pb >= 11 else f"({sb})")), 11
        if name == "xor" and sb == "-1":
            return ("~" + (sa if pa >= 11 else f"({sa})")), 11
        if name == "xor" and sa == "-1":
            return ("~" + (sb if pb >= 11 else f"({sb})")), 11
        # Parenthesize unless it's plain arithmetic precedence: nobody
        # remembers how & and << rank against + and ==.
        arith = lambda q: q >= 9
        if not (pa == 99 or pa == 11 or (arith(pa) and arith(p) and pa >= p)
                or (pa == p and name in ("and", "or", "xor"))):
            sa = f"({sa})"
        if not (pb == 99 or pb == 11 or (arith(pb) and arith(p) and pb > p)
                or (pb == p and name in ("add", "mul", "and", "or", "xor"))):
            sb = f"({sb})"
        return f"{sa} {SYM[name]} {sb}", p

    return go(lang.nleaf + len(ins) - 1)[0]


def c_expr(lang, ins, swap=False):
    """A C expression over uint32_t x, y. Shared subterms are repeated."""
    def go(i):
        if i < lang.nv:
            if swap and lang.nv == 2:
                i = 1 - i
            return VARS[i]
        if i < lang.nleaf:
            return f"{lang.consts[i - lang.nv]}u"
        op, a, b = ins[i - lang.nleaf]
        name = OPS[op]
        sa = go(a)
        if name in SHIFTS:
            if name == "ashr":
                return f"((uint32_t)((int32_t){sa} >> {lang.shifts[b]}))"
            return f"({sa} {CSYM[name]} {lang.shifts[b]})"
        sb = go(b)
        ca, cb = (f"(int32_t){sa}", f"(int32_t){sb}") if name in SIGNED else (sa, sb)
        if name in MINMAX:
            return f"({ca} {CSYM[name]} {cb} ? {sa} : {sb})"
        if name in ("eq", "ne", "lts", "ltu", "les", "leu"):
            return f"((uint32_t)({ca} {CSYM[name]} {cb}))"
        return f"({sa} {CSYM[name]} {sb})"
    return go(lang.nleaf + len(ins) - 1)


def go_expr(lang, ins):
    """A Go expression over uint32 x, y. Needs b2i() in scope for comparisons."""
    def go(i):
        if i < lang.nv:
            return VARS[i]
        if i < lang.nleaf:
            return f"uint32({lang.consts[i - lang.nv]})"
        op, a, b = ins[i - lang.nleaf]
        name = OPS[op]
        sa = go(a)
        if name in SHIFTS:
            if name == "ashr":
                return f"uint32(int32({sa}) >> {lang.shifts[b]})"
            return f"({sa} {CSYM[name]} {lang.shifts[b]})"
        sb = go(b)
        # A constant has to be written as its signed value: Go rejects
        # int32(uint32(4294967295)) as a constant overflow.
        sgn = lambda i, s: f"int32({s32(lang.consts[i - lang.nv])})" if lang.nv <= i < lang.nleaf else f"int32({s})"
        ca, cb = (sgn(a, sa), sgn(b, sb)) if name in SIGNED else (sa, sb)
        if name in MINMAX:
            f = name[1:]
            return f"uint32({f}({ca}, {cb}))" if name in SIGNED else f"{f}({sa}, {sb})"
        if name in ("eq", "ne", "lts", "ltu", "les", "leu"):
            return f"b2i({ca} {CSYM[name]} {cb})"
        return f"({sa} {CSYM[name]} {sb})"
    return go(lang.nleaf + len(ins) - 1)


WAT = {"add": "i32.add", "mul": "i32.mul", "and": "i32.and", "or": "i32.or",
       "xor": "i32.xor", "sub": "i32.sub", "shl": "i32.shl", "lshr": "i32.shr_u",
       "ashr": "i32.shr_s", "eq": "i32.eq", "ne": "i32.ne", "lts": "i32.lt_s",
       "ltu": "i32.lt_u", "les": "i32.le_s", "leu": "i32.le_u",
       "smin": "i32.lt_s", "umin": "i32.lt_u", "smax": "i32.gt_s", "umax": "i32.gt_u"}


def wat_expr(lang, ins):
    """A folded WebAssembly text expression over locals 0, 1."""
    def go(i):
        if i < lang.nv:
            return f"(local.get {i})"
        if i < lang.nleaf:
            return f"(i32.const {s32(lang.consts[i - lang.nv])})"
        op, a, b = ins[i - lang.nleaf]
        name = OPS[op]
        sa = go(a)
        if name in SHIFTS:
            return f"({WAT[name]} {sa} (i32.const {lang.shifts[b]}))"
        sb = go(b)
        if name in MINMAX:
            return f"(select {sa} {sb} ({WAT[name]} {sa} {sb}))"
        return f"({WAT[name]} {sa} {sb})"
    return go(lang.nleaf + len(ins) - 1)


def apply(name, x, y):
    """One operation on 32-bit values (y is the shift amount for shifts)."""
    if name == "shl":
        r = x << y
    elif name == "lshr":
        r = x >> y
    elif name == "ashr":
        r = s32(x) >> y
    elif name == "add":
        r = x + y
    elif name == "sub":
        r = x - y
    elif name == "mul":
        r = x * y
    elif name == "and":
        r = x & y
    elif name == "or":
        r = x | y
    elif name == "xor":
        r = x ^ y
    elif name == "eq":
        r = x == y
    elif name == "ne":
        r = x != y
    elif name == "lts":
        r = s32(x) < s32(y)
    elif name == "ltu":
        r = x < y
    elif name == "les":
        r = s32(x) <= s32(y)
    elif name == "leu":
        r = x <= y
    elif name == "smin":
        r = x if s32(x) < s32(y) else y
    elif name == "smax":
        r = x if s32(x) > s32(y) else y
    elif name == "umin":
        r = min(x, y)
    elif name == "umax":
        r = max(x, y)
    else:
        raise ValueError(name)
    return int(r) & M32


def evaluate(lang, ins, env):
    vals = list(env) + list(lang.consts)
    for op, a, b in ins:
        name = OPS[op]
        vals.append(apply(name, vals[a], lang.shifts[b] if name in SHIFTS else vals[b]))
    return vals[-1]


def key_str(lang, ins, root=None, skeleton=False):
    """A string naming the expression rooted at instruction `root`, the same
    for every spelling of it: commutative operands sorted, variables renamed
    to whichever order gives the smallest string. With skeleton=True the
    constants and shift amounts are blanked, so `x >> 3 << 3` and
    `x >> 8 << 8` get the same name."""
    if root is None:
        root = len(ins) - 1
    best = None
    for perm in itertools.permutations(range(lang.nv)):
        def go(i):
            if i < lang.nv:
                return VARS[perm[i]]
            if i < lang.nleaf:
                c = lang.consts[i - lang.nv]
                return "C" if skeleton and c not in (0, M32) else const_str(c)
            op, a, b = ins[i - lang.nleaf]
            name = OPS[op]
            sa = go(a)
            if name in SHIFTS:
                return f"({name} {sa} {'S' if skeleton else lang.shifts[b]})"
            sb = go(b)
            if name in COMM and sb < sa:
                sa, sb = sb, sa
            return f"({name} {sa} {sb})"
        s = go(lang.nleaf + root)
        if best is None or s < best:
            best = s
    return best


def subterm(lang, ins, root):
    """The instructions of the expression rooted at `root`, renumbered."""
    keep = []

    def visit(j):
        if j in keep:
            return
        op, a, b = ins[j]
        if a >= lang.nleaf:
            visit(a - lang.nleaf)
        if OPS[op] not in SHIFTS and b >= lang.nleaf:
            visit(b - lang.nleaf)
        keep.append(j)

    visit(root)
    new = {j: i for i, j in enumerate(keep)}
    out = []
    for j in keep:
        op, a, b = ins[j]
        fa = lang.nleaf + new[a - lang.nleaf] if a >= lang.nleaf else a
        fb = b if OPS[op] in SHIFTS or b < lang.nleaf else lang.nleaf + new[b - lang.nleaf]
        out.append((op, fa, fb))
    return out


def abstract(lang, ins, j):
    """The expression with the subexpression rooted at instruction j replaced
    by a variable that doesn't otherwise appear. None if every variable is
    already in use outside it. `((x + 1) * y) & 1` abstracts to `(x * y) & 1`:
    if a compiler misses the latter, missing the former is nothing new."""
    nl = lang.nleaf
    root = len(ins) - 1
    if j == root:
        return None
    keep, used = [], set()

    def visit(i):
        if i == j or i in keep:
            return
        op, a, b = ins[i]
        for o in ([a] if OPS[op] in SHIFTS else [a, b]):
            if o >= nl:
                visit(o - nl)
            elif o < lang.nv:
                used.add(o)
        keep.append(i)

    visit(root)
    free = [v for v in range(lang.nv) if v not in used]
    if not free:
        return None
    new = {i: k for k, i in enumerate(keep)}
    fix = lambda o: o if o < nl else (free[0] if o - nl == j else nl + new[o - nl])
    out = []
    for i in keep:
        op, a, b = ins[i]
        out.append((op, fix(a), b) if OPS[op] in SHIFTS else (op, fix(a), fix(b)))
    return out


def swap_vars(lang, ins):
    """The same expression with x and y exchanged."""
    assert lang.nv == 2
    f = lambda o: 1 - o if o < 2 else o
    return [(op, f(a), b if OPS[op] in SHIFTS else f(b)) for op, a, b in ins]


def trivial(lang, ins):
    """If the expression is really a constant or a bare variable, its text."""
    probes = [(5, 9), (123456, 7), (0xDEADBEEF, 0x1234), (9, 5)][:4]
    probes = [p[:lang.nv] + (3,) * (lang.nv - 2) for p in probes]
    outs = [evaluate(lang, ins, p) for p in probes]
    if len(set(outs)) == 1:
        return const_str(outs[0])
    for v in range(lang.nv):
        if all(o == p[v] for o, p in zip(outs, probes)):
            return VARS[v]
    return None
