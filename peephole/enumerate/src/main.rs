//! Enumerate every small integer expression, and sort them into piles that
//! compute the same function.
//!
//! An expression is a DAG over u32: leaves are the variables and a small pool
//! of constants, interior nodes are add/sub/mul/and/or/xor and shifts by a
//! constant amount. Its size is the number of distinct interior nodes, i.e.
//! the number of instructions once common subexpressions are shared.
//!
//! Each DAG is visited exactly once, as a straight-line program in a
//! canonical order. Its function is fingerprinted by running it on a fixed
//! set of inputs. A table from fingerprint to the smallest size seen gives
//! the exact cost of every function reachable in K instructions.
//!
//! What gets written out ("the census"):
//!   - every optimal expression (nothing smaller computes the same function)
//!   - every primitive non-optimal one: something smaller exists, but every
//!     proper subexpression is already optimal. These are the left-hand
//!     sides of the rewrite rules a perfect peephole optimizer would need.
//! Of each pair of expressions that differ only by renaming the variables,
//! one is kept.

use rayon::prelude::*;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::sync::atomic::{AtomicU64, AtomicU8, Ordering::Relaxed};
use std::sync::Mutex;

const T: usize = 160; // test inputs
const MAXK: usize = 5;
const MAXL: usize = 16; // operand indices fit in 4 bits

const ADD: u8 = 0;
const MUL: u8 = 1;
const AND: u8 = 2;
const OR: u8 = 3;
const XOR: u8 = 4;
const SUB: u8 = 5;
const SHL: u8 = 6;
const LSHR: u8 = 7;
const ASHR: u8 = 8;
const EQ: u8 = 9;
const NE: u8 = 10;
const LTS: u8 = 11;
const LTU: u8 = 12;
const LES: u8 = 13;
const LEU: u8 = 14;
const SMIN: u8 = 15;
const SMAX: u8 = 16;
const UMIN: u8 = 17;
const UMAX: u8 = 18;
const OP_NAMES: [&str; 19] = [
    "add", "mul", "and", "or", "xor", "sub", "shl", "lshr", "ashr", "eq", "ne", "lts", "ltu", "les", "leu",
    "smin", "smax", "umin", "umax",
];

type Vals = [u32; T];
type Ins = (u8, u8, u8);

struct Cfg {
    nv: usize,
    consts: Vec<u32>,
    shifts: Vec<u32>,
    ops: Vec<u8>,
    k: usize,
    inputs: Vec<Vals>,   // per variable
    mirror: Vec<Vec<usize>>, // for each variable permutation, where each test input goes
    perms: Vec<Vec<usize>>,
    leaf_hash: Vec<u64>,
    emit_opt_max: usize, // write optimal expressions up to this size
    neg_in_pool: Vec<bool>, // per constant: is its negation also in the pool
    ibits: u32,
}

impl Cfg {
    fn nleaf(&self) -> usize {
        self.nv + self.consts.len()
    }
}

