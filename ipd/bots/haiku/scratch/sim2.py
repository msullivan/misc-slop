import random, sys
sys.path.insert(0, __file__.rsplit("/",1)[0])
import haiku_mod as h
from sim import *
def grim_forgive(m,t,r):
    # defects once we defect, forgives after 12 rounds of defection (opus-1-like guess)
    if "D" not in m: return "C"
    k = len(m) - m.index("D") if "D" in m else 0
    return "C" if (k % 13 == 12) else "D"
OPP2 = dict(grimf=grim_forgive)
for name,f in OPP2.items():
    res=[play(None,f,200,s) for s in range(S)]
    print(f"{name:8s} haiku {sum(x for x,_ in res)/S:.2f}  opp {sum(y for _,y in res)/S:.2f}")
