#include <stdint.h>
typedef uint64_t u64; typedef uint32_t u32;
#define CLZ64(x) __builtin_clzll(x)
#define CTZ64(x) __builtin_ctzll(x)
#define POP64(x) __builtin_popcountll(x)
#include "core.h"
#define R_FATE(r) ((int)((r) & 7))
#define R_SPLIT(r) ((int)((r) >> 3 & 1))
#define R_PER(r) ((int)((r) >> 4 & 16383))
#define R_DX(r) ((int)((r) >> 18 & 32767) - 16384)
#define R_DY(r) ((int)((r) >> 33 & 32767) - 16384)
#define R_T(r) ((int)((r) >> 48))
