#!/usr/bin/env python3
"""Compile every census expression with one compiler and record the machine
code it produced.

    compile.py RUN COMPILER [--jobs N] [--limit N]

Each expression becomes one tiny function. Functions are compiled in batches,
the object code is disassembled with objdump, and each function's body is
reduced to a normalized string. Every batch is also linked and run on the
census's test inputs, so a compiler that changes what a function computes
(or a bug in the source this script emits) is caught.

Writes RUN/asm/COMPILER.ids.npy (one id per census expression) and
RUN/asm/COMPILER.bodies.json (id -> body).
"""
import argparse
import json
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

from terms import Lang, c_expr, go_expr, wat_expr, VARS

HERE = os.path.dirname(os.path.abspath(__file__))
TC = os.path.expanduser("~/src/peephole-build/tc")

CFLAGS = ["-O2", "-fno-asynchronous-unwind-tables", "-fcf-protection=none"]

# name -> (kind, argv prefix)
COMPILERS = {
    "gcc-9": ("c", ["gcc-9"]),
    "gcc-11": ("c", ["gcc-11"]),
    "gcc-12": ("c", ["gcc-12"]),
    "gcc-13": ("c", ["gcc-13"]),
    "gcc-16": ("c", [f"{TC}/gcc-16.2.0/bin/gcc"]),
    "clang-10": ("c", ["clang-10"]),
    "clang-14": ("c", ["clang-14"]),
    "clang-17": ("c", ["clang-17"]),
    "clang-18": ("c", ["clang-18"]),
    "clang-23": ("c", [f"{TC}/LLVM-23.1.6-Linux-X64/bin/clang"]),
    "go-1.27": ("go", ["go"]),
    "cranelift-51": ("wat", [f"{TC}/wasmtime-v51.0.0-x86_64-linux/wasmtime"]),
}

FP_C = r"""
#include <stdint.h>
#include <stdio.h>
typedef uint32_t (*fn)(%(params)s);
%(decls)s
static fn tab[] = {%(names)s};
static const uint32_t in[][%(nv)d] = {%(inputs)s};
int main(void) {
  for (unsigned i = 0; i < sizeof tab / sizeof *tab; i++) {
    uint64_t h = 0x243F6A8885A308D3ull;
    for (unsigned t = 0; t < sizeof in / sizeof *in; t++) {
      h = (h ^ (uint64_t)tab[i](%(args)s)) * 0x9E3779B97F4A7C15ull;
      h ^= h >> 32;
    }
    h = (h ^ (h >> 29)) * 0xBF58476D1CE4E5B9ull;
    h ^= h >> 32;
    if (!h) h = 1;
    fwrite(&h, 8, 1, stdout);
  }
  return 0;
}
"""

FP_GO = r"""
var in = [][%(nv)d]uint32{%(inputs)s}

func main() {
	buf := make([]byte, 0, 8*len(tab))
	for _, f := range tab {
		h := uint64(0x243F6A8885A308D3)
		for _, v := range in {
			h = (h ^ uint64(f(%(args)s))) * 0x9E3779B97F4A7C15
			h ^= h >> 32
		}
		h = (h ^ (h >> 29)) * 0xBF58476D1CE4E5B9
		h ^= h >> 32
		if h == 0 {
			h = 1
		}
		for i := 0; i < 8; i++ {
			buf = append(buf, byte(h>>(8*i)))
		}
	}
	os.Stdout.Write(buf)
}
"""

# Padding and returns. `add BYTE PTR [rax],al` is what a run of zero bytes
# between functions disassembles to.
SKIP = re.compile(r"^(nop|endbr64|int3|ret|xchg\s+ax,ax|data16|cs nop|ud2|add\s+BYTE PTR \[rax\],al$)\b")
LINE = re.compile(r"^\s*[0-9a-f]+:\s+(.*?)\s*$")
SYMBOL = re.compile(r"^[0-9a-f]+ <(?:main\.)?[fF](\d+)>:$")


