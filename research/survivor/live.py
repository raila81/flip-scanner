# Live-like: only the FIRST moment a coin enters the survivor lane counts; the extra filter must hold then.
import sim, statistics as st
coins=sim.load("gh/candles.jsonl")
for c in coins: sim.prep(c)
base=lambda f: 6<=f["age"]<=48 and f["v24"]>=30e3 and (f["liq"] or 1e9)>=10e3 and f["chg1"]>=-0.08 and -0.25<=f["chg6"]<=1.2 and f["chg24"]>=-0.5
A=lambda f:(f["liq"] or 0)>=40e3 and f["mc"] and f["v24"]<f["mc"]
B=lambda f:100e3<=(f["mc"] or 0)<500e3 and 0.4<=f["dd"]<0.8
PA=dict(legs=[(1.0,1.25)],stop=0.15,H=12); PB=dict(legs=[(1.0,3.0)],stop=0.30,H=48)
for slip,cost in ((0.03,0.01),(0.06,0.02)):
    sim.SLIP,sim.COST=slip,cost
    for nm,ex,pl in (("A",A,PA),("B",B,PB),("all lane quick",lambda f:True,PA),("all lane 3x",lambda f:True,PB)):
        r=[]
        for c in coins:
            i,f=sim.first_signal(c,base)
            if i is None or not ex(f): continue
            v=sim.run(c,i,pl)
            if v is not None: r.append((f["T"],v))
        r.sort(); v=[x[1] for x in r]; h=int(len(v)*.6); s=sorted(v)
        print(f"slip{slip} {nm:15s} n{len(v)} mean {st.mean(v)*100:+.1f}% w/o3 {st.mean(s[:-3])*100:+.1f}% old {st.mean(v[:h])*100:+.1f} new {st.mean(v[h:])*100:+.1f} win {sum(x>0 for x in v)/len(v)*100:.0f}%")
