# Life-like Rule Atlas

A GPU census of every Life-like cellular automaton: all 2^18 = 262,144
outer-totalistic rules on the Moore neighbourhood (B0..8 / S0..8), each fed
65,536 small random seeds, to see what the seeds turn into.

Every run ends one of six ways: the seed dies, settles into a still life, an
oscillator or a spaceship, grows without bound, or is still undecided after
4,096 generations. Spaceships are recorded by velocity and period, and each
distinct one is kept with an example.

<https://msullivan.github.io/misc-slop/lifelike/site/>

## How it works

`core.h` is one job (one rule, one seed) written so the same source compiles
as an OpenCL kernel and as plain C:

- 64x64 bit-packed tile, one `ulong` per row, generations computed with
  bit-sliced adders and a mux tree over the rule bits (about 70 word ops per
  row).
- The pattern is stored XOR the "vacuum" state, so B0 rules, where empty
  space itself flips, need no special handling.
- The pattern is recentred as it moves, hashed translation-invariantly, and
  compared against a saved state (Brent's cycle detection). Same hash at a
  different position is a spaceship.
- When the pattern outgrows 40x40, the piece farthest from the origin is cut
  off across a two-cell empty gap and followed on its own. That is how a
  glider leaving a pile of ash gets counted. No gap means "grows".

`census.c` drives the GPU through OpenCL, about four million jobs per kernel
launch, and aggregates per rule. `extract.c` re-runs every reported spaceship
and oscillator on the CPU and checks period and displacement with a separate
naive simulator (byte grid, plain neighbour counting). `build_site.py` refuses
to build if any row failed that check.

## Run it

    gcc -O2 census.c -o census -lOpenCL
    gcc -O2 -fopenmp extract.c -o extract
    gcc -O2 -fopenmp examples.c -o examples
    mkdir -p out
    ./tempmon.sh out/temps.log &     # optional: log CPU/GPU temperature and power
    ./census 65536 4096 0 262144 out/c64k
    ./extract ships 4096 < out/c64k.ships.tsv > out/c64k.ships.x.tsv
    awk 'NR>1 && $2>=3' out/c64k.osc.tsv | ./extract osc 4096 > out/c64k.osc.x.tsv
    ./examples out/c64k.rules.tsv 65536 4096 out/c64k.examples.bin
    python3 build_site.py out/c64k 65536
    cd site && python3 -m http.server 8799

## Limits

- Seeds are 3x3 to 10x10 at four densities; a ship that never arises from
  one of those is not here.
- Periods above about 2,048 cannot be detected within 4,096 generations, so
  the longest-oscillator list is capped there.
- `rules.b64.txt` is the per-rule table (8 little-endian u16 per rule) in base64.
- `examples.b64.txt` is, per rule, the first seed that ends each of the six
  ways (6 little-endian u16, 0xffff for none), found by `examples.c` on the CPU.
- Bounded patterns larger than 40x40 count as "grows".
