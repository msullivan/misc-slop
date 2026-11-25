# Peephole Census

Every small integer expression, compiled by twelve compilers, to see where
each one disagrees with itself.

`(x * y) & 1` and `x & y & 1` are the same function. A compiler that turns
one into a multiply and the other into an AND knew the better answer and
didn't use it. This project finds every such case among all expressions of
up to four operations, without relying on anyone's opinion of what the best
code is: the compiler is only ever compared with its own output for an
equivalent expression.

Along the way it runs everything it compiles, which caught GCC returning
wrong answers.

## Look at it

<https://msullivan.github.io/misc-slop/peephole/site/>, or locally:

    cd site && python3 -m http.server 8766
    # then open http://localhost:8766/

The page has a scoreboard, a head-to-head matrix, and for each compiler a
few hundred of its smallest misses: the expression, an equivalent the same
compiler handles better, both pieces of machine code, and a link that opens
the pair in Compiler Explorer. Every pair shown was recompiled on its own,
run, and proved equivalent with an SMT solver.

## What was found

### GCC returns wrong answers

Both confirmed independently on Compiler Explorer.

    uint32_t f(uint32_t x) {
        return ((x << 31) > 1u ? (x << 31) : 1u) + ((x << 31) > 1u ? (x << 31) : 1u);
    }

`f(1)` is `0x80000000 + 0x80000000`, which is 0. GCC 8.4 through 13.1 return
2, **at `-O0`** as well as `-O2`, including 12.5, the last release of the 12
series. Fixed by 13.4. Any `max(a, c) + max(a, c)` or `min` of that shape
with unsigned operands is affected: GCC doubles the two arms separately, and
doubling doesn't commute with an unsigned comparison once it wraps.

    uint32_t g(uint32_t x) {
        int32_t h = (int32_t)x >> 1;
        return (h > -1 ? h : -1) == h;
    }

`g(-1)` is 1. GCC 9.5, 10.5 and 11.5, the last releases of their series,
return 0 at `-O2`. Fixed in 12.

The census found 15 such expressions for GCC 9 and 11 and 5 for GCC 12, all
variations on these two. No other compiler returned a wrong answer on any of
the 25 million functions.

### How often each compiler is beaten by itself

Share of census expressions for which the same compiler emitted strictly
better code for an equivalent expression.

| | arithmetic (24.1 M expressions) | comparisons (1.04 M) |
|---|---|---|
| clang 23.1.6 | 16.7% | 27.2% |
| clang 18.1.3 | 17.4% | 28.4% |
| clang 17 | 17.5% | 31.2% |
| clang 14 | 18.8% | 33.1% |
| clang 10 | 20.6% | 35.3% |
| GCC 16.2 | 24.9% | 35.5% |
| GCC 13.3 | 24.9% | 36.5% |
| GCC 12.4 | 25.1% | 36.6% |
| GCC 11.5 | 25.2% | 36.8% |
| GCC 9.5 | 26.0% | 36.4% |
| Go 1.27.4 | 39.5% | 59.9% |
| Cranelift (wasmtime 51) | 47.5% | 67.4% |

About three quarters of each figure is "fewer uops were available"; the rest
is the same work in a shorter chain. Most misses are independent of one
another: clang 23 has 1.5 million root misses in the arithmetic census,
falling into about 300,000 shapes once constants are blanked. There is no
short list of missing rules. There is a long tail.

Compared directly on the same source, clang 23 emits strictly better code
than GCC 16 for 13.8% of arithmetic expressions and GCC 16 better than clang
23 for 10.6%. On comparisons it is 34.4% against 5.6%.

### Things nobody knows

A few of the smallest expressions all twelve compilers get wrong in the same
way:

| written | equivalent |
|---|---|
| `2 & (1 - x)` | `x & 2` |
| `(x >>s 31) * (x >>s 31)` | `x >> 31` |
| `(x \| 0x80000000) * (x \| 0x80000000)` | `x * x` |
| `umax(x, x != 0)` | `x` |
| `smax(x, -1)` | `(x >>s 31) \| x`, on eleven of twelve |

(`>>s` is an arithmetic shift, `>>` a logical one.) And one that the newest
clang still misses but GCC has always had: `x - (x ^ 0x80000000)` is the
constant `0x80000000`.

### Releases that got worse

Between consecutive releases, on identical source:

| | got worse | got better |
|---|---|---|
| clang 18 to 23, arithmetic | 41,930 | 348,420 |
| clang 18 to 23, comparisons | 9,383 | 32,774 |
| GCC 13 to 16, arithmetic | 67,653 | 71,993 |
| GCC 13 to 16, comparisons | 19,690 | 29,083 |

Every clang release improves on far more expressions than it makes worse.
GCC 13 to 16 is close to a wash on arithmetic. The page lists examples for
every pair of releases.

### How much of this is proved

- Comparisons census: all 886,304 equalities between an expression and its
  class representative went to Z3. 555 were false and removed, 50 timed out.
