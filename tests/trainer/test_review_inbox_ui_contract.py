#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAIRS = (
    ("src/analytics/leak-analyzer.js", "site/analytics/leak-analyzer.js"),
    ("src/analytics/review-score-adapter.js", "site/analytics/review-score-adapter.js"),
    ("src/analytics/review-confidence-formatter.js", "site/analytics/review-confidence-formatter.js"),
    ("src/analytics/review-inbox.js", "site/analytics/review-inbox.js"),
)

# #424 T4 — the advanced (confidence/provenance) view is a per-item panel painted
# by the *real* served source against a minimal measured DOM: the plain row must
# stay exactly `[open, status]` (no panel, no toggle, no provenance), the hybrid
# row must carry a panel that is `hidden` until the explicit toggle opens it, and
# every displayed value must come from the mirrored formatter. Non-vacuity is
# replayed: two in-memory mutations of the served bytes must each break the
# harness, so a panel promoted into the simple view or opened by default fails
# here instead of passing on a weaker guard.
ADVANCED_VIEW_RUNTIME = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');

let source=fs.readFileSync('site/index.html','utf8');
const formatterSource=fs.readFileSync('site/analytics/review-confidence-formatter.js','utf8');

// The two regressions the static contract must not accept silently: a panel
// painted opened, and a panel promoted into the row of a hand with no hybrid.
const MUTATIONS={
  'default-open':['panel.hidden=!reviewInboxAdvancedIsOpen(handId);','panel.hidden=false;'],
  'ungated':['if(item.hybrid){','if(true){'],
  // #424 T3 - trois mutations ciblees du seul contrat de *rangee principale* :
  // chacune desactive un maillon du passthrough T2 pour prouver que les cas
  // negatifs (a-d) ne passent pas sur un garde trop faible.
  'no-abstain-row-gate':['if(rowAbstains){','if(false){'],
  'no-too-close-row-gate':['else if(rowTooClose){','else if(false){'],
  'no-estimate-row-gate':['else if(rowEstimated){','else if(false){'],
};
const mutation=process.env.ADVANCED_VIEW_MUTATION||'';
if(mutation){
  const [token,replacement]=MUTATIONS[mutation];
  assert.ok(token&&replacement,'unknown mutation: '+mutation);
  assert.equal(source.split(token).length-1,1,'mutation token must occur exactly once: '+mutation);
  source=source.replace(token,replacement);
}

function extractFn(src,name){
  const start=src.indexOf('function '+name+'(');
  if(start<0)throw new Error('missing '+name);
  let cursor=src.indexOf('(',start+'function '.length),depth=0;
  for(;cursor<src.length;cursor++){
    const ch=src[cursor];
    if(ch==='(')depth++;
    else if(ch===')'){depth--;if(depth===0)break;}
  }
  cursor=src.indexOf('{',cursor);depth=0;
  for(;cursor<src.length;cursor++){
    const ch=src[cursor];
    if(ch==='{')depth++;
    else if(ch==='}'){depth--;if(depth===0)return src.slice(start,cursor+1);}
  }
  throw new Error('unbalanced '+name);
}

// Minimal DOM: only what `paintReviewInboxRows` and the advanced panel touch.
function makeElement(tag){
  return {
    tagName:String(tag),className:'',id:'',hidden:false,textContent:'',innerHTML:'',
    children:[],handlers:{},attrs:{},dataset:{},
    append(...nodes){for(const node of nodes)this.children.push(node);},
    appendChild(node){this.children.push(node);return node;},
    setAttribute(name,value){this.attrs[String(name)]=String(value);},
    getAttribute(name){
      return Object.prototype.hasOwnProperty.call(this.attrs,String(name))?this.attrs[String(name)]:null;
    },
    addEventListener(type,handler){(this.handlers[type]=this.handlers[type]||[]).push(handler);},
    querySelector(){return null;},
    click(){for(const handler of this.handlers.click||[])handler({});},
  };
}
function findAll(node,className,out=[]){
  for(const child of node.children||[]){
    if(String(child.className||'').split(/\s+/).includes(className))out.push(child);
    findAll(child,className,out);
  }
  return out;
}
function flatText(node){
  return [String(node.textContent||''),...(node.children||[]).map(flatText)].join(' ');
}

const hhHandsEl=makeElement('div');
Object.defineProperty(hhHandsEl,'innerHTML',{
  get(){return '';},
  set(value){if(!value)this.children=[];},
});

const sandbox={
  console,Set,String,Number,Boolean,Math,JSON,
  document:{createElement:makeElement},
  hhHandsEl,
  state:{selectedHand:null},
  escapeHtml:s=>String(s==null?'':s),
  formatBB:v=>Number(v).toFixed(2)+' BB',
  reviewHandDisplayMeta:()=>({hero_cards:'A K',result:{state:'win',text:'Gagne'}}),
  modelBRobustnessViewForDecision:()=>null,
  modelBRobustnessStatusText:()=>'robustesse indisponible',
  openReviewInboxItem:()=>{},
  setReviewInboxReviewed:()=>{},
  // #424 F1 : le repli borné ne s'applique qu'à la coque desktop mesurée ; le
  // DOM minimal de ce harnais (pas de coque bornée) le neutralise comme hors
  // `matchMedia("(min-width:901px)")`.
  reviewInboxIsHeightBound:()=>false,
};
vm.createContext(sandbox);
vm.runInContext('var window=globalThis;',sandbox);
vm.runInContext(formatterSource,sandbox);
assert.ok(sandbox.window.PokerReviewConfidenceFormatter,'the mirrored formatter must expose its API');

