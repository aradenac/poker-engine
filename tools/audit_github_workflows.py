#!/usr/bin/env python3
"""Read-only GitHub Actions inventory for issue #204 phase 1."""
from __future__ import annotations
import argparse, hashlib, json, re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA="poker-engine-workflow-audit/v1"
FROZEN_CURRENT=["recover-issue-107-pfpc.yml","hero-full-169-evidence.yml","hero-unopened-multiposition-generation.yml","hero-pfpc-evidence-validation.yml","persist-issue-107-pfpc.yml","preflop-strategy-benchmark-v2.yml","preflop-strategy-test-pfpc.yml","preflop-strategy-validation-pfpc.yml"]
HISTORICAL_CANDIDATES=["finalize-training-cycle.yml","model-b-build.yml","model-b-conditioned-runtime.yml","model-b-evaluation.yml","model-b-features.yml","model-b-profile-selection.yml","model-b-response-v3.yml","preflop-strategy-support-closed.yml","preflop-strategy-validation-support-closed.yml","preflop-strategy-validation-v2.yml","promotion-gate-final.yml","strategic-benchmark-v3.yml","strategy-candidate-v84.yml","unseen-preflop-context-audit.yml","v84-strategy-candidate.yml"]

def unquote(v:str)->str:
    v=v.strip()
    return v[1:-1] if len(v)>=2 and v[0]==v[-1] and v[0] in "'\"" else v

def inline_list(v:str)->list[str]:
    v=v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [unquote(x.strip()) for x in v[1:-1].split(",") if x.strip()]
    return [unquote(v)] if v else []

def section(lines:list[str],key:str)->list[str]:
    start=next((i+1 for i,l in enumerate(lines) if l.rstrip()==key+":"),None)
    if start is None: return []
    out=[]
    for l in lines[start:]:
        if l.strip() and not l.startswith((" ","\t")) and not l.lstrip().startswith("#"): break
        out.append(l)
    return out

def yaml_list(seg:list[str],indent:int,field:str)->list[str]:
    rx=re.compile(r"^\s{"+str(indent)+r"}"+re.escape(field)+r":\s*(.*)$")
    for i,l in enumerate(seg):
        m=rx.match(l)
        if not m: continue
        if m.group(1).strip(): return inline_list(m.group(1))
        out=[]
        for n in seg[i+1:]:
            if not n.strip(): continue
            ni=len(n)-len(n.lstrip(" "))
            if ni<=indent: break
            im=re.match(r"^\s*-\s*(.+?)\s*$",n)
            if im: out.append(unquote(im.group(1)))
        return out
    return []

def parse_triggers(lines:list[str])->dict[str,Any]:
    scalar=next((l for l in lines if re.match(r"^on:\s*\S",l)),None)
    if scalar: return {e:{} for e in inline_list(scalar.split(":",1)[1])}
    b=section(lines,"on"); starts=[]
    for i,l in enumerate(b):
        m=re.match(r"^  ([A-Za-z_][\w-]*):",l)
        if m: starts.append((i,m.group(1)))
    out={}
    for pos,(s,event) in enumerate(starts):
        e=starts[pos+1][0] if pos+1<len(starts) else len(b); seg=b[s+1:e]
        cfg={k:yaml_list(seg,4,f) for k,f in [("paths","paths"),("paths_ignore","paths-ignore"),("branches","branches"),("branches_ignore","branches-ignore"),("types","types"),("workflows","workflows")]}
        out[event]={k:v for k,v in cfg.items() if v}
    return out

def parse_concurrency(lines:list[str])->dict[str,Any]:
    b=section(lines,"concurrency")
    if not b: return {}
    out={}
    for l in b:
        m=re.match(r"^\s{2}(group|cancel-in-progress):\s*(.+?)\s*$",l)
        if m:
            key="cancel_in_progress" if m.group(1)=="cancel-in-progress" else "group"; v=unquote(m.group(2))
            out[key]=(v=="true") if key=="cancel_in_progress" and v in ("true","false") else v
    return out

def parse_jobs(lines:list[str])->list[dict[str,Any]]:
    b=section(lines,"jobs"); starts=[]
    for i,l in enumerate(b):
        m=re.match(r"^  ([A-Za-z_][\w-]*):\s*$",l)
        if m: starts.append((i,m.group(1)))
    out=[]
    for pos,(s,jid) in enumerate(starts):
        e=starts[pos+1][0] if pos+1<len(starts) else len(b); job={"id":jid}
        for l in b[s+1:e]:
            m=re.match(r"^\s{4}(runs-on|needs|uses):\s*(.+?)\s*$",l)
            if not m: continue
            if m.group(1)=="runs-on": job["runner"]=unquote(m.group(2))
            elif m.group(1)=="needs": job["needs"]=inline_list(m.group(2))
            else: job["uses"]=unquote(m.group(2))
        out.append(job)
    return out

