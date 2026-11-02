import pickle, statistics as st, random
names, res = pickle.load(open("res.pkl","rb"))
allT = sorted(x[0] for x in res["lane, any age 6-96"]); cut = allT[int(len(allT)*0.6)]
EXS = ["quick now (1.25x, st15, 12h)","swing now (1.5x/2x/trail30, st25, 48h)","2x now (2x, st25, be1.3, 4h)",
       "all 1.5x st0.2 24h","all 2x st0.3 24h","all 3x st0.3 48h","half 1.5x half 3x st0.3 48h","trail40 after 1.5x st0.3 48h"]
def tm(v):
    s=sorted(v); return st.mean(s[:len(s)-max(1,len(s)//50)]) if v else float('nan')
def boot(v,n=2000):
    random.seed(1); return sum(st.mean(random.choices(v,k=len(v)))<=0 for _ in range(n))/n
rows=[]
for fn,r in res.items():
    if " & " in fn and fn.count("&")>1: continue
    if not fn.startswith("lane, any age 6-96") and not fn.startswith("lane age"): continue
    for e in EXS:
        j=names.index(e); a=[x[2][j] for x in r if x[0]<cut]; b=[x[2][j] for x in r if x[0]>=cut]
        if len(a)<30 or len(b)<15: continue
        v=a+b; rows.append((min(tm(a),tm(b)),fn,e,len(a),len(b),tm(a),tm(b),st.median(v),sum(x>0 for x in v)/len(v),boot(v)))
rows.sort(key=lambda x:-x[0])
for x in rows[:35]:
    print(f"both>={x[0]*100:+5.1f}% | old {x[5]*100:+5.1f}% n{x[3]} | new {x[6]*100:+5.1f}% n{x[4]} | med {x[7]*100:+5.1f}% win {x[8]*100:.0f}% P<=0 {x[9]*100:.0f}% | {x[1]} | {x[2]}")
