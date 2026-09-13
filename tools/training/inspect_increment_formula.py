#!/usr/bin/env python3
"""Print exact baseline/delta/candidate state for matched incremental Model A nodes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def node_key(node):
    return node.get('canonical_key') or node.get('id')


def dump(label, value):
    print(label, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--candidate',required=True,type=Path)
    p.add_argument('--overlay',required=True,type=Path)
    p.add_argument('--limit',type=int,default=6)
    args=p.parse_args()
    base=json.loads(args.baseline.read_text(encoding='utf-8'))
    cand=json.loads(args.candidate.read_text(encoding='utf-8'))
    overlay=json.loads(args.overlay.read_text(encoding='utf-8'))
    dump('BASE_METHODOLOGY',base.get('methodology'))
    dump('BASE_TRAINING',base.get('training'))
    dump('CANDIDATE_INCREMENTAL_UPDATE',cand.get('incremental_update'))
    bmap={node_key(x):x for x in base.get('nodes',[])}
    cmap={node_key(x):x for x in cand.get('nodes',[])}
    omap={node_key(x):x for x in overlay.get('postflop_nodes',[])}
    shown=0
    for key in sorted(set(bmap)&set(cmap)&set(omap)):
        delta=omap[key]
        if not delta.get('n_delta'):
            continue
        b=bmap[key]; c=cmap[key]
        print('NODE_BEGIN',key)
        dump('CONTEXT',b.get('context'))
        dump('DELTA',{'n_delta':delta.get('n_delta'),'actions':delta.get('actions')})
        dump('BASE_OBS',b.get('population_observed'))
        dump('CAND_OBS',c.get('population_observed'))
        dump('BASE_MODEL',b.get('population_model'))
        dump('CAND_MODEL',c.get('population_model'))
        dump('BASE_COVERAGE',b.get('coverage'))
        dump('CAND_COVERAGE',c.get('coverage'))
        print('NODE_END',key)
        shown+=1
        if shown>=args.limit:break
    print('MATCHED_OVERLAY_NODES',len(set(bmap)&set(cmap)&set(omap)),'OVERLAY_NODES',len(omap))


if __name__=='__main__':main()
