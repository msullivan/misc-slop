// GPU census of all 2^18 Life-like rules. Usage: census NSEED MAXGEN [rule0 nrules] [outprefix]
#define CL_TARGET_OPENCL_VERSION 200
#include <CL/cl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "cpu.h"
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
static char *slurp(const char *f){FILE*fp=fopen(f,"rb");if(!fp){perror(f);exit(1);}fseek(fp,0,SEEK_END);long n=ftell(fp);rewind(fp);char*s=malloc(n+1);if(fread(s,1,n,fp)!=(size_t)n)exit(1);s[n]=0;fclose(fp);return s;}
#define CK(e,what) do{ if(e){fprintf(stderr,"%s failed: %d\n",what,(int)(e));exit(1);} }while(0)
typedef struct { int a, b, per; unsigned cnt, ex, exsplit; } Ent;   // ship velocity or oscillator period
#define MAXE 96
int main(int argc,char**argv){
  if(argc<3){fprintf(stderr,"usage: census NSEED MAXGEN [rule0 nrules] [prefix]\n");return 1;}
  unsigned nseed=atoi(argv[1]), maxgen=atoi(argv[2]);
  unsigned rule0=argc>4?atoi(argv[3]):0, nrules=argc>4?atoi(argv[4]):1<<18;
  const char *prefix=argc>5?argv[5]:"out/census";
  unsigned batch_rules = (1u<<22)/nseed; if(batch_rules<1)batch_rules=1;
  cl_platform_id ps[8]; cl_uint np; clGetPlatformIDs(8,ps,&np);
  cl_device_id dev=0; cl_int e=-1;
  for(cl_uint i=0;i<np;i++){ e=clGetDeviceIDs(ps[i],CL_DEVICE_TYPE_GPU,1,&dev,NULL); if(e==CL_SUCCESS)break; }
  CK(e,"find GPU");
  cl_context ctx=clCreateContext(NULL,1,&dev,NULL,NULL,&e); CK(e,"context");
  cl_command_queue q=clCreateCommandQueueWithProperties(ctx,dev,NULL,&e); CK(e,"queue");
  const char *src=slurp("kernel.cl");
  cl_program prog=clCreateProgramWithSource(ctx,1,&src,NULL,&e); CK(e,"program");
  e=clBuildProgram(prog,1,&dev,"-I . -cl-std=CL2.0",NULL,NULL);
  if(e){static char log[1<<16];clGetProgramBuildInfo(prog,dev,CL_PROGRAM_BUILD_LOG,sizeof log,log,NULL);fprintf(stderr,"build failed %d:\n%s\n",e,log);return 1;}
  cl_kernel k=clCreateKernel(prog,"census",&e); CK(e,"kernel");
  size_t maxjobs=(size_t)batch_rules*nseed;
  cl_mem buf=clCreateBuffer(ctx,CL_MEM_WRITE_ONLY,maxjobs*8,NULL,&e); CK(e,"buffer");
  u64 *res=malloc(maxjobs*8);
  char fn[512];
  snprintf(fn,sizeof fn,"%s.rules.tsv",prefix); FILE *fr=fopen(fn,"w"); if(!fr){perror(fn);return 1;}
  snprintf(fn,sizeof fn,"%s.ships.tsv",prefix); FILE *fs=fopen(fn,"w");
  snprintf(fn,sizeof fn,"%s.osc.tsv",prefix); FILE *fo=fopen(fn,"w");
  fprintf(fr,"rule\tdie\tstill\tosc\tship\tgrow\ttimeout\tsplit\tsumt_die\tmaxt\tmaxt_seed\n");
  fprintf(fs,"rule\tdx\tdy\tperiod\tcount\tseed\tsplit\n");
  fprintf(fo,"rule\tperiod\tcount\tseed\tsplit\n");
  double t0=now(), gput=0; unsigned long long total=0;
  for(unsigned r0=rule0;r0<rule0+nrules;r0+=batch_rules){
    unsigned nr=batch_rules; if(r0+nr>rule0+nrules)nr=rule0+nrules-r0;
    size_t n=(size_t)nr*nseed; cl_uint z=0;
    clSetKernelArg(k,0,sizeof buf,&buf); clSetKernelArg(k,1,4,&r0); clSetKernelArg(k,2,4,&nseed); clSetKernelArg(k,3,4,&z); clSetKernelArg(k,4,4,&maxgen);
    double t=now();
    e=clEnqueueNDRangeKernel(q,k,1,NULL,&n,NULL,0,NULL,NULL); CK(e,"enqueue");
    e=clEnqueueReadBuffer(q,buf,CL_TRUE,0,n*8,res,0,NULL,NULL); CK(e,"read");
    gput+=now()-t; total+=n;
    for(unsigned i=0;i<nr;i++){
      unsigned rule=r0+i; unsigned long long cnt[6]={0},nsplit=0,sumt=0; unsigned maxt=0,maxts=0;
      Ent ships[MAXE], osc[MAXE]; int ns=0,no=0;
      for(unsigned s=0;s<nseed;s++){
        u64 r=res[(size_t)i*nseed+s]; int f=R_FATE(r); cnt[f]++; nsplit+=R_SPLIT(r);
        if(f==F_DIE) sumt+=R_T(r);
        if(f<=F_SHIP && !R_SPLIT(r) && (unsigned)R_T(r)>maxt){maxt=R_T(r);maxts=s;}
        if(f==F_SHIP||f==F_OSC){
          int a=abs(R_DX(r)),b=abs(R_DY(r)); if(a<b){int tmp=a;a=b;b=tmp;}
          Ent *tab=f==F_SHIP?ships:osc; int *pn=f==F_SHIP?&ns:&no; int j;
          for(j=0;j<*pn;j++) if(tab[j].a==a&&tab[j].b==b&&tab[j].per==R_PER(r))break;
          if(j==*pn){ if(j==MAXE)continue; tab[j]=(Ent){a,b,R_PER(r),0,s,R_SPLIT(r)}; (*pn)++; }
          tab[j].cnt++;
          if(tab[j].exsplit && !R_SPLIT(r)){tab[j].ex=s;tab[j].exsplit=0;}
        }
      }
      fprintf(fr,"%u\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%u\t%u\n",rule,cnt[0],cnt[1],cnt[2],cnt[3],cnt[4],cnt[5],nsplit,sumt,maxt,maxts);
      for(int j=0;j<ns;j++) fprintf(fs,"%u\t%d\t%d\t%d\t%u\t%u\t%u\n",rule,ships[j].a,ships[j].b,ships[j].per,ships[j].cnt,ships[j].ex,ships[j].exsplit);
      for(int j=0;j<no;j++) fprintf(fo,"%u\t%d\t%u\t%u\t%u\n",rule,osc[j].per,osc[j].cnt,osc[j].ex,osc[j].exsplit);
    }
    fflush(fr);fflush(fs);fflush(fo);
    fprintf(stderr,"\rrules %u/%u  %.0fs  gpu %.0fs  %.2e jobs/s ",r0+nr-rule0,nrules,now()-t0,gput,total/gput);
  }
  fprintf(stderr,"\n"); fclose(fr);fclose(fs);fclose(fo); return 0;
}