fn splitmix(x: &mut u64) -> u64 {
    *x = x.wrapping_add(0x9E3779B97F4A7C15);
    let mut z = *x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

fn mix(a: u64, b: u64) -> u64 {
    let mut s = a ^ b.rotate_left(23).wrapping_mul(0x9E3779B97F4A7C15);
    splitmix(&mut s)
}

/// Fingerprint of a function: a hash of its outputs on the test inputs.
#[inline]
fn fingerprint(v: &Vals) -> u64 {
    let mut h: u64 = 0x243F6A8885A308D3;
    for &x in v.iter() {
        h = (h ^ x as u64).wrapping_mul(0x9E3779B97F4A7C15);
        h ^= h >> 32;
    }
    h = (h ^ (h >> 29)).wrapping_mul(0xBF58476D1CE4E5B9);
    h ^= h >> 32;
    if h == 0 {
        1
    } else {
        h
    }
}

fn fingerprint_perm(v: &Vals, m: &[usize]) -> u64 {
    let mut w = [0u32; T];
    for i in 0..T {
        w[i] = v[m[i]];
    }
    fingerprint(&w)
}

#[inline]
fn is_const(v: &Vals) -> bool {
    let a = v[0];
    v.iter().all(|&x| x == a)
}

#[inline]
fn eval(op: u8, a: &Vals, b: &Vals, sh: u32, out: &mut Vals) {
    match op {
        ADD => (0..T).for_each(|i| out[i] = a[i].wrapping_add(b[i])),
        MUL => (0..T).for_each(|i| out[i] = a[i].wrapping_mul(b[i])),
        AND => (0..T).for_each(|i| out[i] = a[i] & b[i]),
        OR => (0..T).for_each(|i| out[i] = a[i] | b[i]),
        XOR => (0..T).for_each(|i| out[i] = a[i] ^ b[i]),
        SUB => (0..T).for_each(|i| out[i] = a[i].wrapping_sub(b[i])),
        SHL => (0..T).for_each(|i| out[i] = a[i] << sh),
        LSHR => (0..T).for_each(|i| out[i] = a[i] >> sh),
        ASHR => (0..T).for_each(|i| out[i] = ((a[i] as i32) >> sh) as u32),
        EQ => (0..T).for_each(|i| out[i] = (a[i] == b[i]) as u32),
        NE => (0..T).for_each(|i| out[i] = (a[i] != b[i]) as u32),
        LTS => (0..T).for_each(|i| out[i] = ((a[i] as i32) < (b[i] as i32)) as u32),
        LTU => (0..T).for_each(|i| out[i] = (a[i] < b[i]) as u32),
        LES => (0..T).for_each(|i| out[i] = ((a[i] as i32) <= (b[i] as i32)) as u32),
        LEU => (0..T).for_each(|i| out[i] = (a[i] <= b[i]) as u32),
        SMIN => (0..T).for_each(|i| out[i] = (a[i] as i32).min(b[i] as i32) as u32),
        SMAX => (0..T).for_each(|i| out[i] = (a[i] as i32).max(b[i] as i32) as u32),
        UMIN => (0..T).for_each(|i| out[i] = a[i].min(b[i])),
        UMAX => (0..T).for_each(|i| out[i] = a[i].max(b[i])),
        _ => unreachable!(),
    }
}

fn commutative(op: u8) -> bool {
    op <= XOR || op == EQ || op == NE || op >= SMIN
}
fn is_shift(op: u8) -> bool {
    op >= SHL && op <= ASHR
}

/// Function table: fingerprint -> (cost, smallest optimal expression).
struct Table {
    mask: usize,
    keys: Vec<AtomicU64>,
    cost: Vec<AtomicU8>,
    rep: Vec<AtomicU64>,
}

impl Table {
    fn new(bits: u32) -> Table {
        let n = 1usize << bits;
        Table {
            mask: n - 1,
            keys: (0..n).into_par_iter().map(|_| AtomicU64::new(0)).collect(),
            cost: (0..n).into_par_iter().map(|_| AtomicU8::new(0)).collect(),
            rep: (0..n).into_par_iter().map(|_| AtomicU64::new(u64::MAX)).collect(),
        }
    }
    #[inline]
    fn get(&self, fp: u64) -> Option<u8> {
        let mut i = (fp as usize) & self.mask;
        loop {
            let k = self.keys[i].load(Relaxed);
            if k == fp {
                return Some(self.cost[i].load(Relaxed));
            }
            if k == 0 {
                return None;
            }
            i = (i + 1) & self.mask;
        }
    }
    /// Record that `fp` is computable at `cost` by `rep`. Only ever called
    /// with one cost per pass, and lower costs are already in the table, so
    /// the first cost written for a key is its minimum.
    #[inline]
    fn insert(&self, fp: u64, cost: u8, rep: u64) -> u8 {
        let mut i = (fp as usize) & self.mask;
        loop {
            let k = self.keys[i].load(Relaxed);
            if k == 0 {
                // The cost is written before the key is published. Two
                // threads racing for an empty slot both write the same cost.
                self.cost[i].store(cost, Relaxed);
                match self.keys[i].compare_exchange(0, fp, Relaxed, Relaxed) {
                    Ok(_) => {
                        self.rep[i].fetch_min(rep, Relaxed);
                        return cost;
                    }
                    Err(_) => continue,
                }
            }
            if k == fp {
                let c = self.cost[i].load(Relaxed);
                if c == cost {
                    self.rep[i].fetch_min(rep, Relaxed);
                }
                return c;
            }
            i = (i + 1) & self.mask;
        }
    }
}

#[derive(Clone)]
struct St {
    n: usize,
    ins: [Ins; MAXK],
    vals: Vec<Vals>,
    sh: [u64; MAXL + MAXK],
    used: u32,
    reach: [u32; MAXK],
    sub_opt: bool, // every instruction so far is the root of an optimal expression
}

/// One instruction is `ibits` bits: op, then 4 bits for each operand. 12
/// when the op fits in 4 bits, else 13. The length goes on top.
fn pack(ins: &[Ins], ibits: u32) -> u64 {
    let mut p = ins.len() as u64;
    for &(op, a, b) in ins {
        p = (p << ibits) | ((op as u64) << 8) | ((a as u64) << 4) | b as u64;
    }
    p
}

struct Ctx<'a> {
    cfg: &'a Cfg,
    table: &'a Table,
    target: usize,
    /// When set, stop at this many instructions and collect the states
    /// instead of searching on: used to cut the search into parallel tasks.
    split: Option<(usize, &'a Mutex<Vec<St>>)>,
}

#[derive(Default)]
struct Out {
    buf: Vec<u8>,
    n_canon: u64,
    n_opt: u64,
    n_nonopt: u64,
    n_prim: u64,
    n_emit: u64,
    n_const: u64,
}

impl<'a> Ctx<'a> {
    fn struct_hash(&self, st: &St, op: u8, a: u8, b: u8) -> u64 {
        if is_shift(op) {
            mix(mix(op as u64 + 100, st.sh[a as usize]), b as u64 + 1000)
        } else {
            mix(mix(op as u64 + 100, st.sh[a as usize]), st.sh[b as usize])
        }
    }

    /// Is the program the canonical ordering of its DAG: instructions in
    /// post-order from the root, left operand first?
    fn canonical(&self, st: &St) -> bool {
        let l = self.cfg.nleaf();
        let n = st.n;
        let mut next = 0usize;
        let mut seen = 0u32;
        // Explicit stack: (instr, stage)
        let mut stack: [(u8, u8); 2 * MAXK + 2] = [(0, 0); 2 * MAXK + 2];
        let mut sp = 0;
        stack[sp] = ((n - 1) as u8, 0);
        sp += 1;
        while sp > 0 {
            let (j, stage) = stack[sp - 1];
            let (op, a, b) = st.ins[j as usize];
            if stage == 0 {
                stack[sp - 1].1 = 1;
                let a = a as usize;
                if a >= l && seen & (1 << (a - l)) == 0 {
                    stack[sp] = ((a - l) as u8, 0);
                    sp += 1;
                }
            } else if stage == 1 {
                stack[sp - 1].1 = 2;
                let b = b as usize;
                if !is_shift(op) && b >= l && seen & (1 << (b - l)) == 0 {
                    stack[sp] = ((b - l) as u8, 0);
                    sp += 1;
                }
            } else {
                sp -= 1;
                if seen & (1 << j) != 0 {
                    continue;
                }
                if j as usize != next {
                    return false;
                }
                next += 1;
                seen |= 1 << j;
            }
        }
        next == n
    }

    /// An instruction nobody would write: a neutral or absorbing constant
    /// (x+0, x*1, x&0, ...), an operand combined with itself to no effect
    /// (x&x, x-x), or a second spelling of adding a constant (x - c when -c
    /// is in the pool).
    fn pointless(&self, op: u8, a: usize, b: usize) -> bool {
        let cfg = self.cfg;
        let l = cfg.nleaf();
        let cv = |i: usize| -> Option<u32> {
            if i >= cfg.nv && i < l {
                Some(cfg.consts[i - cfg.nv])
            } else {
                None
            }
        };
        if a == b && (matches!(op, AND | OR | XOR | SUB) || op >= EQ) {
            return true;
        }
        // Unsigned comparisons and min/max against 0 or all-ones are
        // decided before they start.
        match (op, cv(a), cv(b)) {
            (LTU, _, Some(0)) | (LTU, Some(u32::MAX), _) | (LEU, Some(0), _) | (LEU, _, Some(u32::MAX)) => return true,
            (UMIN | UMAX, Some(0 | u32::MAX), _) | (UMIN | UMAX, _, Some(0 | u32::MAX)) => return true,
            _ => {}
        }
        if op == SUB {
            return match cv(b) {
                Some(_) => cfg.neg_in_pool[b - cfg.nv],
                None => false,
            };
        }
        for c in [cv(a), cv(b)].into_iter().flatten() {
            let bad = match op {
                ADD | XOR => c == 0,
                MUL => c == 0 || c == 1,
                AND | OR => c == 0 || c == u32::MAX,
                _ => false,
            };
            if bad {
                return true;
            }
        }
        false
    }

    fn dfs(&self, st: &mut St, out: &mut Out) {
        let cfg = self.cfg;
        let l = cfg.nleaf();
        let i = st.n;
        let navail = l + i;
        let remaining_after = self.target - (i + 1);
        let last = remaining_after == 0;
        for &op in &cfg.ops {
            if is_shift(op) {
                for a in 0..navail {
                    if a >= cfg.nv && a < l {
                        continue; // shifting a constant is a constant
                    }
                    for s in 0..cfg.shifts.len() {
                        self.try_ins(st, out, (op, a as u8, s as u8), last, remaining_after);
                    }
                }
            } else {
                for a in 0..navail {
                    for b in 0..navail {
                        let ac = a >= cfg.nv && a < l;
                        let bc = b >= cfg.nv && b < l;
                        if ac && bc {
                            continue;
                        }
                        if commutative(op) && st.sh[a] > st.sh[b] {
                            continue;
                        }
                        if self.pointless(op, a, b) {
                            continue;
                        }
                        self.try_ins(st, out, (op, a as u8, b as u8), last, remaining_after);
                    }
                }
            }
        }
    }

    #[inline]
    fn try_ins(&self, st: &mut St, out: &mut Out, ins: Ins, last: bool, remaining_after: usize) {
        let cfg = self.cfg;
        let l = cfg.nleaf();
        let i = st.n;
        let (op, a, b) = ins;
        let (a_us, b_us) = (a as usize, b as usize);
        // No instruction twice.
        if st.ins[..i].contains(&ins) {
            return;
        }
        let mut used = st.used;
        let mut reach = 1u32 << i;
        if a_us >= l {
            used |= 1 << (a_us - l);
            reach |= st.reach[a_us - l];
        }
        if !is_shift(op) && b_us >= l {
            used |= 1 << (b_us - l);
            reach |= st.reach[b_us - l];
        }
        // Every instruction must end up feeding the result.
        let unused = (i + 1) as u32 - used.count_ones();
        if unused as usize > 1 + remaining_after {
            return;
        }
        st.ins[i] = ins;
        st.n = i + 1;
        if last && !self.canonical(st) {
            st.n = i;
            return;
        }
        let sh_amt = if is_shift(op) { cfg.shifts[b_us] } else { 0 };
        {
            let (lo, hi) = st.vals.split_at_mut(l + i);
            let bv = if is_shift(op) { &lo[a_us] } else { &lo[b_us] };
            eval(op, &lo[a_us], bv, sh_amt, &mut hi[0]);
        }
        let v = &st.vals[l + i];
        let fp = fingerprint(v);
        let size = reach.count_ones() as u8;
        if last {
            out.n_canon += 1;
            let p = pack(&st.ins[..st.n], cfg.ibits);
            let cost = if is_const(v) {
                out.n_const += 1;
                0
            } else {
                self.table.insert(fp, size, p)
            };
            let optimal = cost == size;
            if optimal {
                out.n_opt += 1;
            } else {
                out.n_nonopt += 1;
                if st.sub_opt {
                    out.n_prim += 1;
                }
            }
            let want = if optimal {
                st.n <= cfg.emit_opt_max
            } else {
                st.sub_opt
            };
            if want {
                self.emit(st, out, fp, cost, p);
            }
        } else {
            let cost = if is_const(v) {
                0
            } else {
                self.table.get(fp).expect("smaller expression missing from table")
            };
            let saved = (st.used, st.sub_opt);
            st.used = used;
            st.reach[i] = reach;
            st.sub_opt = saved.1 && cost == size;
            st.sh[l + i] = self.struct_hash(st, op, a, b);
            match self.split {
                Some((depth, acc)) if st.n == depth => acc.lock().unwrap().push(st.clone()),
                _ => self.dfs(st, out),
            }
            st.used = saved.0;
            st.sub_opt = saved.1;
        }
        st.n = i;
    }

    /// Write a census record, unless a variable renaming of this expression
    /// is the one that represents it.
    fn emit(&self, st: &St, out: &mut Out, fp: u64, cost: u8, p: u64) {
        let cfg = self.cfg;
        let l = cfg.nleaf();
        let v = &st.vals[l + st.n - 1];
        let ins = &st.ins[..st.n];
        // Which variables appear, and the smallest packing over renamings.
        let mut key = fp;
        let mut best = p;
        for (pi, perm) in cfg.perms.iter().enumerate().skip(1) {
            let q = canon_renamed(cfg, ins, perm);
            if q < best {
                best = q;
            }
            let f = fingerprint_perm(v, &cfg.mirror[pi]);
            if f < key {
                key = f;
            }
        }
        if best != p {
            return;
        }
        out.n_emit += 1;
        out.buf.extend_from_slice(&p.to_le_bytes());
        out.buf.extend_from_slice(&fp.to_le_bytes());
        out.buf.extend_from_slice(&key.to_le_bytes());
        out.buf.extend_from_slice(&(cost as u64).to_le_bytes());
    }
}

/// Canonical packing of the expression with its variables renamed by `perm`.
fn canon_renamed(cfg: &Cfg, ins: &[Ins], perm: &[usize]) -> u64 {
    let l = cfg.nleaf();
    let n = ins.len();
    let ren = |x: u8| -> u8 {
        if (x as usize) < cfg.nv {
            perm[x as usize] as u8
        } else {
            x
        }
    };
    // Structural hashes under the renaming.
    let mut sh = [0u64; MAXL + MAXK];
    sh[..l].copy_from_slice(&cfg.leaf_hash[..l]);
    let mut r: [Ins; MAXK] = [(0, 0, 0); MAXK];
    for j in 0..n {
        let (op, a, b) = ins[j];
        let a = ren(a);
        if is_shift(op) {
            sh[l + j] = mix(mix(op as u64 + 100, sh[a as usize]), b as u64 + 1000);
            r[j] = (op, a, b);
        } else {
            let b = ren(b);
            let (a, b) = if commutative(op) && sh[a as usize] > sh[b as usize] {
                (b, a)
            } else {
                (a, b)
            };
            sh[l + j] = mix(mix(op as u64 + 100, sh[a as usize]), sh[b as usize]);
            r[j] = (op, a, b);
        }
    }
    // Post-order from the root.
    let mut order: Vec<usize> = Vec::with_capacity(n);
    let mut newidx = [usize::MAX; MAXK];
    fn visit(j: usize, l: usize, r: &[Ins; MAXK], newidx: &mut [usize; MAXK], order: &mut Vec<usize>) {
        if newidx[j] != usize::MAX {
            return;
        }
        let (op, a, b) = r[j];
        if a as usize >= l {
            visit(a as usize - l, l, r, newidx, order);
        }
        if !is_shift(op) && b as usize >= l {
            visit(b as usize - l, l, r, newidx, order);
        }
        newidx[j] = order.len();
        order.push(j);
    }
    visit(n - 1, l, &r, &mut newidx, &mut order);
    let mut outp: Vec<Ins> = Vec::with_capacity(n);
    for &j in &order {
        let (op, a, b) = r[j];
        let fix = |x: u8| -> u8 {
            if x as usize >= l {
                (l + newidx[x as usize - l]) as u8
            } else {
                x
            }
        };
        outp.push(if is_shift(op) { (op, fix(a), b) } else { (op, fix(a), fix(b)) });
    }
    pack(&outp, cfg.ibits)
}

fn permutations(n: usize) -> Vec<Vec<usize>> {
    fn go(cur: &mut Vec<usize>, n: usize, out: &mut Vec<Vec<usize>>) {
        if cur.len() == n {
            out.push(cur.clone());
            return;
        }
        for i in 0..n {
            if !cur.contains(&i) {
                cur.push(i);
                go(cur, n, out);
                cur.pop();
            }
        }
    }
    let mut out = vec![];
    go(&mut vec![], n, &mut out);
    out
}

/// Test inputs: every combination of a few corner values, then random and
/// sparse-random tuples. The set is closed under permuting the variables, so
/// the fingerprint of a renamed function can be read off the same outputs.
fn make_inputs(nv: usize) -> (Vec<Vals>, Vec<Vec<usize>>, Vec<Vec<usize>>) {
    let (cols, mirror, perms) =
        make_inputs_n(nv, T, &[0, 1, 0xFFFF_FFFF, 0x8000_0000, 0x7FFF_FFFF, 2], if nv <= 2 { 6 } else { 3 }, 0x5EED_5EED_5EED_5EED);
    let mut inputs = vec![[0u32; T]; nv];
    for v in 0..nv {
        inputs[v].copy_from_slice(&cols[v]);
    }
    (inputs, mirror, perms)
}

fn make_inputs_n(
    nv: usize,
    count: usize,
    corners: &[u32],
    ncorner: usize,
    seed0: u64,
) -> (Vec<Vec<u32>>, Vec<Vec<usize>>, Vec<Vec<usize>>) {
    let perms = permutations(nv);
    let mut tuples: Vec<Vec<u32>> = vec![];
    let mut seen = std::collections::HashSet::new();
    let mut add_closed = |t: Vec<u32>, tuples: &mut Vec<Vec<u32>>| {
        for p in &perms {
            let q: Vec<u32> = (0..nv).map(|i| t[p[i]]).collect();
            if seen.insert(q.clone()) {
                tuples.push(q);
            }
        }
    };
    let mut idx = vec![0usize; nv];
    loop {
        add_closed(idx.iter().map(|&i| corners[i]).collect(), &mut tuples);
        let mut d = 0;
        loop {
            idx[d] += 1;
            if idx[d] < ncorner {
                break;
            }
            idx[d] = 0;
            d += 1;
            if d == nv {
                break;
            }
        }
        if d == nv {
            break;
        }
    }
    let mut seed = seed0;
    let mut kind = 0;
    while tuples.len() < count {
        let t: Vec<u32> = (0..nv)
            .map(|_| {
                let r = splitmix(&mut seed) as u32;
                match kind % 4 {
                    0 | 1 => r,
                    2 => r & (splitmix(&mut seed) as u32) & (splitmix(&mut seed) as u32),
                    _ => r | (splitmix(&mut seed) as u32) | (splitmix(&mut seed) as u32),
                }
            })
            .collect();
        kind += 1;
        if tuples.len() + perms.len() <= count {
            add_closed(t, &mut tuples);
        } else if tuples.len() < count {
            // Pad with tuples whose coordinates are all equal (closed alone).
            add_closed(vec![t[0]; nv], &mut tuples);
        }
    }
    assert_eq!(tuples.len(), count);
    let pos: std::collections::HashMap<Vec<u32>, usize> =
        tuples.iter().cloned().enumerate().map(|(i, t)| (t, i)).collect();
    let mut inputs = vec![vec![0u32; count]; nv];
    for (i, t) in tuples.iter().enumerate() {
        for v in 0..nv {
            inputs[v][i] = t[v];
        }
    }
    // mirror[p][i] = index of the tuple that, fed to f, gives (f renamed by p)(tuple i).
    // Renaming replaces variable v by perm[v], so input v of f receives tuple[perm[v]].
    let mirror = perms
        .iter()
        .map(|p| {
            tuples
                .iter()
                .map(|t| {
                    let q: Vec<u32> = (0..nv).map(|v| t[p[v]]).collect();
                    pos[&q]
                })
                .collect()
        })
        .collect();
    (inputs, mirror, perms)
}

/// Inputs chosen to separate functions that differ only rarely: values
/// around every power of two and around thirds of the range (where carries
/// and borrows start or stop propagating), in all combinations; random
/// values paired with near-copies, near-negations and near-complements of
/// themselves; and plain random tuples. Closed under permuting variables.
fn strong_inputs(cfg: &Cfg, extra: &[Vec<u32>]) -> (Vec<Vec<u32>>, Vec<Vec<usize>>) {
    let nv = cfg.nv;
    let perms = permutations(nv);
    let mut vals: Vec<u32> = vec![];
    let dmax: i64 = if nv <= 2 { 2 } else { 1 };
    for j in 0..=32u32 {
        for d in -dmax..=dmax {
            vals.push(((1i64 << j) + d) as u32);
        }
    }
    for k in 1..=2i64 {
        for d in -1..=1i64 {
            vals.push((k * 0x5555_5555 + d) as u32);
        }
    }
    vals.extend([0xFF, 0xFE, 0x100, 0xFFFF, 0xFF00_0000, 0x00FF_FFFF, 0xFFFF_0000, 0xFFFF_FF00]);
    // Around each constant of the language, its negation and complement:
    // where `x + c` wraps or `x == c` flips.
    for &c in &cfg.consts {
        for b in [c, c.wrapping_neg(), !c] {
            for d in -2..=2i64 {
                vals.push((b as i64 + d) as u32);
            }
        }
    }
    vals.sort();
    vals.dedup();
    if nv >= 3 {
        // Too many triples otherwise.
        let keep: Vec<u32> = vals.iter().copied().filter(|v| v.wrapping_add(2).count_ones() <= 2 || v.wrapping_neg() < 3).collect();
        vals = keep;
        vals.truncate(40);
    }
    let mut tuples: Vec<Vec<u32>> = vec![];
    let mut seen = std::collections::HashSet::new();
    let mut add = |t: Vec<u32>, tuples: &mut Vec<Vec<u32>>| {
        for p in &perms {
            let q: Vec<u32> = (0..nv).map(|i| t[p[i]]).collect();
            if seen.insert(q.clone()) {
                tuples.push(q);
            }
        }
    };
    let mut idx = vec![0usize; nv];
    'outer: loop {
        add(idx.iter().map(|&i| vals[i]).collect(), &mut tuples);
        for d in 0..nv {
            idx[d] += 1;
            if idx[d] < vals.len() {
                continue 'outer;
            }
            idx[d] = 0;
        }
        break;
    }
    let mut seed = 0xABCD_EF01_2345_6789u64;
    let mut rnd = |kind: u32| -> u32 {
        let r = splitmix(&mut seed) as u32;
        match kind % 4 {
            0 | 1 => r,
            2 => r & (splitmix(&mut seed) as u32) & (splitmix(&mut seed) as u32),
            _ => r | (splitmix(&mut seed) as u32) | (splitmix(&mut seed) as u32),
        }
    };
    for i in 0..2000u32 {
        let r = rnd(i);
        for d in -2..=2i32 {
            for base in [r, r.wrapping_neg(), !r] {
                let mut t: Vec<u32> = (0..nv).map(|_| base.wrapping_add(d as u32)).collect();
                t[0] = r;
                add(t.clone(), &mut tuples);
                if nv >= 3 {
                    t[1] = rnd(i);
                    add(t, &mut tuples);
                }
            }
        }
    }
    for i in 0..20000u32 {
        add((0..nv).map(|_| rnd(i)).collect(), &mut tuples);
    }
    for t in extra {
        add(t.clone(), &mut tuples);
    }
    let pos: std::collections::HashMap<Vec<u32>, usize> =
        tuples.iter().cloned().enumerate().map(|(i, t)| (t, i)).collect();
    let inputs = (0..nv).map(|v| tuples.iter().map(|t| t[v]).collect()).collect();
    let mirror = perms
        .iter()
        .map(|p| tuples.iter().map(|t| pos[&(0..nv).map(|v| t[p[v]]).collect::<Vec<u32>>()]).collect())
        .collect();
    (inputs, mirror)
}

