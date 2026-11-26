import random, sys
import sim, zoo
path = sys.argv[2] if len(sys.argv) > 2 else "../strategy.py"
f = sim.load(path)
c = getattr(zoo, sys.argv[1])
rng = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 5)
n = 200
a, b, ma, mb = sim.play(f, lambda r: c(r), n, rng)
print(a/n, b/n)
for i in range(0, n, 100):
    print(ma[i:i+100]); print(mb[i:i+100]); print()
