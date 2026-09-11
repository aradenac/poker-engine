#!/usr/bin/env python3
from pathlib import Path
import sys

src=Path(sys.argv[1]); dst=Path(sys.argv[2]) if len(sys.argv)>2 else src.with_name('poker_range_equity_offline_multiway_v82.html')
s=src.read_text(encoding='utf-8')

def one(old,new,label):
    global s
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label}: expected 1 match, got {n}')
    s=s.replace(old,new,1)

one('<title>Poker Range Equity — Offline v81</title>','<title>Poker Range Equity — Offline v82</title>','title')
one("""    const veryLow=metas.filter(x=>String(x?.confidence||'').toLowerCase()==='very_low');
    const sparseVeryLow=veryLow.filter(x=>Number(x?.observations)<5);
    const localOod=veryLow.filter(x=>{
      const n=Number(x?.observations),p90=Number(x?.p90),price=Number(x?.facingPricePot);
      return n>=5&&Number.isFinite(p90)&&p90>0&&Number.isFinite(price)&&price>p90+1e-9;
    });
    return {floor,veryLow:veryLow.length>0,sparseVeryLow,localOod};""",
"""    const veryLow=metas.filter(x=>String(x?.confidence||'').toLowerCase()==='very_low');
    const weakConfidence=metas.filter(x=>['low','very_low'].includes(String(x?.confidence||'').toLowerCase()));
    const sparseVeryLow=veryLow.filter(x=>Number(x?.observations)<5);
    const outsideLocalP90=rows=>rows.filter(x=>{
      const n=Number(x?.observations),p90=Number(x?.p90),price=Number(x?.facingPricePot);
      return n>=5&&Number.isFinite(p90)&&p90>0&&Number.isFinite(price)&&price>p90+1e-9;
    });
    const localOod=outsideLocalP90(veryLow),weakLocalOod=outsideLocalP90(weakConfidence);
    return {floor,veryLow:veryLow.length>0,sparseVeryLow,localOod,weakLocalOod};""",'weak local support')
one("""    const extreme=(c.kind==='jam')||(Number.isFinite(ratio)&&ratio>=2.0);
    const weakExtreme=extreme&&Number.isFinite(obs)&&obs<10;""",
"""    const extreme=(c.kind==='jam')||(Number.isFinite(ratio)&&ratio>=2.0);
    if(!c.tree.sanityInvalid&&extreme&&c.kind!=='actual'&&rs.weakLocalOod.length){
      const x=rs.weakLocalOod[0],price=Number(x.facingPricePot),p90=Number(x.p90);
      invalidate(c.tree,`Agression extrême hors P90 local sur nœud peu fiable : ${price.toFixed(3)} > ${p90.toFixed(3)} (${String(x.confidence||'').toLowerCase()}, ${Number(x.observations)||0} observations).`);
    }
    const weakExtreme=extreme&&Number.isFinite(obs)&&obs<10;""",'extreme low-confidence guard')
one("""aggressorSizePot:(+d.potBeforeBB||0)>0?(+d.costBB||0)/(+d.potBeforeBB):0}});""",
"""aggressorSizePot:Number.isFinite(+d.aggressorSizePot)?+d.aggressorSizePot:((+d.potBeforeBB||0)>0?(+d.costBB||0)/(+d.potBeforeBB):0),nominalAggressorSizePot:(+d.potBeforeBB||0)>0?(+d.costBB||0)/(+d.potBeforeBB):0}});""",'worker effective aggressor ratio')
one("'evtree-v81-effectivepot-potscaled-finalev-sparse5-extreme10-p90'","'evtree-v82-effectivepot-lowp90-potscaled-finalev'",'cache signature')
one("version:'v81'","version:'v82'",'policy benchmark version')
one('version:"v81"','version:"v82"','AI export version')
one('/* v81 effective-stack response-pot correction active */','/* v81 effective-stack response-pot correction active */\n/* v82 low-confidence extreme local-P90 guard active */','marker')
for needle in ['weakLocalOod','Agression extrême hors P90 local','nominalAggressorSizePot','evtree-v82-effectivepot-lowp90','version:"v82"']:
    if needle not in s: raise SystemExit('missing '+needle)
dst.write_text(s,encoding='utf-8')
print(dst)
