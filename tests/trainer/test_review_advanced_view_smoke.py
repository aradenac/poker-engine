#!/usr/bin/env python3
"""#424 T6 - Smoke Review : parite site + non-regression filtres/pagination.

Verification statique (aucun navigateur, aucun serveur), dans le style des
contrats `*_ui_contract.py` : on lit les octets servis de `site/index.html` et
des miroirs Review, et on confirme

  * la parite octet-a-octet entre les sources d'edition `src/analytics/*` et les
    modules servis `site/analytics/*` (un miroir desynchronise casse ici) ;
  * que le panneau « vue avancee » ajoute en T4 est present et correctement
    reference dans la coque servie : ordre des `<script>`, garde par item,
    cablage du toggle, panneau replie par defaut et CSS `:not([hidden])` ;
  * que les filtres/pagination du Review restent cables comme #395/#424 les a
    laisses : pager borne, codes de tri persistes, filtre de resultat et remise
    a la page 1 a chaque changement de premier niveau.

La non-vacuite est rejouee en memoire : chaque mutation des octets servis doit
faire echouer la meme verification, donc le smoke ne peut pas passer sur un garde
plus faible (panneau ouvert par defaut, panneau non garde par `hybrid`, tag de
script retire, pager supprime).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Modules Review dont la source d'edition et le miroir servi doivent rester
# identiques (la vue avancee T4 vit dans `review-confidence-formatter.js`,
# consomme la projection `hybrid` du `review-score-adapter.js` et est peinte par
# `review-inbox.js`).
PAIRS = (
    ("src/analytics/analysis-state.js", "site/analytics/analysis-state.js"),
    ("src/analytics/leak-analyzer.js", "site/analytics/leak-analyzer.js"),
    ("src/analytics/review-score-adapter.js", "site/analytics/review-score-adapter.js"),
    ("src/analytics/review-confidence-formatter.js", "site/analytics/review-confidence-formatter.js"),
    ("src/analytics/review-inbox.js", "site/analytics/review-inbox.js"),
    ("src/analytics/review-dashboard.js", "site/analytics/review-dashboard.js"),
)

# Ordre de chargement attendu des modules Review dans la coque servie.
SCRIPT_ORDER = (
    '<script src="./analytics/analysis-state.js"></script>',
    '<script src="./analytics/review-score-adapter.js"></script>',
    '<script src="./analytics/review-confidence-formatter.js"></script>',
    '<script src="./analytics/review-inbox.js"></script>',
    '<script src="./analytics/review-dashboard.js"></script>',
)

# Fonctions dediees de la vue avancee : presentes au gabarit servi.
ADVANCED_DECLARATIONS = (
    "function reviewInboxAdvancedFormatter(",
    "function reviewInboxAdvancedProvenance(",
    "function reviewInboxAdvancedView(",
    "function reviewInboxAdvancedModelLabel(",
    "function reviewInboxAdvancedOodLabel(",
    "function reviewInboxAdvancedField(",
    "function reviewInboxAdvancedPanel(",
    "function toggleReviewInboxAdvanced(",
)

# Les valeurs formatees viennent du miroir de confiance : aucune n'est fabriquee
# dans la coque.
ADVANCED_CONSUMPTION = (
    "Formatter.formatSupportStateLabel(hybrid.support_state)",
    "Formatter.formatConfidenceLevel(hybrid.confidence_level)",
    "Formatter.formatEvDisplay(hybrid)",
    "Formatter.formatAbstentionReason(hybrid)",
    "Formatter.formatTooCloseNotice(hybrid)",
    "Formatter.formatAdvancedProvenance(item?.hybrid||null)",
)

# Câblage de la vue avancee dans la rangee : garde par item, panneau replie par
# defaut, toggle dans la cellule statut, panneau ajoute a la rangee.
ADVANCED_WIRING = (
    "if(item.hybrid){",
    "const advanced=reviewInboxAdvancedPanel(item,h.id);",
    'advancedToggle.type="button";advancedToggle.className="review-inbox-advanced-toggle";',
    'advancedToggle.setAttribute("aria-controls",advanced.id);',
    'advancedToggle.setAttribute("aria-expanded",String(reviewInboxAdvancedIsOpen(h.id)));',
    'advancedToggle.addEventListener("click",()=>toggleReviewInboxAdvanced(h.id,advancedToggle,advanced));',
    "status.append(advancedToggle);",
    "row.append(advanced);",
    "panel.hidden=!reviewInboxAdvancedIsOpen(handId);",
)

# Le CSS ne neutralise jamais l'attribut `hidden` : le `display:grid` n'est
# declare que sur l'etat deplie, donc la rangee simple ne reserve aucune hauteur.
ADVANCED_CSS = (
    ".review-inbox-advanced{grid-column:1/-1;",
    ".review-inbox-advanced:not([hidden]){display:grid;",
    '.review-inbox-advanced-toggle[aria-expanded="true"]',
    ".review-inbox-status:has(.review-inbox-advanced-toggle){flex-wrap:wrap}",
)

# Non-regression filtres/pagination du Review (#395/#424).
FILTERS_PAGINATION = (
    'id="reviewResultFilter"',
    'id="hhListPager"',
    'id="hhPagePrev"',
    'id="hhPageNext"',
    'id="hhPageInfo"',
    'class="app-list-pager-info" role="status" aria-live="polite"',
    "const REVIEW_INBOX_PAGE_SIZE_MIN=10;",
    "const REVIEW_INBOX_PAGE_SIZE_MAX=15;",
    "const REVIEW_INBOX_PAGE_SIZE_DEFAULT=REVIEW_INBOX_PAGE_SIZE_MIN;",
    "function updateReviewInboxPager(",
    "const REVIEW_INBOX_SORT_CODES=[",
    'const REVIEW_INBOX_DEFAULT_SORT="recent_desc";',
    "state.reviewInboxPage=0;",
    "state.hhSort=normalizeReviewInboxSortCode(hhSortSelect.value);",
)

# #424 F1 — le repli borne qui garde la ligne ouverte et son panneau atteignables
# dans la coque desktop (`overflow:hidden`). Le mecanisme est une couche de
# presentation pure : la declaration du helper, son appel par le toggle (la
# ligne ouverte), sa re-application apres une re-peinture (`renderHistoryHands`)
# et apres un re-layout (`relayoutReviewInbox`), et la regle CSS qui donne son
# effet (une ligne repliee ne reserve plus de hauteur).
FOLD_WIRING = (
    "function reviewInboxKeepAdvancedVisible(){",
    "  reviewInboxKeepAdvancedVisible();\n  return !open;",
    "  renderReviewInboxPage(hands,byId);\n  reviewInboxKeepAdvancedVisible();\n}",
    "[data-review-inbox-folded]{display:none}",
)

# #424 F2 — la marque d'estimation de la *rangee principale* est independante du
# verdict trop proche. `rowEstimated` reflète le drapeau `is_estimate` *ou* le
# support `SPARSE_ESTIMATED` (les deux signaux du formateur, jamais recalculés),
# et la marque `ESTIMATE_PREFIX/ESTIMATE_SUFFIX` est appliquee dans le
# branchement too-close comme dans le branchement estimation, via un seul
# applier qui ne lit que les exports du formateur.
ROW_ESTIMATE_WIRING = (
    "const rowEstimated=!rowAbstains&&!!rowFormatter&&(rowHybrid.is_estimate===true||rowSupportState===rowFormatter.SUPPORT_STATES.SPARSE_ESTIMATED);",
    "const markEstimated=()=>{",
    "ESTIMATE_PREFIX+' '+decisionText+' '+rowFormatter.ESTIMATE_SUFFIX",
    "if(rowEstimated)markEstimated();",
    "else if(rowEstimated){",
)

# Mutations en memoire : chacune doit faire echouer `check`, sinon le smoke
# passerait sur un garde trop faible. Le jeton doit etre present une seule fois.
MUTATIONS = {
    # un module de la vue avancee retire de la coque -> ordre/presence casse
    "drop-formatter-script": (
        '<script src="./analytics/review-confidence-formatter.js"></script>',
        "",
    ),
    # la vue avancee n'est plus gardee par la projection hybride
    "ungated-advanced": ("if(item.hybrid){", "if(true){"),
    # le panneau est peint ouvert au lieu d'etre replie par defaut
    "default-open": (
        "panel.hidden=!reviewInboxAdvancedIsOpen(handId);",
        "panel.hidden=false;",
    ),
    # le pager de l'inbox disparait
    "drop-pager": ('id="hhListPager"', ""),
    # le repli borne perd son effet CSS : une ligne repliee reserverait sa hauteur
    "drop-fold-css": ("[data-review-inbox-folded]{display:none}", ""),
    # #424 F2 — `rowEstimated` ignore le drapeau independant `is_estimate`
    "row-estimate-ignores-flag": ("rowHybrid.is_estimate===true||", ""),
    # #424 F2 — la marque d'estimation disparait derriere le verdict trop proche
    "row-estimate-lost-behind-too-close": ("if(rowEstimated)markEstimated();", "void 0;"),
}


def check(index_text: str) -> None:
    """Assert the served shell still carries the reviewed wiring.

    Raises AssertionError (never a bare lookup error) on any drift so the
    mutation replay can treat "raises" and "passes" as the two states to test.
    """

    def present(token: str, label: str | None = None) -> None:
        assert token in index_text, label or token

    # 1. Parite de chargement : les modules Review sont presents et charges dans
    #    un ordre qui laisse la vue avancee disponible avant son consommateur.
    for tag in SCRIPT_ORDER:
        present(tag, f"missing review script tag: {tag}")
    positions = [index_text.index(tag) for tag in SCRIPT_ORDER]
    assert positions == sorted(positions), "review modules must keep their load order"

    # 2. Le miroir de confiance expose le formateur consomme par la coque.
    present("window.PokerReviewConfidenceFormatter")

    # 3. La vue avancee est peinte par des fonctions dediees qui ne lisent que les
    #    sorties formatees (aucun recalcul local).
    for declared in ADVANCED_DECLARATIONS:
        present(declared)
    for consumed in ADVANCED_CONSUMPTION:
        present(consumed)

    # 4. Câblage par item : garde `hybrid`, toggle dans la cellule statut,
    #    panneau replie par defaut, panneau ajoute a la rangee.
    for token in ADVANCED_WIRING:
        present(token)

    # 5. Le CSS respecte l'attribut `hidden` (panneau replie = aucune hauteur).
    for token in ADVANCED_CSS:
        present(token)

    # 6. Non-regression filtres/pagination du Review.
    for token in FILTERS_PAGINATION:
        present(token)

    # 7. #424 F1 — le repli borne qui garde la ligne ouverte atteignable dans la
    #    coque bornee (`overflow:hidden`) : helper declare, appele par le toggle,
    #    re-applique apres une re-peinture/un re-layout, et sa regle CSS.
    for token in FOLD_WIRING:
        present(token)

    # 8. #424 F2 — la marque d'estimation de la rangee principale est
    #    independante du verdict trop proche : `rowEstimated` lit `is_estimate`,
    #    et l'applier unique est appele dans les deux branchements.
    for token in ROW_ESTIMATE_WIRING:
        present(token)


# --------------------------------------------------------------------------- #
# #424 F1 — smoke reproductible de l'ouverture du panneau avance sur une page
# pleine. Les fonctions *reellement servies* (`renderReviewInboxPage`,
# `paintReviewInboxRows` remplace par un peintre mesure, `toggleReviewInboxAdvanced`
# et `reviewInboxKeepAdvancedVisible`) sont executees contre un DOM borne minimal ou
# `scrollHeight` est derive des lignes peintes (une ligne repliee — attribut
# `data-review-inbox-folded` *et* regle CSS presente — ne reserve plus de
# hauteur), exactement comme un navigateur le ferait. Le test ouvre le panneau
# de la derniere ligne d'une page pleine et exige que la ligne et son panneau
# restent atteignables (`scrollHeight <= clientHeight`, aucune ligne ouverte
# repliee), puis rejoue trois mutations en memoire : sans l'appel de repli, sans
# l'effet du repli, ou sans la regle CSS, la page deborde derriere la coque.
FOLD_HARNESS_SCRIPT = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');

const FOLD_RULE='[data-review-inbox-folded]{display:none}';
const MUTATIONS={
  // le toggle n'appelle plus le repli borne
  'no-fold-call':[
    '  reviewInboxKeepAdvancedVisible();\n  return !open;',
    '  return !open;',
  ],
  // le repli est appele mais ne replie jamais aucune ligne
  'fold-keeps-rows-visible':[
    '    row.setAttribute("data-review-inbox-folded","");',
    '    void row;',
  ],
  // la regle CSS du repli disparait : une ligne repliee reserverait sa hauteur
  'drop-fold-css':[FOLD_RULE,''],
};
let source=fs.readFileSync('site/index.html','utf8');
const mutation=process.env.ADVANCED_FOLD_MUTATION||'';
if(mutation){
  const [token,replacement]=MUTATIONS[mutation];
  assert.ok(typeof token==='string'&&token.length>0,'unknown mutation: '+mutation);
  assert.equal(source.split(token).length-1,1,'mutation token must occur exactly once: '+mutation);
  source=source.replace(token,replacement);
}
// Une ligne repliee ne libere sa hauteur que si la regle servie est presente :
// c'est ce qui relie le modele mesure a l'octet servi.
const foldCss=source.includes(FOLD_RULE);

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
function servedConst(src,name){
  const match=src.match(new RegExp('^const '+name+'=(.*);$','m'));
  assert.ok(match,'missing served constant: '+name);
  return match[1];
}
function pageSizeConsts(src){
  const re=/^const (REVIEW_INBOX_PAGE_SIZE_[A-Z]+|REVIEW_INBOX_ROW_PITCH_[A-Z]+|REVIEW_INBOX_PAGE_FIT_ATTEMPTS)=[^\n]*$/gm;
  const consts=src.match(re)||[];
  assert.ok(consts.length>=6,'page-size constants must be declared: '+consts.length);
  return consts.join('\n');
}

// Minimal measured DOM: a row owns a base height plus, when its advanced panel
// is open, the panel height. A row carrying `data-review-inbox-folded` (and the
// served CSS rule) leaves the flow, exactly like `display:none`.
const tokens=el=>String(el.className||'').split(/\s+/).filter(Boolean);
function matches(el,sel){
  if(sel==='.hh-hand')return tokens(el).includes('hh-hand');
  if(sel==='.review-inbox-advanced')return tokens(el).includes('review-inbox-advanced');
  if(sel==='.review-inbox-advanced:not([hidden])')
    return tokens(el).includes('review-inbox-advanced')&&el.hidden!==true;
  throw new Error('unsupported selector: '+sel);
}
function descendants(el,out=[]){for(const child of el.children||[]){out.push(child);descendants(child,out);}return out;}
function makeElement(tag){
  return {
    tagName:String(tag),className:'',id:'',hidden:false,textContent:'',children:[],attrs:{},dataset:{},
    append(...nodes){for(const node of nodes)this.children.push(node);},
    appendChild(node){this.children.push(node);return node;},
    setAttribute(name,value){this.attrs[String(name)]=String(value);},
    getAttribute(name){return Object.prototype.hasOwnProperty.call(this.attrs,String(name))?this.attrs[String(name)]:null;},
    removeAttribute(name){delete this.attrs[String(name)];},
    addEventListener(){},
    querySelector(sel){for(const el of descendants(this))if(matches(el,sel))return el;return null;},
    querySelectorAll(sel){return descendants(this).filter(el=>matches(el,sel));},
  };
}

const ROW_HEIGHT=54;
const GAP=6;
const PANEL_HEIGHT=132;
const LIST_HEIGHT=600;
const folded=row=>row.attrs['data-review-inbox-folded']!=null;
const rowHeight=row=>row.baseHeight+((row.panel&&row.panel.hidden===false)?PANEL_HEIGHT:0);
function makeRow(id){
  const row=makeElement('div');
  row.className='hh-hand review-inbox-row';
  row.dataset.handId=String(id);
  row.baseHeight=ROW_HEIGHT;
  const panel=makeElement('div');
  panel.className='review-inbox-advanced';
  panel.hidden=true;
  row.appendChild(panel);
  row.panel=panel;
  return row;
}

function harness(){
  const hhHandsEl=makeElement('div');
  Object.defineProperty(hhHandsEl,'innerHTML',{
    get(){return '';},
    set(value){if(!value)this.children=[];},
  });
  Object.defineProperty(hhHandsEl,'scrollHeight',{get(){
    const rows=this.children.filter(row=>!(folded(row)&&foldCss));
    if(!rows.length)return 0;
    return rows.reduce((sum,row)=>sum+rowHeight(row),0)+(rows.length-1)*GAP;
  }});
  Object.defineProperty(hhHandsEl,'clientHeight',{get(){return LIST_HEIGHT;}});
  const hhListPager={hidden:true};
  const hhPageInfo={textContent:''};
  const hhPagePrev={disabled:false};
  const hhPageNext={disabled:false};
  const state={reviewInboxPage:0,reviewInboxPageSize:0,selectedHand:null};
  const paints=[];
  const sandbox={
    console,Array,Set,String,Number,Boolean,Math,JSON,
    state,hhHandsEl,hhListPager,hhPageInfo,hhPagePrev,hhPageNext,
    window:{matchMedia:()=>({matches:true})},
    getComputedStyle:()=>({rowGap:GAP+'px'}),
    paintReviewInboxRows(pageHands){
      hhHandsEl.innerHTML='';
      for(const hand of pageHands)hhHandsEl.appendChild(makeRow(hand.id));
      paints.push(pageHands.map(hand=>String(hand.id)));
    },
  };
  vm.createContext(sandbox);
  vm.runInContext([
    pageSizeConsts(source),
    'const REVIEW_INBOX_ADVANCED_OPEN='+servedConst(source,'REVIEW_INBOX_ADVANCED_OPEN')+';',
    ...[
      'reviewInboxAdvancedIsOpen','reviewInboxIsHeightBound','reviewInboxRowPitch','reviewInboxFitCount',
      'reviewInboxBoundedSize','reviewInboxPageSizeGuess','updateReviewInboxPager','reviewInboxPageWindow',
      'renderReviewInboxPage','toggleReviewInboxAdvanced','reviewInboxKeepAdvancedVisible',
    ].map(name=>extractFn(source,name)),
  ].join('\n'),sandbox);
  return {sandbox,state,hhHandsEl,paints};
}

function openScenario({total=32,index='last'}={}){
  const h=harness();
  const hands=Array.from({length:total},(_,i)=>({id:String(i+1)}));
  h.sandbox.renderReviewInboxPage(hands,new Map());
  const rows=h.hhHandsEl.children;
  const paintedIds=rows.map(row=>String(row.dataset.handId));
  const target=rows[index==='last'?rows.length-1:index];
  const openedHand=String(target.dataset.handId);
  const button={setAttribute(){},textContent:''};
  // Le vrai toggle servi ouvre le panneau *et* declenche le repli borne.
  h.sandbox.toggleReviewInboxAdvanced(openedHand,button,target.panel);
  const read=()=>({
    paintedIds,
    openedHand,
    panelHidden:target.panel.hidden,
    foldedIds:rows.filter(folded).map(row=>String(row.dataset.handId)),
    visibleIds:rows.filter(row=>!(folded(row)&&foldCss)).map(row=>String(row.dataset.handId)),
    scrollHeight:h.hhHandsEl.scrollHeight,
    clientHeight:h.hhHandsEl.clientHeight,
    overflow:h.hhHandsEl.scrollHeight>h.hhHandsEl.clientHeight+1,
    pageSize:h.state.reviewInboxPageSize,
    page:h.state.reviewInboxPage,
    paints:h.paints.length,
  });
  const opened=read();
  // Fermer le panneau leve le repli et restaure la page pleine.
  h.sandbox.toggleReviewInboxAdvanced(openedHand,button,target.panel);
  const closed=read();
  return {opened,closed};
}

const results={last:openScenario({index:'last'}),middle:openScenario({index:5}),mutation};
process.stdout.write(JSON.stringify(results));
"""


