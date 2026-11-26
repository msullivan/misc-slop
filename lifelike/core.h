// Shared between the OpenCL kernel and the CPU reference: one job = one rule, one seed.
// Includer defines u64, u32, CLZ64, CTZ64, POP64.
// Rule = B bits (bit n: birth on n neighbours) | S bits << 9.
// Patterns are stored XOR the vacuum state, so B0 rules (strobing or inverted
// background) are handled uniformly: p[y] is "cells that differ from empty space".
#define LIM 40
#define F_DIE 0
#define F_STILL 1
#define F_OSC 2
#define F_SHIP 3
#define F_GROW 4
#define F_TIMEOUT 5
#define MIX(x) (x += 0x9E3779B97F4A7C15UL, x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9UL, \
                x = (x ^ (x >> 27)) * 0x94D049BB133111EBUL, x ^ (x >> 31))
#define MAJ(a, b, c) (((a) & (b)) | ((c) & ((a) ^ (b))))
#define MUX(s, a, b) ((a) ^ ((s) & ((a) ^ (b))))
#define RESULT(fate, split, per, dx, dy, t) \
  ((u64)(fate) | (u64)(split) << 3 | (u64)(per) << 4 | (u64)((dx) + 16384) << 18 | \
   (u64)((dy) + 16384) << 33 | (u64)(t) << 48)

static void make_seed(u32 rule, u32 s, u64 *p) {
  u64 k = ((u64)rule << 32) | s; k = MIX(k);
  int w = 3 + (int)(k & 7), h = 3 + (int)((k >> 3) & 7), d = (int)((k >> 6) & 3);
  for (int y = 0; y < 64; y++) p[y] = 0;
  for (int i = 0; i < h; i++) {
    u64 a = k + 3 * i + 1, b = k + 3 * i + 2, c = k + 3 * i + 3;
    a = MIX(a); b = MIX(b); c = MIX(c);
    u64 r = d == 0 ? (a & b) : d == 1 ? (a & (b | c)) : d == 2 ? a : (a | (b & c));
    p[32 - h / 2 + i] = (r & ((1UL << w) - 1)) << (32 - w / 2);
  }
}