// The two served inbox-level declarations are replayed from the served bytes,
// never re-typed here: the open state must be the served `Set` and the
// abstention wording the served literal.
function servedConst(name){
  const match=source.match(new RegExp('^const '+name+'=(.*);$','m'));
  assert.ok(match,'missing served constant: '+name);
  return match[1];
}
vm.runInContext([
  'const REVIEW_INBOX_ADVANCED_OPEN='+servedConst('REVIEW_INBOX_ADVANCED_OPEN')+';',
  'const REVIEW_INBOX_ADVANCED_ABSTENTION='+servedConst('REVIEW_INBOX_ADVANCED_ABSTENTION')+';',
  ...[
    'reviewInboxAdvancedIsOpen','reviewInboxAdvancedFormatter','reviewInboxAdvancedProvenance',
    'reviewInboxAdvancedView','reviewInboxAdvancedModelLabel','reviewInboxAdvancedOodLabel',
    'reviewInboxAdvancedField','reviewInboxAdvancedPanel','reviewInboxCloseOtherAdvancedPanels',
    'toggleReviewInboxAdvanced','paintReviewInboxRows','reviewInboxKeepAdvancedVisible',
  ].map(name=>extractFn(source,name)),
].join('\n'),sandbox);

const hybrid={
  schema:'poker-review-hybrid-result/v1',support_state:'SPARSE_ESTIMATED',confidence_level:'MEDIUM',
  is_estimate:true,ev_bb:-0.35,uncertainty_note:'Intervalle large sur cet \u00e9chantillon',
  abstains:false,abstention_reason:null,too_close:false,
  provenance:{route:'HYBRID_BACKOFF',source:'model_b+model_a',model_id:'gbm-2026-09',model_hash:'sha256:abcd',ood_status:'IN_DISTRIBUTION',ood_reason:null},
};
const plainItem={hand_id:'10',status:'TO_REVIEW',status_label:'A revoir',
  coverage:{decisions_covered:1,decisions_total:2,decisions_comparable:1},
  analysis_state:{state:'ANALYSE_DISPONIBLE',reason_codes:[]},
  costliest_decision:{loss_bb:0.5},action_played:'call',action_recommended:'fold',
  position:'IP',spot_family:'SRP',main_street:'Flop',user_review:{reviewed:false}};

function paint(items){
  hhHandsEl.children=[];
  sandbox.paintReviewInboxRows(items.map(item=>({id:Number(item.hand_id)})),new Map(items.map(item=>[String(item.hand_id),item])));
  return hhHandsEl.children;
}
function fieldValues(panel){
  const map={};
  for(const field of findAll(panel,'review-inbox-advanced-field')){
    map[String(field.children[0].textContent)]=String(field.children[1].textContent);
  }
  return map;
}

// 1. (f) The simple view stays simple: a hand without `hybrid` keeps exactly its
//    `[open, status]` row, with no panel, no toggle and no provenance text. This
//    is the pre-existing simple-row/mutation contract, reused as-is for the
//    `item.hybrid` absent regression (never duplicated by the cases below).
{
  const rows=paint([plainItem]);
  assert.equal(rows.length,1);
  assert.equal(rows[0].children.length,2,'la rangee simple garde exactement [open,status]');
  assert.equal(findAll(rows[0],'review-inbox-advanced').length,0,'aucun panneau sans hybrid');
  assert.equal(findAll(rows[0],'review-inbox-advanced-toggle').length,0,'aucun toggle sans hybrid');
  for(const leaked of ['HYBRID_BACKOFF','sha256:abcd','model_b+model_a','Intervalle large']){
    assert.ok(!flatText(rows[0]).includes(leaked),'la vue simple ne peint pas '+leaked);
  }
}

// 2. A hybrid hand carries the collapsed panel and the explicit toggle; the
//    toggle only lives in the status cell, never inside the row action.
{
  const hybridItem={...plainItem,hand_id:'11',hybrid};
  const rows=paint([hybridItem]);
  assert.equal(rows[0].children.length,3);
  const panel=findAll(rows[0],'review-inbox-advanced')[0];
  const toggle=findAll(rows[0],'review-inbox-advanced-toggle')[0];
  assert.ok(panel&&toggle,'panneau et toggle presents');
  assert.equal(panel.hidden,true,'le panneau est replie par defaut');
  assert.equal(toggle.getAttribute('aria-expanded'),'false');
  assert.equal(toggle.getAttribute('aria-controls'),panel.id);
  assert.equal(toggle.textContent,'D\u00e9tails avanc\u00e9s');
  assert.ok(findAll(rows[0].children[1],'review-inbox-advanced-toggle').length===1,'le toggle vit dans la cellule statut');
  assert.ok(!flatText(rows[0].children[0]).includes('sha256:abcd'),'la rangee simple ne peint pas le hash du modele');

  // The displayed values are the formatter outputs, never a local recomputation.
  const values=fieldValues(panel);
  assert.deepEqual(Object.keys(values),[
    'Support','Confiance','EV','Note d\u2019incertitude','Abstention / verdict','Route','Source','Mod\u00e8le','OOD',
  ]);
  assert.equal(values['Support'],'Support limit\u00e9 (estimation)');
  assert.equal(values['Confiance'],'Confiance moyenne');
  assert.equal(values['EV'],'\u2248 -0.35 bb (estimation)');
  assert.equal(values['Note d\u2019incertitude'],'Intervalle large sur cet \u00e9chantillon');
  assert.equal(values['Abstention / verdict'],'\u2014');
  assert.equal(values['Route'],'HYBRID_BACKOFF');
  assert.equal(values['Source'],'model_b+model_a');
  assert.equal(values['Mod\u00e8le'],'gbm-2026-09 \u00b7 sha256:abcd');
  assert.equal(values['OOD'],'IN_DISTRIBUTION');
  assert.ok(findAll(panel,'tone-caution').length>=1,'le support estim\u00e9 porte son ton');

  // The explicit action opens and closes the panel, following `aria-expanded`.
  toggle.click();
  assert.equal(panel.hidden,false,'le toggle ouvre le panneau');
  assert.equal(toggle.getAttribute('aria-expanded'),'true');
  assert.equal(toggle.textContent,'Masquer les d\u00e9tails');
  toggle.click();
  assert.equal(panel.hidden,true,'le toggle referme le panneau');
  assert.equal(toggle.getAttribute('aria-expanded'),'false');

  // An opened panel survives the repaint of a pager step.
  toggle.click();
  const repainted=paint([hybridItem]);
  assert.equal(findAll(repainted[0],'review-inbox-advanced')[0].hidden,false,'un panneau ouvert reste ouvert apres repaint');
}

