// CPU reference: cpurun RULE SEED0 NSEED MAXGEN  -> prints raw results, same code as the GPU kernel.
#include <stdio.h>
#include <stdlib.h>
#include "cpu.h"
int main(int c,char**v){ unsigned rule=atoi(v[1]),s0=atoi(v[2]),n=atoi(v[3]),mg=atoi(v[4]); u64 p[64]; u32 vac;
  for(unsigned s=s0;s<s0+n;s++){ u64 r=run_job(rule,s,mg,p,&vac); printf("%u %u f=%d split=%d per=%d dx=%d dy=%d t=%d\n",rule,s,R_FATE(r),R_SPLIT(r),R_PER(r),R_DX(r),R_DY(r),R_T(r)); } }
