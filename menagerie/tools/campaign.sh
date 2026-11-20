#!/bin/sh
# The full evolution campaign, run on the big machine from the build dir.
# Each habitat is bred as six isolated families. Budgets are total
# evaluations per habitat; the whole thing is a few hours on 32 cores.
set -e
B=./target/release/menagerie
I=6
mkdir -p runs
run() { # task seed evals [--from ...]
  task=$1; seed=$2; evals=$3; shift 3
  $B evolve --task "$task" --islands $I --seed "$seed" --evals "$evals" --out "runs/$task.json" "$@" 2> "runs/$task.log"
}
run sprint 1 3000000
run walk   2 3000000
run jump   3 1800000
run swim   4 2400000
# The rest start from the sprinters and walkers of the same family, so
# family III in the rough is descended from family III on the flat.
run shove  5 1800000 --from runs/sprint.json --from runs/walk.json
run rough  6 1800000 --from runs/sprint.json --from runs/walk.json
run chase  7 1500000 --from runs/sprint.json --from runs/walk.json
echo done > runs/campaign.done