// 3. Abstention and too-close verdicts keep their dedicated, non-actionable
//    wording on top of the support state.
{
  const abstain={...plainItem,hand_id:'12',hybrid:{...hybrid,abstains:true,support_state:'OOD_UNSUPPORTED'}};
  const abstainValues=fieldValues(findAll(paint([abstain])[0],'review-inbox-advanced')[0]);
  assert.equal(abstainValues['Support'],'Hors distribution (non support\u00e9)');
  assert.equal(abstainValues['Abstention / verdict'],'Abstention \u00b7 aucune action mise en avant');
  assert.doesNotMatch(abstainValues['Abstention / verdict'],/\b(recommand|conseil|jouer|folder|call|raise)\w*/i);

  const close={...plainItem,hand_id:'13',hybrid:{...hybrid,too_close:true,support_state:'LOW_CONFIDENCE_TOO_CLOSE'}};
  const closeValues=fieldValues(findAll(paint([close])[0],'review-inbox-advanced')[0]);
  assert.equal(closeValues['Support'],'Verdict trop proche');
  assert.match(closeValues['Abstention / verdict'],/trop proche/i);
}

// 4. Without the mirrored formatter the panel fabricates nothing: it stays
//    collapsed and empty instead of rendering a invented support state.
{
  delete sandbox.window.PokerReviewConfidenceFormatter;
  const rows=paint([{...plainItem,hand_id:'14',hybrid:{...hybrid}}]);
  const panel=findAll(rows[0],'review-inbox-advanced')[0];
  assert.equal(panel.hidden,true);
  assert.equal(panel.children.length,0,'aucune valeur fabriquee sans formateur');
}

// 5. A hybrid projection without provenance fabricates no trace either: the
//    decision fields render, every absent provenance cell keeps its placeholder.
{
  // Step 4 removed the formatter; reload the served module for the last case.
  vm.runInContext(formatterSource,sandbox);
  assert.ok(sandbox.window.PokerReviewConfidenceFormatter,'the formatter is served again');
  const bare={...plainItem,hand_id:'15',hybrid:{support_state:'ROBUST',confidence_level:'HIGH',ev_bb:0.5}};
  const values=fieldValues(findAll(paint([bare])[0],'review-inbox-advanced')[0]);
  assert.equal(values['Support'],'Support robuste');
  assert.equal(values['Confiance'],'Confiance \u00e9lev\u00e9e');
  assert.equal(values['EV'],'0.50 bb');
  for(const key of ['Note d\u2019incertitude','Abstention / verdict','Route','Source','Mod\u00e8le','OOD']){
    assert.equal(values[key],'\u2014','aucune provenance inventee pour '+key);
  }
}

// 6. #424 T3 - contrat NEGATIF de la *rangee principale* (et non du panneau
//    avance) : la projection `hybrid` deja decidee en amont (passthrough T2) doit
//    (a-b) retirer toute reco / perte EV actionnable quand le modele s'abstient
//    ou sort de la distribution, (c) marquer visiblement une estimation, (d)
//    refuser de designer une action unique quand le verdict est trop proche, et
//    (e) laisser STRONG_SUPPORT / ROBUST strictement inchanges. On lit le HTML
//    reellement peint dans le bouton `open` (cellules "Perte EV" et
//    "Decision"), jamais la projection brute.
const servedValue=expr=>vm.runInContext(expr,sandbox);
const bb=v=>sandbox.formatBB(v);
function rowHtml(item){
  const rows=paint([item]);
  assert.equal(rows.length,1);
  const html=String(rows[0].children[0]?.innerHTML||'');
  assert.ok(html.includes('review-inbox-loss'),'la rangee porte sa cellule perte EV');
  assert.ok(html.includes('review-inbox-decision'),'la rangee porte sa cellule decision');
  return html;
}
const ABSTENTION=servedValue('REVIEW_INBOX_ADVANCED_ABSTENTION');
assert.ok(ABSTENTION&&ABSTENTION.length,'le libelle d abstention servi est lisible');
const RowFormatter=sandbox.window.PokerReviewConfidenceFormatter;
assert.ok(RowFormatter,'le formateur est disponible pour le contrat de rangee');

// (a) OOD_UNSUPPORTED + ev_bb numerique fini + action_recommended presente : la
//     rangee principale ne porte ni la reco ni de perte EV numerique actionnable.
{
  const ood={...plainItem,hand_id:'20',action_played:'call',action_recommended:'fold',total_loss_bb:-0.5,
    hybrid:{...hybrid,support_state:'OOD_UNSUPPORTED',ev_bb:-0.5,abstains:false,too_close:false,is_estimate:false}};
  const html=rowHtml(ood);
  assert.ok(!html.includes('fold'),'(a) aucune reco actionnable pour OOD_UNSUPPORTED');
  assert.ok(!html.includes(bb(-0.5)),'(a) aucune perte EV numerique pour OOD_UNSUPPORTED');
  assert.ok(!html.includes(bb(0.5)),'(a) aucune perte EV de decision pour OOD_UNSUPPORTED');
  assert.ok(html.includes(ABSTENTION),'(a) la rangee porte l etat d abstention');
}

// (b) abstains=true (support_state quelconque) + ev_bb numerique : meme contrat,
//     l'entree autoritaire `abstains` prime sur tout EV numerique.
{
  const abstain={...plainItem,hand_id:'21',action_played:'call',action_recommended:'raise',total_loss_bb:-0.4,
    hybrid:{...hybrid,support_state:'ROBUST',ev_bb:-0.4,abstains:true,too_close:false,is_estimate:false}};
  const html=rowHtml(abstain);
  assert.ok(!html.includes('raise'),'(b) aucune reco actionnable quand le modele s abstient');
  assert.ok(!html.includes(bb(-0.4)),'(b) aucune perte EV numerique quand le modele s abstient');
  assert.ok(!html.includes(bb(0.5)),'(b) aucune perte EV de decision quand le modele s abstient');
  assert.ok(html.includes(ABSTENTION),'(b) la rangee porte l etat d abstention');
}

