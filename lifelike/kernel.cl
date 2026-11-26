typedef ulong u64; typedef uint u32;
#define CLZ64(x) clz((ulong)(x))
#define CTZ64(x) ctz((ulong)(x))
#define POP64(x) popcount((ulong)(x))
#include "core.h"
__kernel void census(__global ulong *out, uint rule0, uint nseed, uint seed0, uint maxgen) {
  uint gid = (uint)get_global_id(0);
  u64 p[64]; u32 v;
  out[gid] = run_job(rule0 + gid / nseed, seed0 + gid % nseed, maxgen, p, &v);
}