/// A much stronger class key for every census record: the function's outputs
/// on a second, larger set of inputs, minimized over variable renamings.
/// Written to OUT/key2.bin, one u64 per record, sizes 1..k concatenated.
fn rekey(cfg: &Cfg, outdir: &str) {
    // Inputs that separated two expressions the tests had lumped together
    // (verify.py finds them with an SMT solver) join the test set.
    let extra: Vec<Vec<u32>> = std::fs::read_to_string(format!("{outdir}/cex.txt"))
        .unwrap_or_default()
        .lines()
        .map(|l| l.split_whitespace().map(|x| x.parse().unwrap()).collect())
        .collect();
    eprintln!("{} extra inputs", extra.len());
    let (inputs, mirror) = strong_inputs(cfg, &extra);
    #[allow(non_snake_case)]
    let T2 = inputs[0].len();
    let l = cfg.nleaf();
    let mut all: Vec<u8> = vec![];
    for k in 1..=cfg.k {
        all.extend(std::fs::read(format!("{outdir}/census{k}.bin")).unwrap());
    }
    let n = all.len() / 32;
    let keys: Vec<u64> = (0..n)
        .into_par_iter()
        .map_init(
            || vec![vec![0u32; T2]; l + MAXK],
            |vals, r| {
                if vals[l - 1][0] == 0 && vals[0][T2 - 1] == 0 {
                    for v in 0..cfg.nv {
                        vals[v].copy_from_slice(&inputs[v]);
                    }
                    for (c, &cv) in cfg.consts.iter().enumerate() {
                        vals[cfg.nv + c].iter_mut().for_each(|x| *x = cv);
                    }
                }
                let p = u64::from_le_bytes(all[r * 32..r * 32 + 8].try_into().unwrap());
                let mut len = 0;
                let ib = cfg.ibits as usize;
                for cand in 1..=MAXK {
                    if ib * cand < 64 && p >> (ib * cand) == cand as u64 {
                        len = cand;
                    }
                }
                for i in 0..len {
                    let f = (p >> (ib * (len - 1 - i))) & ((1 << ib) - 1);
                    let (op, a, b) = ((f >> 8) as u8, ((f >> 4) & 15) as usize, (f & 15) as usize);
                    let (lo, hi) = vals.split_at_mut(l + i);
                    let out = &mut hi[0];
                    let x = &lo[a];
                    if is_shift(op) {
                        let sh = cfg.shifts[b];
                        match op {
                            SHL => (0..T2).for_each(|t| out[t] = x[t] << sh),
                            LSHR => (0..T2).for_each(|t| out[t] = x[t] >> sh),
                            _ => (0..T2).for_each(|t| out[t] = ((x[t] as i32) >> sh) as u32),
                        }
                    } else {
                        let y = &lo[b];
                        match op {
                            ADD => (0..T2).for_each(|t| out[t] = x[t].wrapping_add(y[t])),
                            MUL => (0..T2).for_each(|t| out[t] = x[t].wrapping_mul(y[t])),
                            AND => (0..T2).for_each(|t| out[t] = x[t] & y[t]),
                            OR => (0..T2).for_each(|t| out[t] = x[t] | y[t]),
                            XOR => (0..T2).for_each(|t| out[t] = x[t] ^ y[t]),
                            SUB => (0..T2).for_each(|t| out[t] = x[t].wrapping_sub(y[t])),
                            EQ => (0..T2).for_each(|t| out[t] = (x[t] == y[t]) as u32),
                            NE => (0..T2).for_each(|t| out[t] = (x[t] != y[t]) as u32),
                            LTS => (0..T2).for_each(|t| out[t] = ((x[t] as i32) < (y[t] as i32)) as u32),
                            LTU => (0..T2).for_each(|t| out[t] = (x[t] < y[t]) as u32),
                            LES => (0..T2).for_each(|t| out[t] = ((x[t] as i32) <= (y[t] as i32)) as u32),
                            LEU => (0..T2).for_each(|t| out[t] = (x[t] <= y[t]) as u32),
                            SMIN => (0..T2).for_each(|t| out[t] = (x[t] as i32).min(y[t] as i32) as u32),
                            SMAX => (0..T2).for_each(|t| out[t] = (x[t] as i32).max(y[t] as i32) as u32),
                            UMIN => (0..T2).for_each(|t| out[t] = x[t].min(y[t])),
                            _ => (0..T2).for_each(|t| out[t] = x[t].max(y[t])),
                        }
                    }
                }
                let v = &vals[l + len - 1];
                let mut best = u64::MAX;
                for m in &mirror {
                    let mut h: u64 = 0x243F6A8885A308D3;
                    for t in 0..T2 {
                        h = (h ^ v[m[t]] as u64).wrapping_mul(0x9E3779B97F4A7C15);
                        h ^= h >> 32;
                    }
                    h = (h ^ (h >> 29)).wrapping_mul(0xBF58476D1CE4E5B9);
                    h ^= h >> 32;
                    best = best.min(h);
                }
                best
            },
        )
        .collect();
    let mut f = BufWriter::new(File::create(format!("{outdir}/key2.bin")).unwrap());
    for k in &keys {
        f.write_all(&k.to_le_bytes()).unwrap();
    }
    eprintln!("rekeyed {n} records");
}