// (c) SPARSE_ESTIMATED + ev_bb numerique : la rangee principale porte un marqueur
//     visible d'estimation (prefixe et suffixe servis par le formateur) sur la
//     reco et sur l'EV affichee.
{
  const est={...plainItem,hand_id:'22',action_played:'call',action_recommended:'call',total_loss_bb:-0.3,
    hybrid:{...hybrid,support_state:'SPARSE_ESTIMATED',ev_bb:-0.3,abstains:false,too_close:false,is_estimate:false}};
  const html=rowHtml(est);
  assert.ok(RowFormatter.ESTIMATE_PREFIX&&RowFormatter.ESTIMATE_SUFFIX,'le formateur expose ses marqueurs d estimation');
  assert.ok(html.includes(RowFormatter.ESTIMATE_PREFIX),'(c) prefixe d estimation present sur la rangee');
  assert.ok(html.includes(RowFormatter.ESTIMATE_SUFFIX),'(c) suffixe d estimation present sur la rangee');
  assert.ok(
    html.includes(RowFormatter.ESTIMATE_PREFIX+' '+bb(-0.3)+' '+RowFormatter.ESTIMATE_SUFFIX),
    "(c) l'EV affichee porte le marqueur d estimation"
  );
}

// (d) LOW_CONFIDENCE_TOO_CLOSE : aucune action unique ne doit apparaitre comme
//     definitive/mise en avant (`reco <action>`), seul le verdict trop proche est
//     peint sur la rangee principale.
{
  const close={...plainItem,hand_id:'23',action_played:'call',action_recommended:'fold',total_loss_bb:-0.2,
    hybrid:{...hybrid,support_state:'LOW_CONFIDENCE_TOO_CLOSE',ev_bb:-0.2,abstains:false,too_close:false,is_estimate:false}};
  const html=rowHtml(close);
  assert.ok(!html.includes('\u2192 reco'),'(d) aucune reco unique mise en avant');
  assert.ok(!html.includes('reco '),'(d) aucun libelle de reco unique');
  assert.ok(!html.includes('fold'),'(d) aucune action unique mise en avant');
  assert.ok(html.includes(RowFormatter.TOO_CLOSE_NOTICE),'(d) la rangee porte le verdict trop proche');
}

// (e) Regression STRONG_SUPPORT / ROBUST : la reco et la perte EV restent
//     concises et non marquees, exactement comme la rangee historique.
for(const state of ['STRONG_SUPPORT','ROBUST']){
  const item={...plainItem,hand_id:state==='ROBUST'?'25':'24',action_played:'call',action_recommended:'fold',
    total_loss_bb:-0.25,hybrid:{...hybrid,support_state:state,ev_bb:-0.25,abstains:false,too_close:false,is_estimate:false}};
  const html=rowHtml(item);
  assert.ok(html.includes('\u2192 reco fold'),'(e) la reco concise reste inchangee pour '+state);
  assert.ok(html.includes(bb(-0.25)),'(e) la perte EV reste concise pour '+state);
  assert.ok(!html.includes(RowFormatter.ESTIMATE_PREFIX),'(e) aucun marqueur d estimation pour '+state);
  assert.ok(!html.includes(RowFormatter.ESTIMATE_SUFFIX),'(e) aucun suffixe d estimation pour '+state);
}

