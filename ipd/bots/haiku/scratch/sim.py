import random, sys
sys.path.insert(0, __file__.rsplit("/",1)[0])
import haiku_mod as h
P = {("C","C"):3,("C","D"):0,("D","C"):5,("D","D"):1}
def tft(m,t,r): return t[-1] if t else "C"
def alld(m,t,r): return "D"
def allc(m,t,r): return "C"
def grim(m,t,r): return "D" if "D" in t else "C"
def rnd(m,t,r): return r.choice("CD")
def pavlov(m,t,r): return "C" if (not m or m[-1]==t[-1]) else "D"
def gtft(m,t,r): return ("C" if r.random()<0.1 else "D") if t and t[-1]=="D" else "C"
def tf2t(m,t,r): return "D" if t[-2:]==["D","D"] else "C"
def alt(m,t,r): return "C" if len(m)%2==0 else "D"
def half(m,t,r): return "D" if (t and t[-1]=="D" and r.random()<0.5) else "C"  # 50% punisher
def luna(m,t,r): return "C" if r.random()<0.2 else "D"
OPP = dict(tft=tft,alld=alld,allc=allc,grim=grim,rnd=rnd,pavlov=pavlov,gtft=gtft,tf2t=tf2t,alt=alt,half=half,luna=luna)
def play(fa, fb, n, seed):
    r = random.Random(seed); ma, mb = [], []; sa=sb=0
    for _ in range(n):
        a = fa(ma,mb,r) if fa else h.decide(ma,mb,r)
        b = fb(mb,ma,r) if fb else h.decide(mb,ma,r)
        sa+=P[(a,b)]; sb+=P[(b,a)]; ma.append(a); mb.append(b)
    return sa/n, sb/n
S=300
if __name__!="__main__": OPP={}
for name,f in OPP.items():
    res=[play(None,f,200,s) for s in range(S)]
    print(f"{name:8s} haiku {sum(x for x,_ in res)/S:.2f}  opp {sum(y for _,y in res)/S:.2f}")
print("self", sum(play(None,None,200,s)[0] for s in range(S))/S)
