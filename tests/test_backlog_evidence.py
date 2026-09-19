#!/usr/bin/env python3
from __future__ import annotations
import copy, json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import tools.reconcile_backlog_evidence as m

def contract(): return {'lanes':{s:{'typical_issues':[100+i]} for i,s in enumerate('ABCDEFGH',1)}}
def cap_manifest(): return {'capabilities':[]}
def project(rows=None,status='PASS'): return {'status':status,'capabilities':rows or []}
def claims(): return {'events':[],'active_claims':[],'violations':[],'slots':{s:{'status':'IDLE'} for s in 'ABCDEFGH'}}
def recovery(): return {'lanes':{s:{'status':'FREE','active_issue':None,'next_safe_action':{'reason':'none'}} for s in 'ABCDEFGH'}}
def export(): return {'schema':m.EXPORT_SCHEMA,'coverage':{'comments_complete':True,'all_issues_complete':True,'all_pulls_complete':True,'branches_complete':True,'dispatch_issue':225},'comments':[],'issues':[],'pulls':[],'branches':[],'read_errors':[]}
def manifest(rows=None): return {'schema':m.MANIFEST_SCHEMA,'issues':rows or []}
def cat(report,issue): return next(x for x in report['suggestions'] if x['issue']==issue)

def test_closed_lower_state_is_contradiction():
    cm={'capabilities':[{'id':'x','administrative':{'issue':109,'claimed_state':'PRODUCT_INTEGRATED'}}]}
    pr=project([{'id':'x','state':'CONTRACT_READY'}])
    ex=export(); ex['issues']=[{'number':109,'state':'closed'}]
    r=m.build_report(manifest(),cm,pr,claims(),recovery(),ex)
    row=cat(r,109); assert row['category']=='CONTRADICTION'; assert any(x['code']=='CLOSED_BELOW_DECLARED_DOD' for x in row['contradictions'])

def test_open_satisfied_capability_is_close_candidate():
    mf=manifest([{'issue':300,'capability_id':'x','expected_state':'PRODUCT_INTEGRATED','source_refs':['#300'],'gaps':[]}])
    ex=export(); ex['issues']=[{'number':300,'state':'open'}]
    r=m.build_report(mf,cap_manifest(),project([{'id':'x','state':'PROMOTED'}]),claims(),recovery(),ex)
    assert cat(r,300)['category']=='CLOSE_CANDIDATE'

def test_open_below_target_kept_open():
    mf=manifest([{'issue':301,'capability_id':'x','expected_state':'PROMOTED','source_refs':['#301'],'gaps':[]}])
    ex=export(); ex['issues']=[{'number':301,'state':'open'}]
    r=m.build_report(mf,cap_manifest(),project([{'id':'x','state':'CONTRACT_READY'}]),claims(),recovery(),ex)
    assert cat(r,301)['category']=='KEEP_OPEN'

def test_merged_pr_worklog_release_candidate():
    c=claims(); c['events']=[
      {'kind':'worklog','order':1,'slot':'G','issue':302,'pr':77},
      {'kind':'claim','status':'RELEASED','order':2,'slot':'G','issue':302,'pr':77},
    ]
    ex=export(); ex['issues']=[{'number':302,'state':'open'}]; ex['pulls']=[{'number':77,'state':'merged','head':'agent-G/x','base':'main'}]
    r=m.build_report(manifest(),cap_manifest(),project(),c,recovery(),ex)
    assert cat(r,302)['category']=='CLOSE_CANDIDATE'

def test_release_without_worklog_not_candidate():
    c=claims(); c['events']=[{'kind':'claim','status':'RELEASED','order':2,'slot':'G','issue':303,'pr':77}]
    ex=export(); ex['issues']=[{'number':303,'state':'open'}]; ex['pulls']=[{'number':77,'state':'merged'}]
    r=m.build_report(manifest(),cap_manifest(),project(),c,recovery(),ex)
    assert cat(r,303)['category']=='UNKNOWN'

def test_all_gaps_blocked_or_deferred():
    mf=manifest([{'issue':304,'capability_id':None,'expected_state':None,'source_refs':['#304'],'gaps':[
      {'id':'a','status':'BLOCKED','source_ref':'#304','detail':'x'}, {'id':'b','status':'DEFERRED','source_ref':'#304','detail':'y'}]}])
    ex=export(); ex['issues']=[{'number':304,'state':'open'}]
    r=m.build_report(mf,cap_manifest(),project(),claims(),recovery(),ex)
    assert cat(r,304)['category']=='BLOCKED'

def test_open_gap_keeps_open():
    mf=manifest([{'issue':305,'capability_id':None,'expected_state':None,'source_refs':['#305'],'gaps':[{'id':'a','status':'OPEN','source_ref':'#305','detail':'x'}]}])
    ex=export(); ex['issues']=[{'number':305,'state':'open'}]
    r=m.build_report(mf,cap_manifest(),project(),claims(),recovery(),ex)
    assert cat(r,305)['category']=='KEEP_OPEN'