process.stdout.write(JSON.stringify({status:'PASS',mutation:mutation||null}));
"""


def select_option_values(html: str, element_id: str) -> list:
    """Option values of `<select id="...">` in declaration order."""
    start = html.index(f'<select id="{element_id}">')
    block = html[start:html.index("</select>", start)]
    return re.findall(r'<option value="([^"]*)"', block)


def run_advanced_view_runtime(mutation: str | None = None) -> subprocess.CompletedProcess:
    """Drive the served row painter (and its advanced panel) on a minimal DOM."""
    node = shutil.which("node")
    assert node is not None, "node runtime is required for the review inbox advanced-view contract"
    env = dict(os.environ)
    if mutation:
        env["ADVANCED_VIEW_MUTATION"] = mutation
    else:
        env.pop("ADVANCED_VIEW_MUTATION", None)
    return subprocess.run(
        [node, "-e", ADVANCED_VIEW_RUNTIME],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def main() -> None:
    for source, runtime in PAIRS:
        source_text = (ROOT / source).read_text(encoding="utf-8")
        runtime_text = (ROOT / runtime).read_text(encoding="utf-8")
        assert runtime_text == source_text, (source, runtime)

    # #424 T4 — runtime invariance of the advanced view: the real served
    # `paintReviewInboxRows` source is executed against a minimal measured DOM
    # (no browser, no server). The simple row stays `[open, status]`, the hybrid
    # row carries a collapsed panel opened only by its toggle, and the displayed
    # values are the mirrored formatter outputs.
    #
    # #424 T3 — the same harness carries the *main row* negative contract
    # (cases a-e) and, for case (f), reuses the pre-existing simple-row contract
    # (case 1 here + the `ungated` mutation): a hand without `hybrid` must keep
    # exactly `[open, status]`. It is never re-declared below.
    #
    # Every mutation of the served bytes must break the harness, so a weaker
    # guard (panel promoted/opened, abstention gate dropped, too-close or
    # estimate gate dropped) can never pass here.
    base = run_advanced_view_runtime()
    assert base.returncode == 0, base.stderr
    assert json.loads(base.stdout)["mutation"] is None, base.stdout
    for regression in (
        "default-open",
        "ungated",
        "no-abstain-row-gate",
        "no-too-close-row-gate",
        "no-estimate-row-gate",
    ):
        mutated = run_advanced_view_runtime(regression)
        assert mutated.returncode != 0, (
            f"the {regression} regression must fail the advanced-view harness",
            mutated.stdout,
        )

    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    assert '<script src="./analytics/analysis-state.js"></script>' in index
    assert index.index('<script src="./analytics/analysis-state.js"></script>') < index.index('<script src="./analytics/review-inbox.js"></script>')
    assert '<script src="./analytics/leak-analyzer.js"></script>' in index
    assert '<script src="./analytics/review-score-adapter.js"></script>' in index
    assert '<script src="./analytics/review-inbox.js"></script>' in index
    # #424 T4 — the advanced (confidence/provenance) view is served by its own
    # mirrored module, loaded after the adapter that carries the `hybrid`
    # projection and before the inbox layer that paints it.
    assert '<script src="./analytics/review-confidence-formatter.js"></script>' in index
    assert (
        index.index('<script src="./analytics/review-score-adapter.js"></script>')
        < index.index('<script src="./analytics/review-confidence-formatter.js"></script>')
        < index.index('<script src="./analytics/review-inbox.js"></script>')
    )
    assert "Inbox.queryInbox(inbox,reviewInboxFiltersInput(),reviewInboxSortMode())" in index
    assert "Inbox.setReviewed" in index
    assert 'REVIEW_INBOX_METADATA_DB_KEY="reviewInboxUserMetadataByScope"' in index
    assert 'localDbSet(REVIEW_INBOX_METADATA_DB_KEY,state.reviewInboxUserMetadataByScope||{})' in index
    assert 'localDbGet(REVIEW_INBOX_METADATA_DB_KEY)' in index
    assert 'Review Inbox user metadata must not mutate reviewScores' in index
    assert 'DECISION_NOT_FOUND' in index
    assert 'aucune autre décision n’a été sélectionnée' in index
    assert 'className="review-inbox-open"' in index
    assert 'open.type="button"' in index
    assert 'data-review-inbox-reviewed' in index
    assert 'item.status==="INCOMPLETE_ANALYSIS"' in index
    assert 'item.costliest_decision||item.primary_decision' in index
    assert 'reviewInboxSortMode()' in index
    assert 'EV_LOSS_DESC' in index
    assert 'STATUS_ASC' in index
    assert 'STREET_ASC' in index
    assert 'POSITION_ASC' in index
    assert 'HAND_ID_ASC' in index

    # #395 T4 — the Review inbox opens on a *first level* made of the real-result
    # filter and the sort selector only; status / analysis state / coverage are
    # secondary filters, grouped in their own collapsible panel. A regression
    # that promotes a technical filter back into the primary row (or drops the
    # result filter) must break this test.
    primary_start = index.index('<div class="review-inbox-primary-tools">')
    secondary_start = index.index('<details class="review-inbox-filters">')
    assert primary_start < secondary_start, "the secondary filters must follow the primary tools"
    primary_tools = index[primary_start:secondary_start]
    assert 'id="reviewResultFilter"' in primary_tools
    assert 'id="hhSortSelect"' in primary_tools
    assert 'id="hhListCount"' in primary_tools
    for secondary_id in ("reviewStatusFilter", "reviewAnalysisStateFilter", "reviewCoverageFilter"):
        assert f'id="{secondary_id}"' not in primary_tools, secondary_id

    secondary_panel = index[secondary_start:index.index("</details>", secondary_start)]
    assert "<summary>Statut, analyse et filtres secondaires</summary>" in secondary_panel
    for secondary_id in ("reviewStatusFilter", "reviewAnalysisStateFilter", "reviewCoverageFilter"):
        assert f'id="{secondary_id}"' in secondary_panel, secondary_id
    assert 'id="reviewInboxReasons"' in secondary_panel

    # The real-result filter exposes exactly the schema's result enumeration,
    # behind an "all" sentinel, and feeds the query input.
    result_options = select_option_values(index, "reviewResultFilter")
    assert result_options == ["", "WIN", "LOSS", "EVEN", "UNKNOWN"], result_options
    assert 'result:f.result||""' in index

    # #395 T4 — the sort codes are persisted preference identifiers translated
    # to the poker-review-inbox/v1 sort modes. The five temporal / real-result
    # codes are locked, and TIMESTAMP_DESC (most recent first) stays the default.
    codes_start = index.index("const REVIEW_INBOX_SORT_CODES=[")
    codes_block = index[codes_start:index.index("];", codes_start)]
    sort_codes = re.findall(r'"([a-z_]+)"', codes_block)
    assert "recent_desc" in sort_codes and "recent_asc" in sort_codes, sort_codes

    modes_start = index.index("const REVIEW_INBOX_SORT_MODES={")
    modes_block = index[modes_start:index.index("};", modes_start)]
    sort_modes = dict(re.findall(r'([a-z_]+):"([A-Z_]+)"', modes_block))
    for code in ("TIMESTAMP_DESC", "TIMESTAMP_ASC", "RESULT_GAIN_DESC", "RESULT_LOSS_DESC", "EV_LOSS_DESC"):
        assert code in sort_modes.values(), code
    assert 'const REVIEW_INBOX_DEFAULT_SORT="recent_desc";' in index
    assert sort_modes["recent_desc"] == "TIMESTAMP_DESC", sort_modes
    assert 'hhSort:"recent_desc"' in index
    # The selector is declared in the same order as the persisted codes and its
    # first option is the default (most recent first).
    sort_options = select_option_values(index, "hhSortSelect")
    assert sort_options[0] == "recent_desc", sort_options
    assert set(sort_options) == set(sort_codes), (sort_options, sort_codes)
    # An unknown (or legacy) stored code falls back to the declared default,
    # never to an arbitrary mode.
    assert "return REVIEW_INBOX_SORT_CODES.includes(code)?code:REVIEW_INBOX_DEFAULT_SORT;" in index

    # #395 T5 — the inbox list is bounded by its pager, not by an internal
    # scroll: the bar lives inside the inbox pane, right after the list, and is
    # the only place where the page / hand window is spelled out.
    inbox_pane = index[index.index('id="handSelectionSection"'):index.index('id="strategyPage"')]
    assert 'id="hhHands" class="hh-list"' in inbox_pane
    assert 'id="hhListPager"' in inbox_pane
    assert inbox_pane.index('id="hhHands"') < inbox_pane.index('id="hhListPager"')
    pager_block = inbox_pane[inbox_pane.index('id="hhListPager"'):inbox_pane.index("</nav>", inbox_pane.index('id="hhListPager"'))]
    assert "hidden" in pager_block
    assert 'id="hhPagePrev"' in pager_block and 'id="hhPageNext"' in pager_block
    assert 'id="hhPageInfo"' in pager_block
    assert 'class="app-list-pager-info" role="status" aria-live="polite"' in pager_block
    assert ".hh-list{flex:1 1 auto;min-height:0;max-height:none;overflow:hidden}" in index

    def page_size_const(name: str) -> int:
        match = re.search(rf"const {name}=(\d+);", index)
        assert match is not None, name
        return int(match.group(1))

    page_min = page_size_const("REVIEW_INBOX_PAGE_SIZE_MIN")
    page_max = page_size_const("REVIEW_INBOX_PAGE_SIZE_MAX")
    assert 10 <= page_min <= page_max <= 15, (page_min, page_max)
    assert "const REVIEW_INBOX_PAGE_SIZE_DEFAULT=REVIEW_INBOX_PAGE_SIZE_MIN;" in index
    assert "REVIEW_INBOX_PAGE_FIT_ATTEMPTS=" in index
    assert "function updateReviewInboxPager(" in index
    assert "`Page ${page+1} / ${pages} · mains ${first+1}–${last} sur ${total}`" in index

    # Any first-level change (sort, result filter, known-cards checkbox, and the
    # secondary filter loop) restarts on page 1 and persists the preference.
    for change_block in (
        'state.hhSort=normalizeReviewInboxSortCode(hhSortSelect.value);\n  state.reviewInboxPage=0;',
        'state.reviewInboxFilters.result=reviewResultFilter.value;\n  state.reviewInboxPage=0;',
        "state.hhKnownOnly=hhKnownFilter.checked;\n  state.reviewInboxPage=0;",
        '].forEach(([el,key])=>el?.addEventListener("change",()=>{state.reviewInboxFilters[key]=el.value;state.reviewInboxPage=0;schedulePersistPrefs();renderHistoryHands();}));',
    ):
        assert change_block in index, change_block
    for handler in ("hhSortSelect?.addEventListener", "reviewResultFilter?.addEventListener"):
        start = index.index(handler)
        assert "state.reviewInboxPage=0;" in index[start:index.index("});", start)]
        assert "schedulePersistPrefs();" in index[start:index.index("});", start)]

    # #395 T4 — the result filter and the sort code survive a reload: they are
    # written in the local prefs snapshot and restored through an explicit
    # whitelist, so an unknown stored value can never be injected into the UI.
    prefs = index[index.index("function currentLocalPrefs(){"):index.index("function schedulePersistPrefs(")]
    assert "hhSort:state.hhSort," in prefs
    assert "reviewInboxFilters:{...state.reviewInboxFilters}," in prefs
    restore = index[index.index("const savedSort=String(prefs.hhSort"):index.index("state.hhKnownOnly=!!prefs.hhKnownOnly;")]
    for code in sort_codes:
        assert f'"{code}"' in restore, code
    assert 'if(savedSort==="review_desc") state.hhSort="ev_loss_desc";' in restore
    assert 'result:["","WIN","LOSS","EVEN","UNKNOWN"],' in restore
    assert 'coverage:["","COMPLETE","INCOMPLETE"],' in restore

    # The JSON schema is the single source of truth: every enumeration the UI
    # exposes must be a subset of the schema's, and the item fields consumed by
    # the row (result / coverage / analysis state / status / deep link / review
    # state) must be declared. A UI option that drifts from the schema, or a
    # schema field the UI silently reads, breaks here.
    inbox_schema = json.loads(
        (ROOT / "contracts/analytics/review-inbox.schema.json").read_text(encoding="utf-8")
    )
    schema_sort = set(inbox_schema["$defs"]["review_sort"]["enum"])
    for code in ("TIMESTAMP_DESC", "TIMESTAMP_ASC", "RESULT_GAIN_DESC", "RESULT_LOSS_DESC", "EV_LOSS_DESC"):
        assert code in schema_sort, code
    assert set(sort_modes.values()) <= schema_sort, set(sort_modes.values()) - schema_sort
    assert "EV_LOSS_DESC" in inbox_schema["$defs"]["review_sort"]["description"]

    item_props = inbox_schema["$defs"]["item"]["properties"]
    for field in ("hand_id", "result", "coverage", "analysis_state", "analysis_state_label", "status", "status_label", "deep_link", "user_review"):
        assert field in item_props, field
    assert set(item_props["result"]["properties"]["state"]["enum"]) == {"WIN", "LOSS", "EVEN", "UNKNOWN"}
    assert set(item_props["result"]["properties"]["state"]["enum"]) == set(result_options) - {""}
    assert set(item_props["coverage"]["properties"]["state"]["enum"]) == {"COMPLETE", "INCOMPLETE"}
    assert set(item_props["coverage"]["properties"]["state"]["enum"]) == set(select_option_values(index, "reviewCoverageFilter")) - {""}
    assert set(item_props["status"]["enum"]) == set(select_option_values(index, "reviewStatusFilter")) - {""}
    analysis_state_enum = set(inbox_schema["$defs"]["analysis_state"]["properties"]["state"]["enum"])
    assert analysis_state_enum == set(select_option_values(index, "reviewAnalysisStateFilter")) - {""}
    assert analysis_state_enum == {
        "ANALYSE_DISPONIBLE",
        "ANALYSE_PARTIELLE",
        "CALCUL_EN_COURS",
        "DONNEES_INSUFFISANTES",
        "SPOT_NON_SUPPORTE",
        "ERREUR_CALCUL",
    }
    assert "reason_codes" in inbox_schema["$defs"]["analysis_state"]["properties"]
    assert "reviewInboxReasons" in index and "item.analysis_state?.reason_codes" in index

    # Each row keeps its secondary column: the analysis-state label is the
    # primary user-facing badge (raw reason codes only as a title), the review
    # toggle lives there, and the coverage counters stay in the secondary text.
    row_paint = index[index.index("function paintReviewInboxRows("):index.index("async function clearLoadedHands(")]
    assert 'row.className="hh-hand review-inbox-row"' in row_paint
    assert 'status.className="review-inbox-status";' in row_paint
    assert 'data-analysis-state="${escapeHtml(analysisState?.state||"")}"' in row_paint
    assert 'data-review-inbox-reviewed="${escapeHtml(h.id)}"' in row_paint
    assert "item.analysis_state_label||analysisState?.state||item.status_label" in row_paint
    assert "Support ${item.coverage?.decisions_covered??0}/${item.coverage?.decisions_total??0}" in row_paint
    assert "row.append(open,status);" in row_paint

    # #424 T4 — la vue avancée est un panneau *par item*, construit par des
    # fonctions dédiées, à partir de la seule projection `hybrid` déjà décidée en
    # amont (le formateur mirroir n'est jamais exécuté à la place du modèle : il
    # ne fait que formater). Elle affiche support_state, confidence_level, EV
    # formaté, uncertainty_note, abstention / verdict trop proche et la
    # provenance (route / source / modèle id-hash / OOD).
    formatter = (ROOT / "src/analytics/review-confidence-formatter.js").read_text(encoding="utf-8")
    assert "root.PokerReviewConfidenceFormatter=api;" in formatter
    for exposed in (
        "formatSupportStateLabel",
        "formatConfidenceLevel",
        "formatEvDisplay",
        "formatAbstentionReason",
        "formatTooCloseNotice",
        "formatAdvancedProvenance",
    ):
        assert f"{exposed}," in formatter, exposed
    assert "window.PokerReviewConfidenceFormatter" in index
    for declared in (
        "function reviewInboxAdvancedFormatter(",
        "function reviewInboxAdvancedProvenance(",
        "function reviewInboxAdvancedView(",
        "function reviewInboxAdvancedModelLabel(",
        "function reviewInboxAdvancedOodLabel(",
        "function reviewInboxAdvancedField(",
        "function reviewInboxAdvancedPanel(",
        "function toggleReviewInboxAdvanced(",
    ):
        assert declared in index, declared
    for consumed in (
        "Formatter.formatSupportStateLabel(hybrid.support_state)",
        "Formatter.formatConfidenceLevel(hybrid.confidence_level)",
        "Formatter.formatEvDisplay(hybrid)",
        "Formatter.formatAbstentionReason(hybrid)",
        "Formatter.formatTooCloseNotice(hybrid)",
        "Formatter.formatAdvancedProvenance(item?.hybrid||null)",
    ):
        assert consumed in index, consumed
    # Les marqueurs de la vue avancée, au gabarit servi : chacun des champs
    # demandés a sa ligne, et la provenance est nommée explicitement.
    advanced_panel = index[index.index("function reviewInboxAdvancedPanel("):index.index("function toggleReviewInboxAdvanced(")]
    for field in ("Support", "Confiance", "EV", "Note d’incertitude", "Abstention / verdict", "Route", "Source", "Modèle", "OOD"):
        assert f'reviewInboxAdvancedField("{field}"' in advanced_panel, field
    assert 'reviewInboxAdvancedField("Modèle",reviewInboxAdvancedModelLabel(view.provenance))' in advanced_panel
    assert 'reviewInboxAdvancedField("OOD",reviewInboxAdvancedOodLabel(view.provenance))' in advanced_panel
    assert 'panel.className="review-inbox-advanced";' in advanced_panel
    assert "panel.dataset.reviewInboxAdvanced=String(handId||\"\");" in advanced_panel

    # La vue simple reste la vue par défaut : le panneau est peint *replié* et
    # seul le toggle explicite peut l'ouvrir. Le gabarit de rangée ne contient
    # aucun marqueur de provenance, et une main sans projection hybride ne reçoit
    # ni bouton ni panneau (rien n'est fabriqué à partir de l'absence).
    assert "const REVIEW_INBOX_ADVANCED_OPEN=new Set();" in index
    assert 'const REVIEW_INBOX_ADVANCED_ABSTENTION="Abstention · aucune action mise en avant";' in index
    assert "return REVIEW_INBOX_ADVANCED_OPEN.has(String(handId||\"\"));" in index
    assert "panel.hidden=!reviewInboxAdvancedIsOpen(handId);" in advanced_panel
    toggle = index[index.index("function toggleReviewInboxAdvanced("):index.index("function paintReviewInboxRows(")]
    assert "REVIEW_INBOX_ADVANCED_OPEN.add(id)" in toggle
    assert "REVIEW_INBOX_ADVANCED_OPEN.delete(id)" in toggle
    assert 'button.setAttribute("aria-expanded",String(!open));' in toggle
    assert 'button.textContent=open?"Détails avancés":"Masquer les détails";' in toggle
    row_template = row_paint[row_paint.index("open.innerHTML=`"):row_paint.index("`;", row_paint.index("open.innerHTML=`"))]
    for advanced_only in ("model_hash", "model_id", "ood_status", "uncertainty_note", "provenance", "review-inbox-advanced"):
        assert advanced_only not in row_template, advanced_only
    assert "if(item.hybrid){" in row_paint
    advanced_row = row_paint[row_paint.index("if(item.hybrid){"):]
    for token in (
        "const advanced=reviewInboxAdvancedPanel(item,h.id);",
        'advancedToggle.type="button";advancedToggle.className="review-inbox-advanced-toggle";',
        'advancedToggle.setAttribute("aria-controls",advanced.id);',
        'advancedToggle.setAttribute("aria-expanded",String(reviewInboxAdvancedIsOpen(h.id)));',
        'advancedToggle.addEventListener("click",()=>toggleReviewInboxAdvanced(h.id,advancedToggle,advanced));',
        "status.append(advancedToggle);",
        "row.append(advanced);",
    ):
        assert token in advanced_row, token

    # Le CSS ne doit jamais neutraliser l'attribut `hidden` : le `display:grid`
    # n'est déclaré que sur l'état déplié, donc la rangée simple ne réserve aucune
    # hauteur au détail avancé (la cible de pagination du shell reste mesurée sur
    # la même géométrie déclarée).
    assert ".review-inbox-advanced{grid-column:1/-1;" in index
    assert ".review-inbox-advanced:not([hidden]){display:grid;" in index
    assert ".review-inbox-advanced-toggle[aria-expanded=\"true\"]" in index
    assert ".review-inbox-status:has(.review-inbox-advanced-toggle){flex-wrap:wrap}" in index

    # #394 T3/T1: Review is a dedicated view made of exactly three panes — the
    # pilotage dashboard, the import surface and the review inbox. The import
    # surface is its own pane so the whole import block (advanced options
    # included) fits in the bounded shell instead of sharing the shell height
    # with the dashboard. The manual tools (cards/board, opponents, method,
    # equity, range edition) live in the Spot Lab view, never here.
    review_view = index.split('<div id="mainPage"', 1)[1].split('<div id="strategyPage"', 1)[0]
    assert 'id="reviewDashboard"' in review_view
    assert 'id="historiesSection"' in review_view
    assert 'id="handSelectionSection"' in review_view
    for manual_id in ("opponentsSection", "cardsSection", "rangeDisplaySection", "equitySection"):
        assert f'id="{manual_id}"' not in review_view, manual_id
    assert set(re.findall(r'data-app-subview-panel="([^"]+)"', review_view)) == {"pilotage", "import", "inbox"}
    assert set(re.findall(r'data-app-subview="([^"]+)"', review_view)) == {"pilotage", "import", "inbox"}
    assert (
        '<section id="historiesSection" class="panel wide app-subview-panel"'
        ' role="tabpanel" aria-labelledby="reviewImportTab"'
        ' data-app-subview-panel="import" hidden>'
    ) in review_view
    assert (
        '<button type="button" class="app-subview-tab" id="reviewImportTab"'
        ' role="tab" aria-selected="false" aria-controls="historiesSection"'
        ' data-app-subview="import">Import</button>'
    ) in review_view
    # The dashboard CTA opens the Import pane before clicking the file input, so
    # the picker never depends on an input inside a `hidden` pane.
    assert 'reviewDashboardImportBtn?.addEventListener("click",()=>{activateAppSubview("import");hhFileInput?.click();});' in index

    # #394 T3 — Replayer entry/return contract: the Replayer is opened from the
    # Review inbox by openReplayerPage(), and its "Retour" brings the user back to
    # the Review view with the selected hand preserved. The return is a pure view
    # change: it activates the inbox pane, never scrolls the document, and never
    # re-schedules the background review scoring (T8 contract).
    replayer_entry = index[index.index('function openReplayerPage('):index.index('function returnToHandsPage')]
    assert "state.appView='replayer'" in replayer_entry
    assert 'scheduleBackgroundReviewScoring' not in replayer_entry
    assert 'scheduleAutoCalculate' not in replayer_entry
    back = index[index.index('function returnToHandsPage'):index.index('function leaveHistoryMode')]
    assert 'if(state.hhMode) leaveHistoryMode();' in back
    assert 'activateAppSubview("inbox")' in back
    assert 'scrollIntoView' not in back
    assert 'scheduleBackgroundReviewScoring' not in back
    assert 'state.selectedHand=null' not in back
    assert 'replayerBackBtn?.addEventListener("click",returnToHandsPage);' in index
    # The dashboard leak CTA switches to the Inbox pane the same way, without
    # scrolling the document either.
    leak_cta = index[index.index('function openReviewDashboardLeak'):index.index('function openReviewDashboardTraining')]
    assert 'activateAppSubview("inbox")' in leak_cta
    assert 'scrollIntoView' not in leak_cta

    # #393 T3: the Inbox exposes the canonical analysis-state taxonomy as the
    # primary status label and as an explicit filter, while the raw reason codes
    # stay only in the secondary/technical view.
    assert 'id="reviewAnalysisStateFilter"' in index
    for state in (
        "ANALYSE_DISPONIBLE",
        "ANALYSE_PARTIELLE",
        "CALCUL_EN_COURS",
        "DONNEES_INSUFFISANTES",
        "SPOT_NON_SUPPORTE",
        "ERREUR_CALCUL",
    ):
        assert state in index, state
    assert 'analysis_state:f.analysis_state||""' in index
    assert '[reviewAnalysisStateFilter,"analysis_state"]' in index
    assert 'item.analysis_state_label' in index
    assert 'data-analysis-state' in index
    assert 'reviewInboxReasons' in index
    assert 'Raisons techniques' in index
    assert 'item.analysis_state?.reason_codes' in index

    # The Review scope identity is population-bound: it derives from the Hero
    # strategy resolver and never from a hard-coded "Custom"/"hero-custom" token.
    assert 'hero-custom' not in index
    assert 'strategy_id:"hero-custom"' not in index
    assert 'reviewScopeFromResolution' in index
    assert 'UNAVAILABLE_STRATEGY' in index
    scope_block = index[index.index('function reviewInboxScopeInput()'):index.index('function modelBRobustnessDecisionId')]
    assert 'productHeroStrategyResolution()' in scope_block
    assert 'reviewScopeFromResolution' in scope_block
    assert 'population_id:String(population)' in scope_block
    # #task-a0n: the Review scope consumes the same contextual override status as
    # the Trainer/header chip, never a global presence promoted to active.
    assert 'override:productPersonalOverrideState()' in scope_block

    # #408 blocker 2 / #393 blocker 2: statistical_support is derived from the real
    # per-decision model support with a documented conservative aggregation rule;
    # the counters are non-null integers >= 0 and the explicit availability signal
    # carries unknown/unavailable, so a review decision count can never masquerade
    # as observations and the embedded shape stays in sync with the canonical
    # analysis-state schema + the JS validator.
    schema = json.loads(
        (ROOT / "contracts/analytics/review-inbox.schema.json").read_text(encoding="utf-8")
    )
    support = schema["$defs"]["analysis_state"]["properties"]["statistical_support"]
    for field in ("observations", "distinct_hands"):
        assert support["properties"][field]["type"] == "integer", field
        assert support["properties"][field]["minimum"] == 0, field
    assert set(support["properties"]["availability"]["enum"]) == {
        "AVAILABLE",
        "UNKNOWN",
        "UNAVAILABLE",
    }
    assert "minimum" in support["description"].lower()
    assert "decision" in support["description"].lower()
    inbox_source = (ROOT / "src/analytics/review-inbox.js").read_text(encoding="utf-8")
    assert "statisticalSupportFor" in inbox_source
    assert "observations:comparable.length" not in inbox_source
    assert "distinct_hands:comparable.length?1:0" not in inbox_source

    doc = (ROOT / "docs/analysis-state-contract.md").read_text(encoding="utf-8")
    assert "Règle d'agrégation du support statistique" in doc
    assert "event.support.observations" in doc
    assert "jamais inventé à `1`" in doc

    print("review inbox runtime mirror/UI contract checks: OK")

if __name__ == "__main__":
    main()
