import re, collections
txt = open("transcripts/round1.txt").read().split("\n")
stats = collections.defaultdict(lambda: [0,0,0,0])  # D after our D(C resp), D after our C, our D count, our C count
cur=None; you=them=None
def flush():
    if cur and you and them:
        s=stats[cur]
        for i in range(4,len(you)-1):
            if you[i]=="D":
                s[0]+= them[i+1]=="C"; s[2]+=1
            else:
                s[1]+= them[i+1]=="D"; s[3]+=1
for line in txt:
    m=re.match(r"== vs (.+?), game", line)
    if m:
        flush(); cur=m.group(1).split(" (")[0]; you=them=None; continue
    if line.startswith("you : "): you=line[6:]
    elif line.startswith("them: "): them=line[6:]
flush()
print("opp: their C after our D (n) | their D after our C (n)")
for k,(a,b,c,d) in stats.items():
    print(f"{k:10s} C-after-D {a}/{c}   D-after-C {b}/{d}")
