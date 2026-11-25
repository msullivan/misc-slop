#!/bin/bash
# The whole pipeline, start to finish. Takes a few hours on 64 threads and
# wants ~100 GB of memory and ~40 GB of disk under $WORK.
#
#   ./census.sh              everything
#   COMPILERS="gcc-13 go-1.27" ./census.sh
set -euo pipefail
cd "$(dirname "$0")"
WORK=${WORK:-$HOME/src/peephole-build}
PY=${PY:-$WORK/venv/bin/python}       # needs numpy and z3-solver
COMPILERS=${COMPILERS:-"clang-10 clang-14 clang-17 clang-18 clang-23 gcc-9 gcc-11 gcc-12 gcc-13 gcc-16 go-1.27 cranelift-51"}
export CARGO_TARGET_DIR=$WORK/target
(cd enumerate && cargo build --release)
ENUM=$WORK/target/release/enumerate

ARITH="--k 4 --bits 28 --consts 0,1,-1,2,3,0xff,0x80000000 --shifts 1,2,8,16,24,31"
CMP="--k 3 --consts 0,1,-1,2,0x80000000 --shifts 1,31 --ops add,sub,and,or,xor,shl,lshr,ashr,eq,ne,lts,ltu,les,leu,smin,smax,umin,umax"

census() {  # name, enumerator flags
  local run=$WORK/runs/$1
  # The order of census records isn't deterministic: never redo this under existing results.
  if [ ! -f $run/meta.json ]; then $ENUM $2 --out $run; fi
  $ENUM $2 --out $run --rekey                # equal on ~150k more inputs
  $PY verify.py $run --timeout 600           # then prove it
  $PY pre.py $run
  for c in $COMPILERS; do
    [ -f $run/asm/$c.ids.npy ] || $PY compile.py $run $c
  done
}
census main "$ARITH"
census cmp "$CMP"
$PY report.py $WORK/runs/report.json arith=$WORK/runs/main cmp=$WORK/runs/cmp
$PY build_site.py $WORK/runs/report.json site
