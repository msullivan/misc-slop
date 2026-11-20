#!/bin/sh
# Bring finished archives back from the build machine, pack them for the
# page, and prove the browser build replays every creature exactly.
# usage: tools/collect.sh [host:path/to/runs]
set -e
SRC=${1:-red:src/menagerie-build/runs}
mkdir -p runs web/data
args=""
for t in sprint walk rough chase shove swim jump; do
  if rsync -a "$SRC/$t.json" runs/ 2>/dev/null; then
    args="$args $t=runs/$t.json"
  fi
done
rm -f web/data/sprint.json web/data/walk.json web/data/rough.json web/data/chase.json web/data/shove.json web/data/swim.json web/data/jump.json
# shellcheck disable=SC2086
python3 tools/pack.py web/data $args
for t in sprint walk rough chase shove swim jump; do
  [ -f "runs/$t.json" ] && node tools/check_wasm.mjs web/mg.wasm "runs/$t.json"
done
