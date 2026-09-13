#!/usr/bin/env python3
"""Check deterministic coverage/ranking formulas against a persisted population model."""
from __future__ import annotations
import argparse,json
from pathlib import Path


def key(n): return n.get('canonical_key') or n.get('id') or ''

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True,type=Path);args=p.parse_args()
    d=json.loads(args.model.read_text(encoding='utf-8'));nodes=d['nodes']
    total=sum(int((n.get('coverage') or {}).get('population_decisions') or 0) for n in nodes)
    hypotheses={
      'count_key':sorted(nodes,key=lambda n:(-int((n.get('coverage') or {}).get('population_decisions') or 0),key(n))),
      'count_original':sorted(enumerate(nodes),key=lambda t:(-int((t[1].get('coverage') or {}).get('population_decisions') or 0),t[0])),
    }
    for name,items in hypotheses.items():
        seq=[x[1] for x in items] if name=='count_original' else items
        rank_bad=[];flag_bad=[];cum=0
        for rank,n in enumerate(seq,1):
            cov=n.get('coverage') or {};stored=n.get('rank_population')
            if stored!=rank and len(rank_bad)<5:rank_bad.append((rank,stored,key(n),cov.get('population_decisions')))
            count=int(cov.get('population_decisions') or 0);cum+=count
            frac=cum/total if total else 0
            # Node belongs to a core set when the cumulative mass including that node is <= threshold,
            # with the first boundary-crossing node included as well.
            prev=(cum-count)/total if total else 0
            predicted={f'core{pct}': prev < pct/100 for pct in (90,95,99)}
            for field,val in predicted.items():
                if bool(cov.get(field))!=val and len(flag_bad)<5:flag_bad.append((field,key(n),cov.get(field),val,prev,frac,count,rank))
        print(name,'rank_bad_count_sample',rank_bad,'flag_bad_sample',flag_bad)
    print('total',total,'dataset_total',sum((d.get('dataset',{}).get('mode_train_population_decisions') or {}).values()))

if __name__=='__main__':main()