def test_active_claim_missing_branch_is_contradiction():
    c=claims(); c['active_claims']=[{'slot':'C','issue':306,'branch':'agent-C/issue-306-x','pr':88,'claimed_order':1}]
    ex=export(); ex['issues']=[{'number':306,'state':'open'}]; ex['pulls']=[{'number':88,'state':'open','head':'agent-C/issue-306-x'}]; ex['branches']=[]
    rec=recovery(); rec['lanes']['C']={'status':'CLAIMED','active_issue':306,'next_safe_action':{'reason':'x'}}
    r=m.build_report(manifest(),cap_manifest(),project(),c,rec,ex)
    assert cat(r,306)['category']=='CONTRADICTION'; assert any(x['code']=='ACTIVE_CLAIM_BRANCH_MISSING' for x in cat(r,306)['contradictions'])

def test_active_claim_after_release_is_contradiction():
    c=claims(); c['active_claims']=[{'slot':'C','issue':307,'branch':'b','pr':None,'claimed_order':1}]; c['events']=[{'kind':'claim','status':'RELEASED','slot':'C','issue':307,'order':2,'pr':None}]
    ex=export(); ex['issues']=[{'number':307,'state':'open'}]; ex['branches']=['b']
    rec=recovery(); rec['lanes']['C']={'status':'CLAIMED','active_issue':307,'next_safe_action':{'reason':'x'}}
    r=m.build_report(manifest(),cap_manifest(),project(),c,rec,ex)
    assert any(x['code']=='ACTIVE_CLAIM_AFTER_RELEASE' for x in cat(r,307)['contradictions'])

def test_recovery_claim_divergence_is_contradiction():
    c=claims(); c['active_claims']=[{'slot':'D','issue':308,'branch':'b','pr':None,'claimed_order':1}]
    ex=export(); ex['issues']=[{'number':308,'state':'open'}]; ex['branches']=['b']
    r=m.build_report(manifest(),cap_manifest(),project(),c,recovery(),ex)
    assert any(x['code']=='RECOVERY_CLAIM_DIVERGENCE' for x in cat(r,308)['contradictions'])

def test_coordination_violation_propagates():
    c=claims(); c['violations']=[{'code':'ISSUE_LANE_MISMATCH','issue':309,'slot':'E','detail':'bad lane'}]
    ex=export(); ex['issues']=[{'number':309,'state':'open'}]
    r=m.build_report(manifest(),cap_manifest(),project(),c,recovery(),ex)
    assert cat(r,309)['category']=='CONTRADICTION'; assert r['divergences'][0]['code']=='COORDINATION_ISSUE_LANE_MISMATCH'

def test_missing_issue_is_unknown():
    mf=manifest([{'issue':310,'capability_id':None,'expected_state':None,'source_refs':['#310'],'gaps':[]}])
    r=m.build_report(mf,cap_manifest(),project(),claims(),recovery(),export())
    assert cat(r,310)['category']=='UNKNOWN'

def test_deterministic_order_and_categories():
    mf=manifest([{'issue':312,'capability_id':None,'expected_state':None,'source_refs':[],'gaps':[]},{'issue':311,'capability_id':None,'expected_state':None,'source_refs':[],'gaps':[]}])
    ex=export(); ex['issues']=[{'number':312,'state':'open'},{'number':311,'state':'open'}]
    a=m.build_report(mf,cap_manifest(),project(),claims(),recovery(),ex); b=m.build_report(copy.deepcopy(mf),cap_manifest(),project(),claims(),recovery(),copy.deepcopy(ex))
    assert m.stable_json(a)==m.stable_json(b); assert [x['issue'] for x in a['suggestions']]==[311,312]; assert set(a['categories'])==m.CATEGORIES

def test_report_validation_and_compare():
    r=m.build_report(manifest(),cap_manifest(),project(),claims(),recovery(),export()); assert m.validate_report(r)==[]
    with tempfile.TemporaryDirectory() as tmp:
      p=Path(tmp)/'r.json'; content=m.stable_json(r); p.write_text(content); assert m.compare_report_file(p,content)==(True,''); p.write_text(content+'\n'); assert m.compare_report_file(p,content)[0] is False

def test_normalize_merged_and_branches():
    ex=export(); ex['pulls']=[{'number':1,'state':'closed','merged_at':'x','head':'h'}]; ex['branches']=[{'name':'z'},'a']
    n=m.normalize_backlog_export(ex); assert n['pulls'][0]['state']=='MERGED'; assert n['branches']==['a','z']

def main():
    cases=[v for k,v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for case in cases: case()
    print(f'backlog evidence tests: {len(cases)} passed')
if __name__=='__main__': main()
