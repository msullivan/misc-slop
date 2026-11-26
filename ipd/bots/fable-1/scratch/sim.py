import importlib.machinery, importlib.util, random, sys, time
sys.dont_write_bytecode = True
l = importlib.machinery.SourceFileLoader('fb', '/home/sully/src/misc-slop/ipd/bots/fable-1/run')
spec = importlib.util.spec_from_loader('fb', l); fb = importlib.util.module_from_spec(spec); l.exec_module(fb)
PAY = fb.PAY
def allc(me, op): return 'C'
def alld(me, op): return 'D'
def tft(me, op): return op[-1] if op else 'C'
def tf2t(me, op): return 'D' if op[-2:] == ['D','D'] else 'C'
def grim(me, op): return 'D' if 'D' in op else 'C'
def pavlov(me, op):
    if not op: return 'C'
    return me[-1] if op[-1]=='C' else ('C' if me[-1]=='D' else 'D')
def joss(me, op): return 'D' if (op and op[-1]=='D') or random.random()<0.1 else 'C'
def stft(me, op): return op[-1] if op else 'D'
def rnd(me, op): return random.choice('CD')
def exploiter(me, op): return 'D' if len(me)%4==0 else (op[-1] if op else 'C')
def luna(me, op):
    t=len(me)
    if t<2: return 'C'
    return 'C' if (me[-1]=='D' and op[-1]=='D' and op[-2]=='C') else 'D'
def terra(me, op):
    t=len(me)
    if t%59 in (12,13): return 'D'
    if op[-4:].count('D')>=3: return 'D'
    return 'C'
def haiku(me, op):
    t=len(me)
    if t in (1,2,12,22): return 'D'
    if t in (3,14,24): return 'C'
    return op[-1] if op else 'C'
def farm(me, op):  # D, take the punishment, D again, repeat
    t=len(me)
    return 'D' if t%8 in (3,5) else 'C'
def run(f, n=300):
    b = fb.Bot()
    me=[];op=[];s=0;so=0
    for _ in range(n):
        m = b.move(); b.my.append(m)
        o = f(op, me)
        b.op.append(o); me.append(m); op.append(o)
        s+=PAY[m,o]; so+=PAY[o,m]
    return s/n, so/n, ''.join(me[:110]), ''.join(op[:110])
random.seed(1); t0=time.time()
for f in [allc,alld,tft,tf2t,grim,pavlov,joss,stft,rnd,exploiter,luna,terra,haiku,farm]:
    a,b,m,o = run(f)
    print(f"{f.__name__:10s} me={a:.2f} op={b:.2f}\n  {m}\n  {o}")
print(time.time()-t0)
