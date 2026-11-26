// For every rule, the first seed that meets each fate. Usage: examples RULES.tsv NSEED MAXGEN OUT.bin [rule0 nrules]
// Reads the census counts so it knows which fates exist and can stop as soon as it has one of each.
// A seed that dies is only taken if it lasts at least a generation, when the census saw one that did
// (an empty seed "dies" at once and shows nothing).
// Output: 6 little-endian u16 per rule (0xffff where the census counted none). Same job code as the GPU kernel.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cpu.h"
#define NR (1u << 18)
int main(int argc, char **argv) {
  if (argc < 5) { fprintf(stderr, "usage: examples RULES.tsv NSEED MAXGEN OUT.bin [rule0 nrules]\n"); return 1; }
  unsigned nseed = atoi(argv[2]), maxgen = atoi(argv[3]);
  unsigned rule0 = argc > 6 ? atoi(argv[5]) : 0, nrules = argc > 6 ? atoi(argv[6]) : NR;
  static unsigned long long cnt[NR][6], sumt[NR];
  static unsigned short ex[NR][6];
  FILE *f = fopen(argv[1], "r"); if (!f) { perror(argv[1]); return 1; }
  char line[512]; unsigned got = 0;
  while (fgets(line, sizeof line, f)) {
    unsigned r; unsigned long long c[6], sp, st;
    if (sscanf(line, "%u %llu %llu %llu %llu %llu %llu %llu %llu", &r, c, c + 1, c + 2, c + 3, c + 4, c + 5, &sp, &st) == 9 && r < NR) { memcpy(cnt[r], c, sizeof c); sumt[r] = st; got++; }
  }
  fclose(f);
  if (got != NR) { fprintf(stderr, "expected %u rules, read %u\n", NR, got); return 1; }
  memset(ex, 0xff, sizeof ex);
  unsigned long long jobs = 0, bad = 0;
  #pragma omp parallel for schedule(dynamic, 16) reduction(+:jobs, bad)
  for (unsigned rule = rule0; rule < rule0 + nrules; rule++) {
    int need = 0; unsigned long long seen[6] = {0};
    for (int i = 0; i < 6; i++) need += cnt[rule][i] != 0;
    u64 p[64]; u32 v; unsigned s;
    for (s = 0; s < nseed && need; s++) {
      u64 res = run_job(rule, s, maxgen, p, &v); int fate = R_FATE(res);
      if (fate == F_DIE && sumt[rule] && R_T(res) == 0) continue;
      if (!seen[fate]++) { ex[rule][fate] = (unsigned short)s; need--; if (!cnt[rule][fate]) bad++; }
    }
    jobs += s; if (need > 0) bad++;
  }
  fprintf(stderr, "%llu jobs, %llu disagreements with the census\n", jobs, bad);
  if (bad) return 1;
  f = fopen(argv[4], "wb"); fwrite(ex[rule0], 12, nrules, f); fclose(f);
  return 0;
}