# --------------------------------------------------------------------------- #
# #424 F2 — smoke comportemental de la *rangee principale* : le peintre servi
# (`paintReviewInboxRows`) est execute contre un DOM minimal, avec le formateur
# servi charge, sur les deux combinaisons du correctif :
#   * `is_estimate=true` avec un `support_state` qui n'est PAS `SPARSE_ESTIMATED`
#     -> la rangee doit porter le prefixe ET le suffixe d'estimation ;
#   * `is_estimate=true` ET `too_close=true` simultanes -> la marque d'estimation
#     survit au verdict trop proche au lieu de disparaitre.
# Non-vacuite : deux mutations des octets servis (le drapeau `is_estimate` n'est
# plus lu, la marque ne survit plus au too-close) doivent casser le meme cas.
ROW_ESTIMATE_HARNESS_SCRIPT = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');

let source=fs.readFileSync('site/index.html','utf8');
const formatterSource=fs.readFileSync('site/analytics/review-confidence-formatter.js','utf8');

const MUTATIONS={
  // `rowEstimated` ne lit plus le drapeau independant `is_estimate` : le cas F2-a
  // (is_estimate=true, support_state=ROBUST) perd sa marque.
  'drop-is-estimate':['rowHybrid.is_estimate===true||',''],
  // la marque d'estimation ne survit plus au verdict trop proche : le cas F2-b
  // (too_close + is_estimate) perd son prefixe/suffixe.
  'drop-too-close-estimate':['if(rowEstimated)markEstimated();','void 0;'],
};
const mutation=process.env.ROW_ESTIMATE_MUTATION||'';
if(mutation){
  const [token,replacement]=MUTATIONS[mutation];
  assert.ok(typeof token==='string'&&token.length>0,'unknown mutation: '+mutation);
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
function servedConst(src,name){
  const match=src.match(new RegExp('^const '+name+'=(.*);$','m'));
  assert.ok(match,'missing served constant: '+name);
  return match[1];
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
  // Le repli borne ne vise que la coque desktop mesuree : ce DOM minimal (pas de
  // coque) le neutralise comme hors `matchMedia("(min-width:901px)")`.
  reviewInboxIsHeightBound:()=>false,
};
vm.createContext(sandbox);
vm.runInContext('var window=globalThis;',sandbox);
vm.runInContext(formatterSource,sandbox);
assert.ok(sandbox.window.PokerReviewConfidenceFormatter,'the mirrored formatter must expose its API');
vm.runInContext([
  'const REVIEW_INBOX_ADVANCED_OPEN='+servedConst(source,'REVIEW_INBOX_ADVANCED_OPEN')+';',
  'const REVIEW_INBOX_ADVANCED_ABSTENTION='+servedConst(source,'REVIEW_INBOX_ADVANCED_ABSTENTION')+';',
  ...[
    'reviewInboxAdvancedIsOpen','reviewInboxAdvancedFormatter','reviewInboxAdvancedProvenance',
    'reviewInboxAdvancedView','reviewInboxAdvancedModelLabel','reviewInboxAdvancedOodLabel',
    'reviewInboxAdvancedField','reviewInboxAdvancedPanel','paintReviewInboxRows',
  ].map(name=>extractFn(source,name)),
].join('\n'),sandbox);

const Formatter=sandbox.window.PokerReviewConfidenceFormatter;
const PREFIX=Formatter.ESTIMATE_PREFIX;
const SUFFIX=Formatter.ESTIMATE_SUFFIX;
const NOTICE=Formatter.TOO_CLOSE_NOTICE;
const bb=v=>sandbox.formatBB(v);

const hybridBase={
  schema:'poker-review-hybrid-result/v1',support_state:'ROBUST',confidence_level:'MEDIUM',
  is_estimate:false,ev_bb:-0.3,uncertainty_note:null,abstains:false,abstention_reason:null,too_close:false,
  provenance:{route:'HYBRID_BACKOFF',source:'model_b+model_a',model_id:'gbm-2026-09',model_hash:'sha256:abcd',ood_status:'IN_DISTRIBUTION',ood_reason:null},
};
const plainItem={hand_id:'30',status:'TO_REVIEW',status_label:'A revoir',
  coverage:{decisions_covered:1,decisions_total:2,decisions_comparable:1},
  analysis_state:{state:'ANALYSE_DISPONIBLE',reason_codes:[]},
  costliest_decision:{loss_bb:0.5},action_played:'call',action_recommended:'fold',total_loss_bb:-0.3,
  position:'IP',spot_family:'SRP',main_street:'Flop',user_review:{reviewed:false}};

function rowHtml(item){
  hhHandsEl.children=[];
  sandbox.paintReviewInboxRows([{id:Number(item.hand_id)}],new Map([[String(item.hand_id),item]]));
  assert.equal(hhHandsEl.children.length,1,'une main doit peindre une rangee');
  const html=String(hhHandsEl.children[0].children[0]?.innerHTML||'');
  assert.ok(html.includes('review-inbox-loss')&&html.includes('review-inbox-decision'),'la rangee porte ses cellules');
  return html;
}

const CASES=[
  // F2-a : `is_estimate=true` suffit, meme quand le support n'est pas
  // `SPARSE_ESTIMATED` (ici ROBUST, qui seul ne marque jamais).
  ['F2-a',()=>{
    const html=rowHtml({...plainItem,hybrid:{...hybridBase,support_state:'ROBUST',is_estimate:true,ev_bb:-0.3}});
    assert.ok(html.includes(PREFIX),'F2-a: le prefixe d estimation est peint depuis is_estimate');
    assert.ok(html.includes(SUFFIX),'F2-a: le suffixe d estimation est peint depuis is_estimate');
    assert.ok(html.includes('\u2192 reco fold'),'F2-a: la reco reste peinte, marquee comme estimation');
    assert.ok(html.includes(PREFIX+' '+bb(-0.3)+' '+SUFFIX),'F2-a: la perte EV affichee porte le marqueur');
    assert.ok(!html.includes(NOTICE),'F2-a: aucun verdict trop proche sans too_close');
  }],
  // F2-b : too_close + is_estimate simultanes -> la marque d'estimation survit.
  ['F2-b',()=>{
    const html=rowHtml({...plainItem,hand_id:'31',hybrid:{...hybridBase,support_state:'LOW_CONFIDENCE_TOO_CLOSE',is_estimate:true,too_close:true,ev_bb:-0.3}});
    assert.ok(html.includes(NOTICE),'F2-b: le verdict trop proche reste peint');
    assert.ok(html.includes(PREFIX+' '+NOTICE+' '+SUFFIX),'F2-b: la marque encadre le verdict trop proche');
    assert.ok(html.includes(PREFIX+' '+bb(-0.3)+' '+SUFFIX),'F2-b: la perte EV porte le marqueur d estimation');
    assert.ok(!html.includes('\u2192 reco'),'F2-b: aucune action unique mise en avant');
  }],
  // F2-c : non-regression — trop proche seul (is_estimate=false) reste net.
  ['F2-c',()=>{
    const html=rowHtml({...plainItem,hand_id:'32',hybrid:{...hybridBase,support_state:'LOW_CONFIDENCE_TOO_CLOSE',is_estimate:false,too_close:true,ev_bb:-0.2}});
    assert.ok(html.includes(NOTICE),'F2-c: le verdict trop proche reste peint');
    assert.ok(!html.includes(PREFIX)&&!html.includes(SUFFIX),'F2-c: aucun marqueur d estimation sans is_estimate');
  }],
  // F2-d : non-regression — STRONG_SUPPORT/ROBUST sans is_estimate inchange.
  ['F2-d',()=>{
    for(const state of ['STRONG_SUPPORT','ROBUST']){
      const html=rowHtml({...plainItem,hand_id:state==='ROBUST'?'34':'33',total_loss_bb:-0.25,
        hybrid:{...hybridBase,support_state:state,is_estimate:false,ev_bb:-0.25}});
      assert.ok(html.includes('\u2192 reco fold'),'F2-d: la reco concise reste inchangee pour '+state);
      assert.ok(html.includes(bb(-0.25)),'F2-d: la perte EV reste concise pour '+state);
      assert.ok(!html.includes(PREFIX)&&!html.includes(SUFFIX),'F2-d: aucun marqueur d estimation pour '+state);
    }
  }],
  // F2-e : non-regression — l'abstention (`abstains`) garde sa rangee dediee,
  // meme quand `is_estimate` est present.
  ['F2-e',()=>{
    const html=rowHtml({...plainItem,hand_id:'35',hybrid:{...hybridBase,support_state:'OOD_UNSUPPORTED',is_estimate:true,abstains:true,ev_bb:-0.4}});
    assert.ok(html.includes('Abstention'),'F2-e: l etat d abstention prime');
    assert.ok(!html.includes(PREFIX)&&!html.includes(SUFFIX),'F2-e: aucune marque d estimation sur une abstention');
  }],
];

for(const [id,fn] of CASES){
  try{
    fn();
  }catch(err){
    process.stdout.write(JSON.stringify({status:'FAIL',failed:id,message:String((err&&err.message)||err),mutation:mutation||null}));
    process.exit(0);
  }
}
process.stdout.write(JSON.stringify({status:'PASS',mutation:mutation||null}));
"""


def run_fold_harness(mutation: str | None = None) -> dict:
    """Drive the served open/fold path on a measured bounded DOM (node only)."""
    import json
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node is not None, "node runtime is required for the review advanced-view fold smoke"
    completed = subprocess.run(
        [node, "-e", FOLD_HARNESS_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "ADVANCED_FOLD_MUTATION": mutation or ""},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def check_fold_runtime() -> None:
    """#424 F1 — opening the advanced panel on a full page stays reachable."""
    results = run_fold_harness()
    last = results["last"]
    # La page est pleine : elle peint toute sa fenetre sans deborder (fermee).
    assert last["closed"]["panelHidden"] and not last["closed"]["overflow"], last
    assert len(last["closed"]["visibleIds"]) == len(last["closed"]["paintedIds"]), last
    assert not last["closed"]["foldedIds"], last
    # Ouvrir le panneau de la *derniere* ligne : la ligne et son panneau restent
    # atteignables (aucun debordement derriere la coque), la ligne ouverte n'est
    # jamais repliee et reste la derniere ligne visible.
    opened = last["opened"]
    assert opened["panelHidden"] is False, opened
    assert not opened["overflow"], opened
    assert opened["scrollHeight"] <= opened["clientHeight"] + 1, opened
    assert opened["openedHand"] in opened["visibleIds"], opened
    assert opened["visibleIds"][-1] == opened["openedHand"], opened
    assert opened["foldedIds"], "ouvrir le panneau doit replier au moins une ligne au-dessus"
    assert set(opened["foldedIds"]) <= set(opened["paintedIds"]) - {opened["openedHand"]}, opened
    # Le repli est purement presentationnel : la fenetre paginee et la taille de
    # page servies ne bougent pas.
    assert opened["pageSize"] == last["closed"]["pageSize"], last
    assert opened["page"] == 0, last

    # Une ligne du milieu de page : le repli garde la ligne ouverte, son panneau
    # et les lignes en dessous atteignables sans deborder.
    middle = results["middle"]["opened"]
    assert middle["panelHidden"] is False and not middle["overflow"], middle
    assert middle["openedHand"] in middle["visibleIds"], middle
    assert set(middle["visibleIds"]) - {middle["openedHand"]}, middle

    # Non-vacuite : sans l'appel de repli, sans son effet, ou sans la regle CSS,
    # la page deborde derriere `overflow:hidden`.
    for name in ("no-fold-call", "fold-keeps-rows-visible", "drop-fold-css"):
        mutated = run_fold_harness(name)["last"]
        assert mutated["opened"]["overflow"], (
            f"la mutation {name} doit faire deborder la page ouverte (repli non load-bearing)",
            mutated,
        )


def run_row_estimate_harness(mutation: str | None = None) -> dict:
    """Drive the served main-row painter on the F2 estimation combinations."""
    import json
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node is not None, "node runtime is required for the review row estimate smoke"
    completed = subprocess.run(
        [node, "-e", ROW_ESTIMATE_HARNESS_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "ROW_ESTIMATE_MUTATION": mutation or ""},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def check_row_estimate_runtime() -> None:
    """#424 F2 — the main row marks an estimate independently of too-close."""
    base = run_row_estimate_harness()
    assert base.get("status") == "PASS", base
    # Non-vacuite : la meme verification doit casser quand le drapeau
    # `is_estimate` n'est plus lu (F2-a) ou quand la marque ne survit plus au
    # verdict trop proche (F2-b).
    for name, expected in (("drop-is-estimate", "F2-a"), ("drop-too-close-estimate", "F2-b")):
        mutated = run_row_estimate_harness(name)
        assert mutated.get("status") == "FAIL" and mutated.get("failed") == expected, (
            f"la mutation {name} doit casser le cas {expected}",
            mutated,
        )


def main() -> None:
    # La parite octet-a-octet entre source d'edition et miroir servi : un miroir
    # desynchronise fait echouer le smoke avant meme la lecture de la coque.
    for source, runtime in PAIRS:
        source_text = (ROOT / source).read_text(encoding="utf-8")
        runtime_text = (ROOT / runtime).read_text(encoding="utf-8")
        assert runtime_text == source_text, f"mirror drift: {source} != {runtime}"

    index_text = (ROOT / "site/index.html").read_text(encoding="utf-8")
    check(index_text)

    # Non-vacuite : chaque mutation doit casser la meme verification.
    for name, (token, replacement) in MUTATIONS.items():
        assert index_text.count(token) == 1, f"mutation token must be unique: {name}"
        mutated = index_text.replace(token, replacement)
        try:
            check(mutated)
        except AssertionError:
            continue
        raise AssertionError(f"the {name} mutation must fail the smoke harness")

    # #424 F1 — la verification comportementale de l'ouverture du panneau sur une
    # page pleine (le harnais node execute les fonctions servies).
    check_fold_runtime()

    # #424 F2 — la verification comportementale de la rangee principale : la
    # marque d'estimation suit `is_estimate` et survit au verdict trop proche.
    check_row_estimate_runtime()

    print("review advanced-view smoke checks: OK")


if __name__ == "__main__":
    sys.exit(main())