// Runs the job. p must be u64[64]; on return it holds the final pattern
// (relative to vacuum), *pv the vacuum state.
__attribute__((unused)) static u64 run_job(u32 rule, u32 s, u32 maxgen, u64 *p, u32 *pv) {
  u64 BB[10], SS[10];
  for (int j = 0; j < 10; j++) {
    BB[j] = (j <= 8 && ((rule >> j) & 1)) ? ~0UL : 0UL;
    SS[j] = (j >= 1 && ((rule >> (8 + j)) & 1)) ? ~0UL : 0UL;
  }
  u32 v = 0, split = 0;
  make_seed(rule, s, p);
  int ymin = 64, ymax = -1, xmin = 0, xmax = 0, pop = 0, ox = 0, oy = 0;
  u64 col = 0;
  for (int y = 0; y < 64; y++) if (p[y]) { if (ymin == 64) ymin = y; ymax = y; col |= p[y]; pop += (int)POP64(p[y]); }
  u64 sh = 0; int sx = 0, sy = 0, spop = -1; u32 st = 0;
  for (u32 t = 0;; t++) {
    if (pop == 0) { *pv = v; return RESULT(F_DIE, split, 0, 0, 0, t); }
    xmin = (int)CTZ64(col); xmax = 63 - (int)CLZ64(col);
    // Too big: try to cut off the piece farthest from where the seed started.
    for (int tries = 0; ymax - ymin >= LIM || xmax - xmin >= LIM; tries++) {
      int done = 0;
      if (tries < 8 && ymax - ymin >= LIM) {
        if (ymax - (32 + oy) >= (32 + oy) - ymin) {
          for (int y = ymax - 1; y >= ymin + 2 && !done; y--)
            if (!p[y] && !p[y - 1]) { for (int z = ymin; z < y; z++) p[z] = 0; done = 1; }
        } else {
          for (int y = ymin + 1; y <= ymax - 2 && !done; y++)
            if (!p[y] && !p[y + 1]) { for (int z = y + 1; z <= ymax; z++) p[z] = 0; done = 1; }
        }
      }
      if (tries < 8 && !done && xmax - xmin >= LIM) {
        u64 m = 0;
        if (xmax - (32 + ox) >= (32 + ox) - xmin) {
          for (int x = xmax - 1; x >= xmin + 2 && !done; x--)
            if (!((col >> x) & 1) && !((col >> (x - 1)) & 1)) { m = ~0UL << x; done = 1; }
        } else {
          for (int x = xmin + 1; x <= xmax - 2 && !done; x++)
            if (!((col >> x) & 1) && !((col >> (x + 1)) & 1)) { m = ~(~0UL << x); done = 1; }
        }
        if (done) for (int y = ymin; y <= ymax; y++) p[y] &= m;
      }
      if (!done) { *pv = v; return RESULT(F_GROW, split, 0, 0, 0, t); }
      split = 1; spop = -1;
      int a = ymin, b = ymax; ymin = 64; ymax = -1; col = 0; pop = 0;
      for (int y = a; y <= b; y++) if (p[y]) { if (ymin == 64) ymin = y; ymax = y; col |= p[y]; pop += (int)POP64(p[y]); }
      xmin = (int)CTZ64(col); xmax = 63 - (int)CLZ64(col);
    }
    // Recentre so the pattern never reaches the tile edge.
    int dy = 32 - (ymin + ymax + 1) / 2, dx = 32 - (xmin + xmax + 1) / 2;
    if (dy > 4) { for (int y = ymax; y >= ymin; y--) { p[y + dy] = p[y]; p[y] = 0; } }
    else if (dy < -4) { for (int y = ymin; y <= ymax; y++) { p[y + dy] = p[y]; p[y] = 0; } }
    else dy = 0;
    ymin += dy; ymax += dy; oy += dy;
    if (dx > 4) { for (int y = ymin; y <= ymax; y++) p[y] <<= dx; }
    else if (dx < -4) { for (int y = ymin; y <= ymax; y++) p[y] >>= -dx; }
    else dx = 0;
    xmin += dx; xmax += dx; ox += dx;
    // Translation-invariant hash; Brent cycle detection against a saved state.
    u64 h = 0;
    for (int y = ymin; y <= ymax; y++) { h = (h ^ (p[y] >> xmin)) * 0x9E3779B97F4A7C15UL; h ^= h >> 32; }
    h ^= (u64)v << 16 ^ (u64)(ymax - ymin) << 8 ^ (u64)(xmax - xmin);
    int wx = xmin - ox, wy = ymin - oy;
    if (pop == spop && h == sh) {
      int ddx = wx - sx, ddy = wy - sy; u32 per = t - st;
      *pv = v;
      return RESULT((ddx || ddy) ? F_SHIP : per == 1 ? F_STILL : F_OSC, split, per, ddx, ddy, t);
    }
    if ((t & (t - 1)) == 0 || spop < 0) { sh = h; spop = pop; sx = wx; sy = wy; st = t; }
    if (t >= maxgen) { *pv = v; return RESULT(F_TIMEOUT, split, 0, 0, 0, t); }
    // One generation, bit-parallel, rows ymin-1 .. ymax+1.
    u64 vm = v ? ~0UL : 0UL;
    v = v ? ((rule >> 17) & 1) : (rule & 1);
    u64 vn = v ? ~0UL : 0UL;
    u64 a0 = vm, a1 = vm, c0 = vm, c1 = vm;
    int y0 = ymin - 1, y1 = ymax + 1;
    ymin = 64; ymax = -1; col = 0; pop = 0;
    for (int y = y0; y <= y1; y++) {
      u64 sb = p[y] ^ vm, sd = p[y + 1] ^ vm;
      u64 l = (sd << 1) | (sd >> 63), r = (sd >> 1) | (sd << 63);
      u64 d0 = l ^ sd ^ r, d1 = MAJ(l, sd, r);
      u64 n0 = a0 ^ c0 ^ d0, k = MAJ(a0, c0, d0);
      u64 tt = a1 ^ c1 ^ d1, m = MAJ(a1, c1, d1);
      u64 n1 = tt ^ k, kk = tt & k, n2 = m ^ kk, n3 = m & kk;
#define TJ(j) ((sb & SS[j]) | (~sb & BB[j]))
      u64 m01 = MUX(n0, TJ(0), TJ(1)), m23 = MUX(n0, TJ(2), TJ(3));
      u64 m45 = MUX(n0, TJ(4), TJ(5)), m67 = MUX(n0, TJ(6), TJ(7)), m89 = MUX(n0, TJ(8), TJ(9));
      u64 q = MUX(n2, MUX(n1, m01, m23), MUX(n1, m45, m67));
      u64 nw = MUX(n3, q, m89) ^ vn;
      p[y] = nw;
      if (nw) { if (ymin == 64) ymin = y; ymax = y; col |= nw; pop += (int)POP64(nw); }
      a0 = c0; a1 = c1; c0 = d0; c1 = d1;
    }
  }
}
