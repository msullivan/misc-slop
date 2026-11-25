import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import random, json, numpy as np
from terms import *
from distill import Distilled
run, comp, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
nshow = int(sys.argv[4]) if len(sys.argv) > 4 else 30
D = Distilled(run, [comp]); cen, lang = D.cen, D.lang
x = D.data[comp]
x["bodies"] = cen.load(comp, bodies=True)[1]
idx = np.flatnonzero(x["root"] & (cen.size == size))
random.seed(int(sys.argv[5]) if len(sys.argv) > 5 else 0)
for i in random.sample(list(idx), min(nshow, len(idx))):
    w = x["wit"][i]
    sw = cen.fp[i] != cen.fp[w]
    print(f"{infix(lang, lang.unpack(cen.packed[i])):38s} [{x['u'][i]},{x['d'][i]}] {x['bodies'][x['ids'][i]]}\n   = {infix(lang, lang.unpack(cen.packed[w]), swap=sw):33s} [{x['u'][w]},{x['d'][w]}] {x['bodies'][x['ids'][w]]}")