def role(path:Path,name:str)->str:
    h=(path.name+" "+name).lower()
    if re.search(r"trainer|range-editor|compliance|pack-catalog",h): return "product_browser_validation"
    if re.search(r"release|promotion",h): return "release_promotion"
    if re.search(r"dataset|ingest|population-certification|materialize-certified",h): return "dataset_population"
    if "model-b" in h: return "model_b"
    if "hero" in h: return "hero_preflop"
    if re.search(r"preflop|strategy",h): return "preflop_strategy"
    if re.search(r"full-hand|arena|game-core|benchmark",h): return "simulation_benchmark"
    if "training" in h: return "training_orchestration"
    return "validation_or_utility"

def parse_workflow(path:Path,root:Path)->dict[str,Any]:
    text=path.read_text(encoding="utf-8"); lines=text.splitlines()
    nm=re.search(r"^name:\s*(.+?)\s*$",text,re.M); name=unquote(nm.group(1)) if nm else path.name
    triggers=parse_triggers(lines); jobs=parse_jobs(lines); conc=parse_concurrency(lines)
    patterns={"checkout":r"actions/checkout@","setup_python":r"actions/setup-python@","setup_node":r"actions/setup-node@","pip_install":r"(?:\bpip(?:3)?\s+install\b|python3?\s+-m\s+pip\s+install)","playwright_install":r"playwright\s+install","npm_install":r"\bnpm\s+(?:ci|install)\b","upload_artifact":r"actions/upload-artifact@","download_artifact":r"(?:actions/download-artifact@|\bgh\s+run\s+download\b)"}
    dup={k:len(re.findall(v,text)) for k,v in patterns.items()}
    uploads=[]
    for i,l in enumerate(lines):
        if "actions/upload-artifact@" in l:
            for n in lines[i+1:i+15]:
                m=re.match(r"^\s+name:\s*(.+?)\s*$",n)
                if m: uploads.append(unquote(m.group(1))); break
    deps=sorted({x for cfg in triggers.values() for x in cfg.get("workflows",[])})
    score=len(jobs)+2*dup["checkout"]+2*dup["setup_python"]+2*dup["setup_node"]+2*dup["pip_install"]+5*dup["playwright_install"]+2*dup["npm_install"]+2*dup["upload_artifact"]+2*dup["download_artifact"]+(2 if re.search(r"train|benchmark|simulation|arena|fit|evaluation|candidate|strategy",path.name+" "+name,re.I) else 0)
    life="frozen_current" if path.name in FROZEN_CURRENT else "historical_candidate" if path.name in HISTORICAL_CANDIDATES else "current"
    scopes=sorted({p.lstrip("!").split("/")[0] for cfg in triggers.values() for p in cfg.get("paths",[]) if p})
    return {"path":path.relative_to(root).as_posix(),"sha256":hashlib.sha256(text.encode()).hexdigest(),"name":name,"role":role(path,name),"lifecycle":life,"triggers":triggers,"path_scopes":scopes,"concurrency":conc,"jobs":jobs,"artifacts":{"uploads":uploads,"download_operations":dup["download_artifact"]},"workflow_run_dependencies":deps,"duplication_primitives":dup,"cost_proxy":{"score":score,"band":"high" if score>=18 else "medium" if score>=8 else "low","method":"static structural proxy; not GitHub-billed minutes"}}

def audit_repository(root:Path)->dict[str,Any]:
    paths=sorted([*(root/".github/workflows").glob("*.yml"),*(root/".github/workflows").glob("*.yaml")])
    w=[parse_workflow(p,root) for p in paths]; totals=Counter(); groups=defaultdict(list); names={x["name"]:x["path"] for x in w}; edges=[]
    for x in w:
        totals.update(x["duplication_primitives"])
        if x["concurrency"].get("group"): groups[x["concurrency"]["group"]].append(x["path"])
        for d in x["workflow_run_dependencies"]: edges.append({"type":"workflow_run","from_name":d,"from_path":names.get(d,""),"to_path":x["path"]})
    return {"schema":SCHEMA,"active_definition":"workflow file present in audited checkout","workflow_count":len(w),"workflows":w,"aggregate":{"lifecycle_counts":dict(Counter(x["lifecycle"] for x in w)),"role_counts":dict(Counter(x["role"] for x in w)),"cost_band_counts":dict(Counter(x["cost_proxy"]["band"] for x in w)),"duplication_primitives":dict(totals),"concurrency":{"groups":dict(groups),"cancel_true_count":sum(x["concurrency"].get("cancel_in_progress") is True for x in w),"cancel_false_count":sum(x["concurrency"].get("cancel_in_progress") is False for x in w),"no_concurrency_count":sum(not x["concurrency"] for x in w)},"workflow_run_edges":edges,"historical_candidates":[x["path"] for x in w if x["lifecycle"]=="historical_candidate"],"frozen_current":[x["path"] for x in w if x["lifecycle"]=="frozen_current"]}}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument("--json",type=Path); args=ap.parse_args()
    data=audit_repository(args.root.resolve()); out=json.dumps(data,indent=2,sort_keys=True)+"\n"
    if args.json: args.json.parent.mkdir(parents=True,exist_ok=True); args.json.write_text(out,encoding="utf-8"); print(args.json)
    else: print(out,end="")
    return 0
if __name__=="__main__": raise SystemExit(main())