def parse_objdump(text, n, strip_frame=False):
    """-> list of n normalized bodies ('ins;ins;...')."""
    bodies = [None] * n
    cur = None
    acc = []
    end = [None]

    def flush():
        if cur is not None:
            ins = acc if end[0] is None else acc[:end[0]]
            end[0] = None
            if strip_frame:
                # Cranelift gives every function a frame, torn down before each return.
                ins = [x for x in ins if x not in ("push rbp", "mov rbp,rsp", "mov rsp,rbp", "pop rbp")]
            bodies[cur] = ";".join(ins)

    for line in text.split("\n"):
        m = LINE.match(line)
        if m:
            if cur is None:
                continue
            ins = m.group(1)
            if ins.startswith("ret"):
                end[0] = len(acc)  # whatever follows the last return is data or padding
            if SKIP.match(ins):
                continue
            ins = re.sub(r"^rex\s+", "", ins)
            ins = re.sub(r"\s+", " ", ins, count=1)
            ins = re.sub(r"\s*#.*$", "", ins)
            acc.append(ins)
            continue
        m = SYMBOL.match(line)
        if m:
            flush()
            cur = int(m.group(1))
            acc = []
            if cur >= n:
                cur = None
        elif line.endswith(">:"):
            flush()
            cur = None
            acc = []
    flush()
    return bodies


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, **kw)
    if r.returncode != 0:
        how = f"killed by signal {-r.returncode}" if r.returncode < 0 else f"exit status {r.returncode}"
        raise RuntimeError(f"{' '.join(map(str, cmd))}\n{how}\n{r.stderr.decode()[:2000]}")
    return r.stdout


def objdump(path):
    return run(["objdump", "-d", "-M", "intel", "--no-show-raw-insn", path]).decode()


def do_batch(args):
    name, lang, inputs, packed, check = args
    bodies, fps = compile_split(name, lang, inputs, [lang.unpack(p) for p in packed], check)
    uniq = {}
    ids = np.empty(len(packed), dtype=np.uint32)
    for i, b in enumerate(bodies):
        ids[i] = uniq.setdefault(b, len(uniq))
    return ids, list(uniq), fps


def compile_split(name, lang, inputs, terms, check, retry=True):
    """Compile a batch; if the compiler itself fails, halve the batch until
    the functions it can't compile are isolated. Their body is '!' plus the
    first line of the compiler's complaint."""
    try:
        return compile_batch(name, lang, inputs, terms, check)
    except RuntimeError as e:
        if retry:
            # Try once more before blaming the compiler: transient failures
            # (out of memory, a killed process) shouldn't end up as results.
            return compile_split(name, lang, inputs, terms, check, retry=False)
        if not re.search(r"internal compiler error|Segmentation fault|panic|Killed|signal", str(e)):
            raise  # the source was rejected: that's a bug here, not in the compiler
        if len(terms) == 1:
            msg = [l for l in str(e).split("\n")[1:] if l.strip() and not l.startswith("#")]
            fps = np.zeros(1, dtype=np.uint64) if check else None
            return ["!" + (msg[0] if msg else "failed")[:200]], fps
        h = len(terms) // 2
        b1, f1 = compile_split(name, lang, inputs, terms[:h], check)
        b2, f2 = compile_split(name, lang, inputs, terms[h:], check)
        return b1 + b2, (np.concatenate([f1, f2]) if check else None)


