import sim, statistics as st, time, collections
coins=sim.load("gh/candles.jsonl")
for c in coins: sim.prep(c)
base=lambda f: 6<=f["age"]<=96 and f["v24"]>=30e3 and (f["liq"] or 1e9)>=10e3 and f["chg1"]>=-0.08 and -0.25<=f["chg6"]<=1.2 and f["chg24"]>=-0.5
def ev(ff,pl):
    r=[]
    for c in coins:
        i,f=sim.first_signal(c,ff)
        if i is None: continue
        v=sim.run(c,i,pl)
        if v is not None: r.append((f["T"],v,c.get("name")))
    r.sort(); v=[x[1] for x in r]; s=sorted(v); h=int(len(v)*0.6)
    days=collections.Counter(time.strftime('%m-%d',time.gmtime(x[0])) for x in r if x[1]>0.5)
    return f"n{len(v):3d} mean {st.mean(v)*100:+5.1f} w/o3 {st.mean(s[:-3])*100:+5.1f} old {st.mean(v[:h])*100:+5.1f} new {st.mean(v[h:])*100:+5.1f} win {sum(x>0 for x in v)/len(v)*100:.0f}% bigwin days {dict(days)}", r
print("B neighbours (3x-type):")
for lo,hi in ((80e3,600e3),(100e3,500e3),(150e3,400e3),(50e3,1e6)):
    for dl,dh in ((0.3,0.85),(0.4,0.8),(0.0,1.01)):
        for tp,sp in ((2.5,0.3),(3.0,0.3),(4.0,0.3),(3.0,0.25),(3.0,0.35)):
            ff=lambda f,lo=lo,hi=hi,dl=dl,dh=dh: base(f) and lo<=(f["mc"] or 0)<hi and dl<=f["dd"]<dh
            s,_=ev(ff,dict(legs=[(1.0,tp)],stop=sp,H=48))
            print(f" mc {lo/1e3:.0f}-{hi/1e3:.0f}K dd {dl}-{dh} {tp}x st{sp}: {s}")
print("A neighbours (quick-type):")
for pool in (30e3,40e3,60e3):
    for vm in (0.7,1.0,1.5):
        ff=lambda f,pool=pool,vm=vm: base(f) and (f["liq"] or 0)>=pool and f["mc"] and f["v24"]<vm*f["mc"]
        s,r=ev(ff,dict(legs=[(1.0,1.25)],stop=0.15,H=12))
        print(f" pool {pool/1e3:.0f}K vol<{vm}mc: {s.split(' bigwin')[0]}")
s,r=ev(lambda f: base(f) and 100e3<=(f["mc"] or 0)<500e3 and 0.4<=f["dd"]<0.8, dict(legs=[(1.0,3.0)],stop=0.3,H=48))
print("B best coins:", sorted(r,key=lambda x:-x[1])[:8])