fn parse_list(s: &str) -> Vec<u32> {
    s.split(',')
        .filter(|x| !x.is_empty())
        .map(|x| {
            if let Some(h) = x.strip_prefix("0x") {
                u32::from_str_radix(h, 16).unwrap()
            } else if let Some(n) = x.strip_prefix('-') {
                (n.parse::<u32>().unwrap()).wrapping_neg()
            } else {
                x.parse().unwrap()
            }
        })
        .collect()
}

fn main() {
    let mut nv = 2;
    let mut k = 3;
    let mut consts = parse_list("0,1,-1,2,0x80000000");
    let mut shifts = parse_list("1,2,31");
    let mut ops: Vec<u8> = (0..=ASHR).collect();
    let mut outdir = String::from("out");
    let mut bits = 24u32;
    let mut emit_opt_max = usize::MAX;
    let mut do_rekey = false;
    let args: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < args.len() {
        let val = args.get(i + 1).cloned().unwrap_or_default();
        match args[i].as_str() {
            "--vars" => nv = val.parse().unwrap(),
            "--k" => k = val.parse().unwrap(),
            "--consts" => consts = parse_list(&val),
            "--shifts" => shifts = parse_list(&val),
            "--out" => outdir = val,
            "--bits" => bits = val.parse().unwrap(),
            "--emit-opt-max" => emit_opt_max = val.parse().unwrap(),
            "--ops" => {
                ops = val
                    .split(',')
                    .map(|n| OP_NAMES.iter().position(|x| *x == n).expect("unknown op") as u8)
                    .collect();
            }
            "--rekey" => {
                do_rekey = true;
                i -= 1;
            }
            other => panic!("unknown argument {other}"),
        }
        i += 2;
    }
    assert!(k <= MAXK && nv + consts.len() + k <= MAXL && shifts.len() <= 16);
    let (inputs, mirror, perms) = make_inputs(nv);
    let mut seed = 0xC0FFEEu64;
    let leaf_hash: Vec<u64> = (0..nv + consts.len()).map(|_| splitmix(&mut seed)).collect();
    let neg_in_pool = consts.iter().map(|c| consts.contains(&c.wrapping_neg())).collect();
    let ibits = if ops.iter().any(|&o| o >= 16) { 13 } else { 12 };
    assert!(4 + ibits as usize * k <= 64);
    let cfg = Cfg { nv, consts, shifts, ops, k, inputs, mirror, perms, leaf_hash, emit_opt_max, neg_in_pool, ibits };
    if do_rekey {
        rekey(&cfg, &outdir);
        return;
    }
    std::fs::create_dir_all(&outdir).unwrap();

    // The test inputs, for anything downstream that wants to re-check a function.
    {
        let mut f = BufWriter::new(File::create(format!("{outdir}/inputs.txt")).unwrap());
        for t in 0..T {
            let row: Vec<String> = (0..nv).map(|v| cfg.inputs[v][t].to_string()).collect();
            writeln!(f, "{}", row.join(" ")).unwrap();
        }
    }

    let table = Table::new(bits);
    let l = cfg.nleaf();
    let mut base = St {
        n: 0,
        ins: [(0, 0, 0); MAXK],
        vals: vec![[0u32; T]; l + MAXK],
        sh: [0; MAXL + MAXK],
        used: 0,
        reach: [0; MAXK],
        sub_opt: true,
    };
    for v in 0..nv {
        base.vals[v] = cfg.inputs[v];
        table.insert(fingerprint(&base.vals[v]), 0, 0);
    }
    for (c, &cv) in cfg.consts.iter().enumerate() {
        base.vals[nv + c] = [cv; T];
    }
    base.sh[..l].copy_from_slice(&cfg.leaf_hash);

    let mut meta = String::new();
    meta.push_str(&format!(
        "{{\"vars\":{},\"consts\":{:?},\"shifts\":{:?},\"ops\":{:?},\"k\":{},\"ibits\":{},\"levels\":[",
        nv, cfg.consts, cfg.shifts, cfg.ops, cfg.k, cfg.ibits
    ));
    let mut nfuncs_total = 0u64;
    for target in 1..=cfg.k {
        let t0 = std::time::Instant::now();
        let ctx = Ctx { cfg: &cfg, table: &table, target, split: None };
        // Cut the search into tasks at depth 2.
        let prefixes: Vec<St> = if target >= 3 {
            let acc = Mutex::new(vec![]);
            let splitter = Ctx { cfg: &cfg, table: &table, target, split: Some((2, &acc)) };
            splitter.dfs(&mut base.clone(), &mut Out::default());
            acc.into_inner().unwrap()
        } else {
            vec![base.clone()]
        };
        let file = Mutex::new(BufWriter::with_capacity(
            1 << 24,
            File::create(format!("{outdir}/census{target}.bin")).unwrap(),
        ));
        let tot = prefixes
            .into_par_iter()
            .map(|mut st| {
                let mut out = Out::default();
                ctx.dfs(&mut st, &mut out);
                if !out.buf.is_empty() {
                    file.lock().unwrap().write_all(&out.buf).unwrap();
                    out.buf = Vec::new();
                }
                out
            })
            .reduce(Out::default, |mut a, b| {
                a.n_canon += b.n_canon;
                a.n_opt += b.n_opt;
                a.n_nonopt += b.n_nonopt;
                a.n_prim += b.n_prim;
                a.n_emit += b.n_emit;
                a.n_const += b.n_const;
                a
            });
        file.lock().unwrap().flush().unwrap();
        let nfuncs = table
            .keys
            .par_iter()
            .zip(table.cost.par_iter())
            .filter(|(k, c)| k.load(Relaxed) != 0 && c.load(Relaxed) as usize == target)
            .count() as u64;
        nfuncs_total += nfuncs;
        eprintln!(
            "size {target}: {} expressions, {} functions first reached here, {} optimal, {} not ({} primitive, {} constant), {} written  [{:.1}s]",
            tot.n_canon, nfuncs, tot.n_opt, tot.n_nonopt, tot.n_prim, tot.n_const, tot.n_emit,
            t0.elapsed().as_secs_f64()
        );
        if target > 1 {
            meta.push(',');
        }
        meta.push_str(&format!(
            "{{\"size\":{},\"expressions\":{},\"functions\":{},\"optimal\":{},\"nonoptimal\":{},\"primitive\":{},\"constant\":{},\"written\":{}}}",
            target, tot.n_canon, nfuncs, tot.n_opt, tot.n_nonopt, tot.n_prim, tot.n_const, tot.n_emit
        ));
        let load = nfuncs_total as f64 / (table.mask + 1) as f64;
        assert!(load < 0.7, "table too full ({load:.2}); raise --bits");
    }
    meta.push_str("]}\n");
    std::fs::write(format!("{outdir}/meta.json"), meta).unwrap();

    // The table itself: fingerprint, cost, smallest optimal expression.
    let mut f = BufWriter::with_capacity(1 << 24, File::create(format!("{outdir}/table.bin")).unwrap());
    for i in 0..=table.mask {
        let k = table.keys[i].load(Relaxed);
        if k != 0 {
            f.write_all(&k.to_le_bytes()).unwrap();
            f.write_all(&table.rep[i].load(Relaxed).to_le_bytes()).unwrap();
            f.write_all(&(table.cost[i].load(Relaxed) as u64).to_le_bytes()).unwrap();
        }
    }
}
