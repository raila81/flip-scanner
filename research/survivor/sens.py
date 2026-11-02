import sim, statistics as st, random
coins=sim.load("gh/candles.jsonl")
for c in coins: sim.prep(c)
base=lambda f: 6<=f["age"]<=96 and f["v24"]>=30e3 and (f["liq"] or 1e9)>=10e3 and f["chg1"]>=-0.08 and -0.25<=f["chg6"]<=1.2 and f["chg24"]>=-0.5
FL={"lane":base,
 "lane pool40K":lambda f: base(f) and (f["liq"] or 0)>=40e3,
 "lane pool40K vol<mc":lambda f: base(f) and (f["liq"] or 0)>=40e3 and f["mc"] and f["v24"]<f["mc"],
 "lane pool40K near top":lambda f: base(f) and (f["liq"] or 0)>=40e3 and f["dd"]>=0.8,
 "lane pool20K vol<mc":lambda f: base(f) and (f["liq"] or 0)>=20e3 and f["mc"] and f["v24"]<f["mc"],
 "lane mc100-500K":lambda f: base(f) and 100e3<=(f["mc"] or 0)<500e3,
 "lane mc100-500K dd.4-.8":lambda f: base(f) and 100e3<=(f["mc"] or 0)<500e3 and 0.4<=f["dd"]<0.8}
PL={"quick 1.25x st15 12h":dict(legs=[(1.0,1.25)],stop=0.15,H=12),
    "1.2x st15 12h":dict(legs=[(1.0,1.2)],stop=0.15,H=12),
    "1.3x st15 12h":dict(legs=[(1.0,1.3)],stop=0.15,H=12),
    "1.25x st20 24h":dict(legs=[(1.0,1.25)],stop=0.20,H=24),
    "3x st30 48h":dict(legs=[(1.0,3.0)],stop=0.30,H=48),
    "half1.25 half3x st25 48h":dict(legs=[(0.5,1.25),(0.5,3.0)],stop=0.25,H=48)}
cut=None
def go(slip,cost):
    sim.SLIP=slip; sim.COST=cost; out={}
    for fn,ff in FL.items():
        r=[]
        for c in coins:
            i,f=sim.first_signal(c,ff)
            if i is None: continue
            r.append((f["T"],c["token"],{p:sim.run(c,i,pl) for p,pl in PL.items()}))
        out[fn]=sorted(r)
    return out
o=go(0.03,0.01)
allT=[x[0] for x in o["lane"]]; cut=sorted(allT)[int(len(allT)*0.6)]
def line(r,p):
    v=[x[2][p] for x in r if x[2][p] is not None]; s=sorted(v)
    a=[x[2][p] for x in r if x[0]<cut]; b=[x[2][p] for x in r if x[0]>=cut]
    return f"n{len(v):3d} mean {st.mean(v)*100:+5.1f}% w/o best3 {st.mean(s[:-3])*100:+5.1f}% old {st.mean(a)*100:+5.1f} new {st.mean(b)*100:+5.1f} win {sum(x>0 for x in v)/len(v)*100:3.0f}%"
for slip,cost in ((0.03,0.01),(0.06,0.02)):
    o=go(slip,cost); print(f"\n== stop slip {slip*100:.0f}%, costs {cost*100:.0f}% ==")
    for fn in FL:
        for p in PL: print(f"{fn:26s} | {p:24s} | {line(o[fn],p)}")
