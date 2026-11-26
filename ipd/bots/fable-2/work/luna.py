import sys
from importlib.machinery import SourceFileLoader
sys.dont_write_bytecode=True
mod = SourceFileLoader("fb", "/home/sully/src/misc-slop/ipd/bots/fable-2/run").load_module()
b=mod.Bot(); me=[];op=[];s=0
for t in range(300):
    m=b.move(); o="C" if t<2 or (me[-1]=="D" and me[-2]=="C") else "D"
    b.observe(m,o); me.append(m); op.append(o); s+=mod.PAY[m,o]
print("".join(me[:80])); print("".join(op[:80])); print(s/300)
