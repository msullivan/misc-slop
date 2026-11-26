// Re-runs census examples on the CPU, extracts the final pattern, and checks it with an
// independent naive simulator (byte grid, plain neighbour counting).
// Usage: extract ships|osc MAXGEN < in.tsv > out.tsv
//   ships rows: rule dx dy period count seed split ; osc rows: rule period count seed split
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cpu.h"
#define N 192
typedef struct { unsigned rule; int a, b, per; unsigned cnt, seed, split; char pat[512]; int w, h, v, minpop, ok; } Row;

static int bbox(const unsigned char *g, int *x0, int *y0, int *x1, int *y1) {
  int pop = 0; *x0 = N; *y0 = N; *x1 = -1; *y1 = -1;
  for (int y = 0; y < N; y++) for (int x = 0; x < N; x++) if (g[y * N + x]) {
    pop++; if (x < *x0) *x0 = x; if (x > *x1) *x1 = x; if (y < *y0) *y0 = y; if (y > *y1) *y1 = y; }
  return pop;
}
// g holds cells XOR vacuum. One naive generation.
static void nstep(unsigned rule, unsigned char *g, int *v, int x0, int y0, int x1, int y1) {
  static _Thread_local unsigned char t[N * N];
  int nv = *v ? (rule >> 17) & 1 : rule & 1;
  memset(t, 0, sizeof t);
  for (int y = y0 - 1; y <= y1 + 1; y++) for (int x = x0 - 1; x <= x1 + 1; x++) {
    int n = 0;
    for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) if (dx || dy) n += g[(y + dy) * N + x + dx] ^ *v;
    int self = g[y * N + x] ^ *v;
    int nw = self ? (rule >> (9 + n)) & 1 : (rule >> n) & 1;
    t[y * N + x] = nw ^ nv;
  }
  memcpy(g, t, sizeof t); *v = nv;
}
static int verify(Row *r, const u64 *p, int v0) {
  static _Thread_local unsigned char g[N * N], init[64 * 64], tmp[N * N];
  memset(g, 0, sizeof g);
  int off = (N - 64) / 2;
  for (int y = 0; y < 64; y++) for (int x = 0; x < 64; x++) g[(y + off) * N + x + off] = (p[y] >> x) & 1;
  int x0, y0, x1, y1, v = v0, ox = 0, oy = 0;
  int pop = bbox(g, &x0, &y0, &x1, &y1);
  int w = x1 - x0 + 1, h = y1 - y0 + 1, sx = x0, sy = y0, ipop = pop;
  for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) init[y * 64 + x] = g[(y0 + y) * N + x0 + x];
  r->w = w; r->h = h; r->v = v0; r->minpop = pop;
  int k = 0; unsigned char acc = 0; int nb = 0;
  static const char b64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  for (int i = 0; i < w * h; i++) { acc = acc << 1 | init[(i / w) * 64 + i % w]; if (++nb == 6) { r->pat[k++] = b64[acc]; acc = 0; nb = 0; } }
  if (nb) r->pat[k++] = b64[acc << (6 - nb)];
  r->pat[k] = 0;
  for (int q = 1; q <= r->per; q++) {
    nstep(r->rule, g, &v, x0, y0, x1, y1);
    pop = bbox(g, &x0, &y0, &x1, &y1);
    if (pop == 0 || x1 - x0 >= 60 || y1 - y0 >= 60) return 0;
    if (pop < r->minpop) r->minpop = pop;
    int same = v == v0 && pop == ipop && x1 - x0 + 1 == w && y1 - y0 + 1 == h;
    for (int y = 0; same && y < h; y++) for (int x = 0; x < w; x++) if (init[y * 64 + x] != g[(y0 + y) * N + x0 + x]) { same = 0; break; }
    if (same) {
      if (q < r->per) return 0;
      int dx = abs(x0 - ox - sx), dy = abs(y0 - oy - sy); if (dx < dy) { int t = dx; dx = dy; dy = t; }
      return v == v0 && dx == r->a && dy == r->b;
    }
    if (x0 < 40 || y0 < 40 || x1 >= N - 40 || y1 >= N - 40) {   // recentre
      int cx = N / 2 - (x0 + x1) / 2, cy = N / 2 - (y0 + y1) / 2;
      memset(tmp, 0, sizeof tmp);
      for (int y = y0; y <= y1; y++) for (int x = x0; x <= x1; x++) tmp[(y + cy) * N + x + cx] = g[y * N + x];
      memcpy(g, tmp, sizeof g); ox += cx; oy += cy; x0 += cx; x1 += cx; y0 += cy; y1 += cy;
    }
  }
  return 0;
}
int main(int argc, char **argv) {
  int ships = !strcmp(argv[1], "ships"); unsigned maxgen = atoi(argv[2]);
  size_t n = 0, cap = 1 << 16; Row *rows = malloc(cap * sizeof(Row)); char line[256];
  while (fgets(line, sizeof line, stdin)) {
    if (line[0] == 'r') continue;
    if (n == cap) rows = realloc(rows, (cap *= 2) * sizeof(Row));
    Row *r = &rows[n]; r->a = r->b = 0;
    if (ships) sscanf(line, "%u %d %d %d %u %u %u", &r->rule, &r->a, &r->b, &r->per, &r->cnt, &r->seed, &r->split);
    else sscanf(line, "%u %d %u %u %u", &r->rule, &r->per, &r->cnt, &r->seed, &r->split);
    n++;
  }
  #pragma omp parallel for schedule(dynamic, 16)
  for (size_t i = 0; i < n; i++) {
    Row *r = &rows[i]; u64 p[64]; u32 v;
    u64 res = run_job(r->rule, r->seed, maxgen, p, &v);
    int a = abs(R_DX(res)), b = abs(R_DY(res)); if (a < b) { int t = a; a = b; b = t; }
    int same = R_FATE(res) == (ships ? F_SHIP : F_OSC) && R_PER(res) == r->per && a == r->a && b == r->b;
    r->ok = verify(r, p, v) && same;
  }
  size_t bad = 0;
  for (size_t i = 0; i < n; i++) { Row *r = &rows[i]; bad += !r->ok;
    printf("%u\t%d\t%d\t%d\t%u\t%u\t%u\t%d\t%d\t%d\t%d\t%s\t%d\n", r->rule, r->a, r->b, r->per, r->cnt, r->seed, r->split, r->v, r->w, r->h, r->minpop, r->pat, r->ok); }
  fprintf(stderr, "%zu rows, %zu failed verification\n", n, bad);
  return 0;
}