- Arithmetic census, sizes 1 to 3: all 205,364 went to Z3 or the polynomial
  check. None false after the second round of test inputs, 2,289 undecided.
- Arithmetic census, size 4: 17.7 million equalities, too many to prove.
  Of 4,500 misses sampled at random, 10 rested on a false equality (0.22%)
  and 171 were undecided. Of the first 915,000 size-4 equalities checked
  before the run was stopped, 739 were false (0.08%). The size-4 figures
  above are off by about that much.
- Every example on the page: recompiled alone, run on the test inputs, and
  proved. Of 9,600 pairs, 38 are marked "tested": Z3 gave up, the polynomial
  check didn't apply, and four million random inputs found no difference.

## How it works

**Enumerate** (`enumerate/`, Rust). An expression is a DAG over 32-bit
values: leaves are `x`, `y` and a few constants, nodes are operations. Its
size is its number of distinct nodes, so a repeated subexpression counts
once. Each DAG is visited exactly once, as a straight-line program in a
canonical order. Skipped as noise: operations with a neutral or absorbing
constant (`x + 0`, `x & 0`), an operand combined with itself to no effect
(`x ^ x`), and shifts by anything but a constant.

Two languages were enumerated:

| | operations | constants | shift amounts | max size |
|---|---|---|---|---|
| arithmetic | `+ - * & \| ^ << >> >>s` | 0, 1, -1, 2, 3, 0xff, 0x80000000 | 1, 2, 8, 16, 24, 31 | 4 |
| comparisons | `+ - & \| ^ << >> >>s`, `== != < <=` signed and unsigned, signed and unsigned `min max` | 0, 1, -1, 2, 0x80000000 | 1, 31 | 3 |

**Classify.** Each expression is run on 160 inputs and the outputs hashed. A
table from that fingerprint to the smallest size seen gives every function's
cost. The census keeps the optimal expressions (nothing smaller computes the
same function) and the *primitive* non-optimal ones (something smaller
exists, but every proper subexpression is already optimal), and one of each
pair that differ only by swapping `x` and `y`.

**Don't trust the tests.** 160 inputs wrongly merge about 5% of classes:
`(x + 1) >> 31` and `x >> 31` differ on two inputs out of four billion. So
every census expression is run again on about 150,000 inputs built for the
purpose (values around powers of two, around each constant, and pairs that
nearly cancel), and then `verify.py` asks Z3 to prove each expression equal
to the smallest member of its class. What Z3 refutes is split off. Where Z3
times out on a multiply, the identity is tried as a polynomial identity
modulo 2^32, then on four million random inputs.

**Compile** (`compile.py`). Each expression becomes a function. Batches of
4,000 are compiled at `-O2` (Go: default; Cranelift: `opt-level=2`), the
object code disassembled with `objdump`, and each body reduced to a string.
Every batch is also linked against a small driver and run on the 160 test
inputs; the result is compared with the enumerator's fingerprint. That check
is what found the GCC miscompilations. A wrong result is only recorded if it
happens again with the function compiled alone.

**Cost** (`asmcost.py`). Two numbers per body. *uops*: instructions, not
counting register moves and zeroing idioms. *depth*: the longest dependency
chain from arguments to result, counting 3 for a multiply and 1 for anything
else. One body beats another only if it is no worse on both and better on
one. Bodies with a conditional jump are set aside rather than ranked.

**Analyse** (`analyze.py`, `distill.py`, `report.py`). An expression is a
miss for a compiler if that compiler produced better code for another member
of its class. A miss is a *root* if no subexpression is itself a miss, and
neither is the expression with a subexpression replaced by a plain variable.

## Caveats

- The cost model is crude on purpose. It will call `lea` and `add` equal and
  knows nothing about ports, fusion or code size. A miss means "fewer
  instructions doing work, or a shorter chain, and no worse on the other",
  which is hard to argue with but not the whole story.
- x86-64 only, default tuning, no `-march`.
- Unsigned 32-bit arithmetic throughout, so nothing here depends on signed
  overflow being undefined.
- Equalities between size-4 arithmetic expressions are tested, not all
  proved; see the figures above. Everything shown on the page is
  proved individually, apart from the few marked "tested".
- GCC's and clang's output for a function in a 4,000-function file is
  assumed to be what they'd produce for it alone. Every example on the page
  was recompiled alone and kept only if the difference held.

## Run it

`census.sh` is the whole pipeline. It needs Rust, Python with `numpy` and
`z3-solver`, `objdump`, and whichever compilers are named in
`compile.py`. On a 64-thread machine the arithmetic census takes about ten
minutes per compiler; the enumeration itself takes four seconds.

To add a compiler, add a line to `COMPILERS` in `compile.py` and run

    python compile.py RUN NAME
    python report.py report.json arith=RUNS/main cmp=RUNS/cmp
    python build_site.py report.json site

`tools/show.py RUN COMPILER SIZE` prints misses in a terminal.
