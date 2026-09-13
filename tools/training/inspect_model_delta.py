#!/usr/bin/env python3
"""Summarize structural differences between two population-model JSON artifacts."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def short(value, limit=180):
    text=json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))
    return text if len(text)<=limit else text[:limit]+'…'


def walk(a,b,path,counts,samples,max_samples):
    if type(a) is not type(b):
        counts[path]+=1
        if len(samples[path])<max_samples:samples[path].append((short(a),short(b)))
        return
    if isinstance(a,dict):
        keys=set(a)|set(b)
        for key in sorted(keys):
            child=f"{path}.{key}" if path else key
            if key not in a or key not in b:
                counts[child]+=1
                if len(samples[child])<max_samples:samples[child].append((short(a.get(key,'<MISSING>')),short(b.get(key,'<MISSING>'))))
            else: walk(a[key],b[key],child,counts,samples,max_samples)
        return
    if isinstance(a,list):
        if len(a)!=len(b):
            child=path+'.<length>'
            counts[child]+=1
            if len(samples[child])<max_samples:samples[child].append((str(len(a)),str(len(b))))
        for i,(x,y) in enumerate(zip(a,b)):
            walk(x,y,f"{path}[]",counts,samples,max_samples)
        return
    if a!=b:
        counts[path]+=1
        if len(samples[path])<max_samples:samples[path].append((short(a),short(b)))


def node_key(node):
    return node.get('canonical_key') or node.get('id')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--candidate',required=True,type=Path)
    p.add_argument('--max-samples',type=int,default=3)
    args=p.parse_args()
    base=json.loads(args.baseline.read_text(encoding='utf-8'))
    cand=json.loads(args.candidate.read_text(encoding='utf-8'))
    print('TOP_LEVEL_KEYS',sorted(base),sorted(cand))
    for key in sorted(set(base)|set(cand)):
        if key=='nodes':continue
        if base.get(key)!=cand.get(key):print('TOP_DIFF',key,short(base.get(key)),short(cand.get(key)))
    bn=base.get('nodes') or []
    cn=cand.get('nodes') or []
    bmap={node_key(x):x for x in bn}; cmap={node_key(x):x for x in cn}
    print('NODE_COUNTS',len(bn),len(cn),'KEY_COUNTS',len(bmap),len(cmap))
    print('NODE_KEYS_ONLY_BASE',len(set(bmap)-set(cmap)),'ONLY_CANDIDATE',len(set(cmap)-set(bmap)))
    counts=collections.Counter(); samples=collections.defaultdict(list); changed_nodes=0
    for key in sorted(set(bmap)&set(cmap)):
        before=sum(counts.values())
        walk(bmap[key],cmap[key],'node',counts,samples,args.max_samples)
        if sum(counts.values())>before:changed_nodes+=1
    print('CHANGED_NODES',changed_nodes)
    print('DIFF_PATHS')
    for path,count in counts.most_common():
        print(count,path)
        for a,b in samples[path]:print('  ',a,'=>',b)


if __name__=='__main__':main()