def compile_batch(name, lang, inputs, terms, check):
    kind, cmd = COMPILERS[name]
    n = len(terms)
    nv = lang.nv
    d = tempfile.mkdtemp(prefix="pc_", dir="/dev/shm")
    try:
        fps = None
        if kind == "c":
            params = ", ".join(f"uint32_t {VARS[i]}" for i in range(nv))
            with open(f"{d}/b.c", "w") as f:
                f.write("#include <stdint.h>\n")
                for i, t in enumerate(terms):
                    f.write(f"uint32_t f{i}({params}){{return {c_expr(lang, t)};}}\n")
            run(cmd + CFLAGS + ["-c", "b.c", "-o", "b.o"], cwd=d)
            bodies = parse_objdump(objdump(f"{d}/b.o"), n)
            if check:
                with open(f"{d}/m.c", "w") as f:
                    f.write(FP_C % dict(
                        params=", ".join(["uint32_t"] * nv), nv=nv,
                        decls="".join(f"uint32_t f{i}({params});\n" for i in range(n)),
                        names=",".join(f"f{i}" for i in range(n)),
                        inputs=",".join("{" + ",".join(f"{v}u" for v in row) + "}" for row in inputs),
                        args=", ".join(f"in[t][{i}]" for i in range(nv))))
                run(["gcc", "-O1", "m.c", "b.o", "-o", "m"], cwd=d)
                fps = np.frombuffer(run([f"{d}/m"]), dtype=np.uint64)
        elif kind == "go":
            params = ", ".join(VARS[i] for i in range(nv)) + " uint32"
            with open(f"{d}/main.go", "w") as f:
                f.write('package main\n\nimport "os"\n\n'
                        "func b2i(b bool) uint32 {\n\tif b {\n\t\treturn 1\n\t}\n\treturn 0\n}\n\n")
                for i, t in enumerate(terms):
                    f.write(f"//go:noinline\nfunc F{i}({params}) uint32 {{ return {go_expr(lang, t)} }}\n")
                f.write(f"var tab = []func({', '.join(['uint32'] * nv)}) uint32{{" + ",".join(f"F{i}" for i in range(n)) + "}\n")
                f.write(FP_GO % dict(
                    nv=nv,
                    inputs=",".join("{" + ",".join(str(v) for v in row) + "}" for row in inputs),
                    args=", ".join(f"v[{i}]" for i in range(nv))))
            with open(f"{d}/go.mod", "w") as f:
                f.write("module b\n\ngo 1.21\n")
            env = dict(os.environ, GOFLAGS="-buildvcs=false", GOMAXPROCS="2")
            run(cmd + ["build", "-o", "m", "."], cwd=d, env=env)
            bodies = parse_objdump(objdump(f"{d}/m"), n)
            if check:
                fps = np.frombuffer(run([f"{d}/m"]), dtype=np.uint64)
        elif kind == "wat":
            # The module carries its own checker: _start calls every function
            # on every test input and writes the fingerprints to stdout.
            params = " ".join("(param i32)" for _ in range(nv))
            T = len(inputs)
            data = "".join("".join(f"\\{b:02x}" for b in int(v).to_bytes(4, "little")) for row in inputs for v in row)
            IN, OUT = 1024, 1024 + 4 * nv * T + 64
            pages = (OUT + 8 * n) // 65536 + 1
            args = " ".join(f"(i32.load (i32.add (i32.const {IN + 4 * v}) (i32.mul (local.get $t) (i32.const {4 * nv}))))" for v in range(nv))
            with open(f"{d}/b.wat", "w") as f:
                f.write('(module\n(import "wasi_snapshot_preview1" "fd_write" (func $w (param i32 i32 i32 i32) (result i32)))\n')
                f.write(f"(type $f (func {params} (result i32)))\n(memory (export \"memory\") {pages})\n")
                f.write(f"(table {n} funcref)\n(elem (i32.const 0) {' '.join(f'$f{i}' for i in range(n))})\n")
                for i, t in enumerate(terms):
                    f.write(f"(func $f{i} {params} (result i32) {wat_expr(lang, t)})\n")
                f.write(f"""(data (i32.const {IN}) "{data}")
(func (export "_start") (local $i i32) (local $t i32) (local $h i64)
  (loop $fi
    (local.set $h (i64.const 0x243F6A8885A308D3))
    (local.set $t (i32.const 0))
    (loop $ti
      (local.set $h (i64.mul (i64.xor (local.get $h) (i64.extend_i32_u (call_indirect (type $f) {args} (local.get $i)))) (i64.const 0x9E3779B97F4A7C15)))
      (local.set $h (i64.xor (local.get $h) (i64.shr_u (local.get $h) (i64.const 32))))
      (local.set $t (i32.add (local.get $t) (i32.const 1)))
      (br_if $ti (i32.lt_u (local.get $t) (i32.const {T}))))
    (local.set $h (i64.mul (i64.xor (local.get $h) (i64.shr_u (local.get $h) (i64.const 29))) (i64.const 0xBF58476D1CE4E5B9)))
    (local.set $h (i64.xor (local.get $h) (i64.shr_u (local.get $h) (i64.const 32))))
    (if (i64.eqz (local.get $h)) (then (local.set $h (i64.const 1))))
    (i64.store (i32.add (i32.const {OUT}) (i32.shl (local.get $i) (i32.const 3))) (local.get $h))
    (local.set $i (i32.add (local.get $i) (i32.const 1)))
    (br_if $fi (i32.lt_u (local.get $i) (i32.const {n}))))
  (i32.store (i32.const 0) (i32.const {OUT}))
  (i32.store (i32.const 4) (i32.const {8 * n}))
  (drop (call $w (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 16))))
)
""")
            run(cmd + ["compile", "-O", "opt-level=2", "b.wat", "-o", "b.cwasm"], cwd=d)
            text = objdump(f"{d}/b.cwasm")
            # Function 0 is the import.
            text = re.sub(r"<wasm\[0\]::function\[\d+\]::f(\d+)>:", r"<f\1>:", text)
            bodies = parse_objdump(text, n, strip_frame=True)
            if check:
                fps = np.frombuffer(run(cmd + ["run", "--allow-precompiled", "b.cwasm"], cwd=d), dtype=np.uint64)
        missing = [i for i, b in enumerate(bodies) if b is None]
        if missing:
            raise RuntimeError(f"{name}: no code found for {len(missing)} functions, e.g. #{missing[0]}")
        return bodies, fps
    finally:
        shutil.rmtree(d, ignore_errors=True)


def confirm_wrong(name, lang, inputs, packed, fp, wrong):
    """A wrong result only counts if it happens again with the function
    compiled on its own."""
    kept = []
    for i in wrong:
        _, fps = compile_split(name, lang, inputs, [lang.unpack(packed[i])], True)
        if fps[0] != fp[i]:
            kept.append(i)
    return kept


def load_census(rundir):
    """-> (packed, fp, key, cost) arrays over all sizes, in file order."""
    with open(f"{rundir}/meta.json") as f:
        meta = json.load(f)
    parts = [np.fromfile(f"{rundir}/census{k}.bin", dtype=np.uint64).reshape(-1, 4)
             for k in range(1, meta["k"] + 1)]
    cen = np.concatenate(parts)
    return cen[:, 0], cen[:, 1], cen[:, 2], cen[:, 3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("compiler")
    ap.add_argument("--jobs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=4000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--recheck", action="store_true", help="only re-test the wrong results already recorded")
    a = ap.parse_args()

    lang = Lang.load(a.run)
    inputs = [list(map(int, l.split())) for l in open(f"{a.run}/inputs.txt")]
    packed, fp, _, _ = load_census(a.run)
    if a.limit:
        packed, fp = packed[:a.limit], fp[:a.limit]
    n = len(packed)
    if a.recheck:
        path = f"{a.run}/asm/{a.compiler}.wrong.json"
        wrong = json.load(open(path))
        kept = confirm_wrong(a.compiler, lang, inputs, packed, fp, wrong)
        print(f"{a.compiler}: {len(kept)} of {len(wrong)} wrong results reproduce", file=sys.stderr)
        json.dump(kept, open(path, "w"))
        return
    os.makedirs(f"{a.run}/asm", exist_ok=True)
    jobs = [(a.compiler, lang, inputs, packed[i:i + a.batch], not a.no_check)
            for i in range(0, n, a.batch)]
    ids = np.empty(n, dtype=np.uint32)
    table = {}
    wrong = []
    t0 = time.time()
    done = 0
    with mp.Pool(a.jobs) as pool:
        for bi, (bids, bodies, fps) in enumerate(pool.imap(do_batch, jobs, chunksize=1)):
            lo = bi * a.batch
            remap = np.array([table.setdefault(b, len(table)) for b in bodies], dtype=np.uint32)
            ids[lo:lo + len(bids)] = remap[bids]
            if fps is not None:
                bad = np.nonzero((fps != fp[lo:lo + len(bids)]) & (fps != 0))[0]
                wrong.extend(int(lo + i) for i in bad)
            done += len(bids)
            if bi % 200 == 0:
                el = time.time() - t0
                print(f"\r{a.compiler}: {done}/{n}  {done / max(el, 1e-9):.0f}/s  {len(table)} distinct bodies  {len(wrong)} wrong",
                      end="", file=sys.stderr, flush=True)
    print(f"\r{a.compiler}: {n} functions in {time.time() - t0:.0f}s, {len(table)} distinct bodies, {len(wrong)} wrong results" + " " * 20,
          file=sys.stderr)
    if wrong:
        kept = confirm_wrong(a.compiler, lang, inputs, packed, fp, wrong)
        print(f"{a.compiler}: {len(kept)} of {len(wrong)} wrong results reproduce", file=sys.stderr)
        wrong = kept
    np.save(f"{a.run}/asm/{a.compiler}.ids.npy", ids)
    with open(f"{a.run}/asm/{a.compiler}.bodies.json", "w") as f:
        json.dump(list(table), f)
    with open(f"{a.run}/asm/{a.compiler}.wrong.json", "w") as f:
        json.dump(wrong, f)
    if wrong:
        from terms import infix
        for i in wrong[:20]:
            print("  WRONG:", infix(lang, lang.unpack(packed[i])), file=sys.stderr)


if __name__ == "__main__":
    main()
