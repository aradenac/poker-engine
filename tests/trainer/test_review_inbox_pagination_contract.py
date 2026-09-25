#!/usr/bin/env python3
"""#395 T5 — the Review inbox page is measured, bounded and selection-safe.

What is checked, and from what
------------------------------
The inbox is the only list of the desktop shell that keeps every hand
reachable without a scroll zone of its own: it is painted one bounded page at a
time. This module pins the *measured* page size contract on the served bytes:

* static contract on ``site/index.html`` — the page-size window is declared as
  ``REVIEW_INBOX_PAGE_SIZE_MIN=10`` / ``REVIEW_INBOX_PAGE_SIZE_MAX=15`` (the
  ``_DEFAULT`` fallback mirrors the minimum), the pager keeps its
  ``Précédent`` / ``Suivant`` / ``Page x / y · mains a–b sur N`` shape, the
  desktop rule of ``.hh-list`` stays ``overflow:hidden`` (no internal list
  scroll) and every filter/sort input resets ``state.reviewInboxPage`` to 0 —
  so a filter change always lands on page 1;
* runtime invariance (``node``) — the real
  ``renderReviewInboxPage`` / ``reviewInboxPageSizeGuess`` sources are executed
  against a minimal measured DOM where ``scrollHeight`` is derived from the
  painted rows and ``clientHeight`` from the constrained shell *including* the
  pager bar. The painted page must:
  - hold between 10 and 15 rows when the measured height allows it,
  - never exceed 15 rows, whatever the viewport,
  - shrink below the 10-row target rather than clip a row behind
    ``overflow:hidden``,
  - leave ``scrollHeight <= clientHeight`` once the pager is visible (the
    pager is part of the constrained height: it is shown *before* the
    measurement, so its own appearance cannot hide the last row),
  - clamp ``state.reviewInboxPage`` to ``[0, pages-1]`` and keep
    ``state.selectedHand`` untouched.

Non-vacuity is replayed, not asserted: two in-memory mutations of the served
source are run through the same harness — raising ``REVIEW_INBOX_PAGE_SIZE_MAX``
must let the page exceed 15 rows, and removing the pager-first assignment must
produce the hidden overflow the real source avoids. A guard that still passed
with those declarations weakened would be vacuous.

``#395 T5b`` adds the measurement the reference viewport was missing: the page
size the served shell *really paints* at ``1500x1000`` with the 32-hand fixture
of the large-list smoke. The vertical geometry of the shell (every box the inbox
consumes around ``.hh-list``, the painted height of a row and the pager bar) is
derived from the served declarations, then handed to the **same** harness so the
real ``renderReviewInboxPage`` paints the real fixture ids in it. The result is
pinned (10 rows for the conservative 1.5 line factor, 11 for the typographic 1.2
one) and every lever of the reconciliation is replayed backwards: without it the
conservative model no longer holds ``REVIEW_INBOX_PAGE_SIZE_MIN``. Replayed on
the bytes from before the task, the same model returns the 8 rows a browser
measured at that viewport — the calibration anchor.

The module is static + ``node`` only: no browser, no server, no network, no
write. ``site/index.html`` is never modified (the mutations only exist as
strings in memory and the delivered bytes are re-read at the end).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "site" / "index.html"
INDEX = INDEX_PATH.read_text(encoding="utf-8")


def check_static_contract() -> None:
    assert "const REVIEW_INBOX_PAGE_SIZE_MIN=10;" in INDEX
    assert "const REVIEW_INBOX_PAGE_SIZE_MAX=15;" in INDEX
    assert "const REVIEW_INBOX_PAGE_SIZE_DEFAULT=REVIEW_INBOX_PAGE_SIZE_MIN;" in INDEX
    # The measured target is documented where it is implemented.
    assert "#395 T5" in INDEX
    assert "10 à 15 mains par page" in INDEX

    # The bounded pager keeps its operational shape: previous / next plus the
    # page and hand-window caption.
    assert 'id="hhListPager"' in INDEX
    assert 'id="hhPagePrev"' in INDEX and 'id="hhPageNext"' in INDEX
    assert 'id="hhPageInfo"' in INDEX
    assert "`Page ${page+1} / ${pages} · mains ${first+1}–${last} sur ${total}`" in INDEX
    assert 'hhPagePrev?.addEventListener("click"' in INDEX
    assert 'hhPageNext?.addEventListener("click"' in INDEX

    # No internal list scroll on the desktop shell: the page size is the only
    # bound, the list itself stays clipped (and is never a scroll zone).
    assert ".hh-list{flex:1 1 auto;min-height:0;max-height:none;overflow:hidden}" in INDEX
    for rule in re.findall(r"\.hh-list\{([^}]*)\}", INDEX):
        assert "overflow:auto" not in rule and "overflow:scroll" not in rule, rule
    assert "max-height:310px;overflow:auto" not in INDEX

    # A selected hand keeps its highlight across a bounded repaint, and no
    # repaint clears the selection.
    assert 'row.className="hh-hand review-inbox-row"+(state.selectedHand?.id===h.id?" selected":"");' in INDEX

    # Filter / sort changes restart on page 1.
    for reset in (
        "state.hhSort=normalizeReviewInboxSortCode(hhSortSelect.value);\n  state.reviewInboxPage=0;",
        "state.hhKnownOnly=hhKnownFilter.checked;\n  state.reviewInboxPage=0;",
        "state.reviewInboxFilters.result=reviewResultFilter.value;\n  state.reviewInboxPage=0;",
        "state.reviewInboxFilters[key]=el.value;state.reviewInboxPage=0;",
    ):
        assert reset in INDEX, reset
    leak_cta = INDEX[INDEX.index("function openReviewDashboardLeak"):INDEX.index("function openReviewDashboardTraining")]
    assert "state.reviewInboxPage=0;" in leak_cta

    # The page-size window is re-derived after a shell resize, without any
    # compute scheduling (the #394 T3 contract forbids scroll/visibility
    # triggers, not layout re-measurement).
    assert "function relayoutReviewInbox(){" in INDEX
    assert 'window.addEventListener("resize"' in INDEX
    relayout = INDEX[INDEX.index("function relayoutReviewInbox(){"):INDEX.index('window.addEventListener("resize"')]
    assert "renderReviewInboxPage(hands,byId);" in relayout
    assert "scheduleBackgroundReviewScoring" not in relayout
    assert "scheduleAutoCalculate" not in relayout


# The measured DOM harness, shared by the two node measurements below: the
# synthetic page-size cases (`PAGINATION_CASES`) and the served-shell
# measurement at 1500x1000 (`SHELL_BUDGET_CASES`). It is one instrument, never
# two: a page-size rule that the shell measurement accepts must be the same one
# the synthetic cases exercise.
PAGINATION_HARNESS_SCRIPT = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');

const MUTATIONS={
  cap:['const REVIEW_INBOX_PAGE_SIZE_MAX=15;','const REVIEW_INBOX_PAGE_SIZE_MAX=25;'],
  'pager-first':[
    '    if(hhListPager)hhListPager.hidden=pageWindow.pages<=1;\n'
      +'    paintReviewInboxRows(hands.slice(pageWindow.start,pageWindow.end),byId);',
    '    paintReviewInboxRows(hands.slice(pageWindow.start,pageWindow.end),byId);',
  ],
};
let source=fs.readFileSync('site/index.html','utf8');
const mutation=process.env.PAGINATION_MUTATION||'';
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

function pageSizeConsts(src){
  const re=/^const (REVIEW_INBOX_PAGE_SIZE_[A-Z]+|REVIEW_INBOX_ROW_PITCH_[A-Z]+|REVIEW_INBOX_PAGE_FIT_ATTEMPTS)=[^\n]*$/gm;
  const consts=src.match(re)||[];
  assert.ok(consts.length>=6,'page-size constants must be declared: '+consts.length);
  return consts.join('\n');
}

// A measured DOM: scrollHeight is derived from the painted rows, clientHeight
// from the constrained shell minus the pager bar whenever the pager is shown.
function harness({desktop=true,rowHeight=54,gap=6,baseHeight=900,pagerHeight=44,tallFrom=0,tallRowHeight=0}={}){
  const pagerState={visible:false};
  const paints=[];
  const hhHandsEl={
    children:[],
    appendChild(node){this.children.push(node);},
    querySelector(){return this.children.find(c=>String(c.className||'').includes('hh-hand'))||null;},
    set innerHTML(value){this.children=[];},
    get innerHTML(){return '';},
  };
  Object.defineProperty(hhHandsEl,'scrollHeight',{get(){
    const n=this.children.length;
    return n?this.children.reduce((sum,child)=>sum+child.height,0)+(n-1)*gap:0;
  }});
  Object.defineProperty(hhHandsEl,'clientHeight',{get(){
    return baseHeight-(pagerState.visible?pagerHeight:0);
  }});
  const hhListPager={};
  Object.defineProperty(hhListPager,'hidden',{
    get(){return !pagerState.visible;},
    set(value){pagerState.visible=!value;},
  });
  const hhPageInfo={textContent:''};
  const hhPagePrev={disabled:false};
  const hhPageNext={disabled:false};
  const state={reviewInboxPage:0,reviewInboxPageSize:10,selectedHand:null};
  const sandbox={
    console,state,hhHandsEl,hhListPager,hhPageInfo,hhPagePrev,hhPageNext,
    window:{matchMedia:()=>({matches:!!desktop})},
    getComputedStyle:()=>({rowGap:gap+'px'}),
    paintReviewInboxRows(pageHands){
      hhHandsEl.innerHTML='';
      pageHands.forEach((hand,index)=>{
        const height=tallFrom&&index+1>=tallFrom?tallRowHeight:rowHeight;
        hhHandsEl.appendChild({
          className:'hh-hand review-inbox-row',handId:String(hand.id),
          height,getBoundingClientRect:()=>({height}),
        });
      });
      paints.push({ids:pageHands.map(hand=>String(hand.id)),pagerVisible:pagerState.visible});
    },
  };
  vm.createContext(sandbox);
  vm.runInContext([
    pageSizeConsts(source),
    extractFn(source,'reviewInboxIsHeightBound'),
    extractFn(source,'reviewInboxRowPitch'),
    extractFn(source,'reviewInboxFitCount'),
    extractFn(source,'reviewInboxBoundedSize'),
    extractFn(source,'reviewInboxPageSizeGuess'),
    extractFn(source,'updateReviewInboxPager'),
    extractFn(source,'reviewInboxPageWindow'),
    extractFn(source,'renderReviewInboxPage'),
  ].join('\n'),sandbox);
  return {sandbox,state,hhHandsEl,hhListPager,hhPageInfo,hhPagePrev,hhPageNext,pagerState,paints};
}

function run({pitch=60,total=100,page=0,selected=null,ids=null,...options}={}){
  const h=harness({rowHeight:pitch-6,gap:6,...options});
  h.state.reviewInboxPage=page;
  if(selected!==null)h.state.selectedHand=selected;
  const hands=(ids&&ids.length?ids:Array.from({length:total},(_,index)=>String(index+1)))
    .map(id=>({id:String(id)}));
  h.sandbox.renderReviewInboxPage(hands,new Map());
  const last=h.paints[h.paints.length-1];
  return {
    painted:last.ids,
    paintedCount:last.ids.length,
    paints:h.paints.length,
    pageCount:Math.max(1,Math.ceil(hands.length/Math.max(1,h.state.reviewInboxPageSize))),
    pagerVisible:h.pagerState.visible,
    everyPaintMeasuredWithPager:h.paints.every(paint=>paint.pagerVisible===h.pagerState.visible||!h.pagerState.visible),
    size:h.state.reviewInboxPageSize,
    page:h.state.reviewInboxPage,
    info:h.hhPageInfo.textContent,
    prevDisabled:h.hhPagePrev.disabled,
    nextDisabled:h.hhPageNext.disabled,
    scrollHeight:h.hhHandsEl.scrollHeight,
    clientHeight:h.hhHandsEl.clientHeight,
    overflow:h.hhHandsEl.scrollHeight>h.hhHandsEl.clientHeight,
    selectedHand:h.state.selectedHand,
  };
}
"""

# The synthetic page-size cases of #395 T5 (unchanged by T5b).
PAGINATION_CASES_SCRIPT = r"""
const results={
  // 1200px of measured list: the 15-row cap binds (19 rows would fit).
  capped:run({baseHeight:1200,total:100}),
  // 800px of measured list: 12 rows fit, inside the 10–15 target.
  measured:run({baseHeight:800,total:100}),
  // 500px of measured list: only 7 rows fit — the page shrinks below the
  // 10-row target instead of clipping rows behind overflow:hidden.
  belowTarget:run({baseHeight:500,total:100}),
  // A 6-hand inbox is a single bounded page: no pager, no scroll.
  singlePage:run({baseHeight:900,total:6}),
  // A short shell (600px) where the pager bar is what decides the fit: the
  // pager must be shown before the measurement, or the last row is hidden.
  pagerFirst:run({baseHeight:600,total:100}),
  // A page whose grown range contains a taller (wrapped) row: the growth is
  // measured again and reverted instead of leaving an overflow behind.
  wrappedRow:run({baseHeight:700,rowHeight:50,gap:6,tallFrom:11,tallRowHeight:150,total:100}),
  // Page index is clamped, never trusted blindly.
  clampHigh:run({baseHeight:1200,total:100,page:999}),
  clampLow:run({baseHeight:1200,total:100,page:-5}),
  // Selection survives a repaint; the selected hand keeps its row when visible.
  selection:run({baseHeight:800,total:100,page:0,selected:{id:'5'}}),
  // Below 901px the shell is not height-bound: the document flow renders all.
  mobile:run({desktop:false,baseHeight:400,total:100}),
};
results.mutation=mutation;
process.stdout.write(JSON.stringify(results));
"""

PAGINATION_RUNTIME_SCRIPT = PAGINATION_HARNESS_SCRIPT + PAGINATION_CASES_SCRIPT

# #395 T5b — the served-shell measurement at 1500x1000. The geometry of the
# constrained shell (everything the review inbox consumes around `.hh-list`,
# the row box and the pager bar) is derived from the served declarations by
# `shell_budget()` and handed to this runner as `INBOX_SHELL_BUDGET`; the page
# that is measured is then the one the *real* `renderReviewInboxPage` paints on
# the *real* 32-hand fixture ids, against that measured DOM.
SHELL_BUDGET_CASES_SCRIPT = r"""
const budget=JSON.parse(process.env.INBOX_SHELL_BUDGET||'null');
const results={};
if(!budget){
  results.measured=null;
}else{
  results.measured=run({
    baseHeight:budget.baseHeight,
    pagerHeight:budget.pagerHeight,
    rowHeight:budget.rowHeight,
    gap:budget.gap,
    total:budget.ids.length,
    ids:budget.ids,
  });
  results.budget=budget;
}
results.mutation=null;
process.stdout.write(JSON.stringify(results));
"""

SHELL_BUDGET_RUNTIME_SCRIPT = PAGINATION_HARNESS_SCRIPT + SHELL_BUDGET_CASES_SCRIPT


def run_runtime(mutation: str | None = None) -> dict:
    node = shutil.which("node")
    assert node is not None, "node runtime is required for the inbox pagination contract"
    completed = subprocess.run(
        [node, "-e", PAGINATION_RUNTIME_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PAGINATION_MUTATION": mutation or ""},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def check_runtime_contract() -> None:
    results = run_runtime()

    capped = results["capped"]
    assert capped["paintedCount"] == 15, capped
    assert capped["size"] == 15, capped
    assert capped["painted"][0] == "1" and capped["painted"][-1] == "15", capped
    assert capped["pagerVisible"] and not capped["overflow"], capped
    assert capped["info"] == "Page 1 / 7 · mains 1–15 sur 100", capped
    assert capped["prevDisabled"] and not capped["nextDisabled"], capped

    measured = results["measured"]
    assert 10 <= measured["paintedCount"] <= 15, measured
    assert measured["paintedCount"] == 12, measured
    assert not measured["overflow"], measured

    below = results["belowTarget"]
    assert below["paintedCount"] == 7, below
    assert below["paintedCount"] < 10, "a page may only fall below the target when the height cannot hold it"
    assert not below["overflow"], below

    single = results["singlePage"]
    assert single["paintedCount"] == 6 and single["painted"] == [str(i) for i in range(1, 7)], single
    assert not single["pagerVisible"] and not single["overflow"] and single["size"] == 6, single

    pager_first = results["pagerFirst"]
    assert not pager_first["overflow"], pager_first
    assert pager_first["clientHeight"] < 600, "the pager bar is part of the constrained height"
    assert pager_first["everyPaintMeasuredWithPager"], pager_first
    assert pager_first["scrollHeight"] <= pager_first["clientHeight"], pager_first

    wrapped = results["wrappedRow"]
    assert wrapped["paintedCount"] == 10 and wrapped["size"] == 10, wrapped
    assert not wrapped["overflow"], wrapped
    assert wrapped["paints"] >= 3, "the grown page must be measured and reverted: " + str(wrapped)

    high = results["clampHigh"]
    assert high["page"] == 6 and high["painted"][-1] == "100" and high["painted"][0] == "91", high
    assert high["info"] == "Page 7 / 7 · mains 91–100 sur 100", high
    assert not high["prevDisabled"] and high["nextDisabled"], high
    low = results["clampLow"]
    assert low["page"] == 0 and low["prevDisabled"] and not low["nextDisabled"], low

    selection = results["selection"]
    assert "5" in selection["painted"], selection
    assert selection["selectedHand"] == {"id": "5"}, "a bounded repaint must not clear the selection"

    mobile = results["mobile"]
    assert mobile["paintedCount"] == 100 and not mobile["pagerVisible"], mobile

    # Non-vacuity: the two load-bearing declarations are replayed as strings.
    raised = run_runtime("cap")
    assert raised["capped"]["paintedCount"] > 15, (
        "raising the page-size cap must let the measured page exceed 15 rows, else the cap is not proven",
        raised["capped"],
    )
    unhidden = run_runtime("pager-first")
    assert unhidden["pagerFirst"]["overflow"], (
        "without the pager-first measurement, the pager appearance hides the last row: the guard is load-bearing",
        unhidden["pagerFirst"],
    )

    assert INDEX_PATH.read_text(encoding="utf-8") == INDEX, "the replay must never write site/index.html"


# --------------------------------------------------------------------------- #
# #395 T5b — la taille de page peinte à 1500x1000, mesurée sur la coque servie.
# --------------------------------------------------------------------------- #
#
# Le smoke navigateur du job gelé `browser-smoke` consigne déjà `page_size` par
# tri (`tests/trainer/smoke_review_inbox_large_list.py`), mais il ne tourne que
# là-bas. Cette section apporte la mesure **reproductible depuis le dépôt**,
# sans navigateur : la géométrie verticale de la coque servie (tout ce que
# l'inbox consomme au-dessus et au-dessous de `.hh-list`, la boîte d'une rangée
# et la barre de pagination) est **dérivée des déclarations servies** — chaque
# nombre est lu dans `site/index.html` / `site/trainer.css`, jamais choisi — puis
# donnée au **vrai** `renderReviewInboxPage` (même harnais node que T5) sur les
# **vrais identifiants de la fixture 32 mains**. La taille de page peinte est
# ensuite épinglée, et chaque levier de la réconciliation est rejoué en sens
# inverse : si un seul d'entre eux disparaît, la page retombe sous la cible.
#
# Deux modèles de hauteur de ligne sont calculés, tous deux déclarés :
#   * `TYPOGRAPHIC` (1.2) — la hauteur de ligne « normale » d'un texte sans
#     `line-height` déclaré. Ce modèle reproduit exactement la valeur mesurée
#     dans un vrai navigateur au 1500x1000 **avant** cette réconciliation (8
#     lignes, la mesure du constat de revue) : c'est l'ancrage de calibration
#     (`SHELL_PRE_CHANGE_MEASURED_PAGE_SIZE`).
#   * `MAJORANT` (1.5) — la borne haute des contrats frères
#     (`test_spotlab_range_fit_contract.DEFAULT_LINE_FACTOR`) ; c'est le modèle
#     qui **épingle la borne basse**, parce qu'il majore toute ligne réelle et
#     sous-estime donc la page réellement peinte.
#
# L'autorité mesurée reste le job gelé `browser-smoke` : cette section ne le
# remplace pas, elle rend son chiffre vérifiable depuis le dépôt.
SHELL_VIEWPORT = (1500, 1000)
SHELL_TYPOGRAPHIC_LINE_FACTOR = 1.2
SHELL_MAJORANT_LINE_FACTOR = 1.5  # == test_spotlab_range_fit_contract.DEFAULT_LINE_FACTOR
# Majorant d'avance moyenne d'un glyphe (le même que les contrats frères) : il
# évalue le nombre de lignes d'un texte déclaré dans la largeur qu'il reçoit.
SHELL_CHAR_ADVANCE_EM = 0.62  # == test_spotlab_range_fit_contract.CHAR_ADVANCE_EM
SHELL_ROOT_FONT_PX = 16.0
# `small` ne porte aucune règle dans la cellule « perte EV » : il hérite du
# parent (10px) et du `font-size:smaller` de la feuille de style du navigateur.
SHELL_SMALL_FONT_RATIO = 0.8333
# Valeurs épinglées (voir `check_shell_budget_measurement`).
SHELL_TYPOGRAPHIC_PAGE_SIZE = 11
SHELL_MAJORANT_PAGE_SIZE = 10
SHELL_PRE_CHANGE_MEASURED_PAGE_SIZE = 8


def _shell_derivation():
    """Le lecteur de constantes CSS des contrats frères (réutilisé, pas réécrit)."""
    if str(ROOT / "tests" / "trainer") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests" / "trainer"))
    import test_desktop_panels_fit_contract as derivation

    return derivation


def _shell_sheet(index_text: str):
    derivation = _shell_derivation()
    document = (
        derivation.STATEMENT_AT_RULE.sub("", index_text)
        + "\n"
        + derivation.STATEMENT_AT_RULE.sub("", derivation.TRAINER_CSS_TEXT)
    )
    return derivation.Layout(document=document, markup=index_text)


def _grid_tracks(value: str) -> list[str]:
    """Les pistes de premier niveau d'un `grid-template-columns` déclaré."""
    tracks: list[str] = []
    depth = 0
    current = ""
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char.isspace() and depth == 0:
            if current:
                tracks.append(current)
                current = ""
            continue
        current += char
    if current:
        tracks.append(current)
    return tracks


def _split_track(track: str) -> tuple[str, float | None]:
    """`(minimum déclaré, facteur fr)` d'une piste de grille."""
    match = re.fullmatch(r"minmax\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", track)
    if match:
        minimum, upper = match.group(1).strip(), match.group(2).strip()
        return minimum, (float(upper[:-2]) if upper.endswith("fr") else None)
    if track.endswith("fr"):
        return "0", float(track[:-2])
    return track, None


def _track_widths(tracks: list[str], available: float, gap: float, px) -> list[float]:
    """La largeur réellement peinte de chaque piste, `fr` distribués."""
    assert available > 0, available
    split = [_split_track(track) for track in tracks]
    minimums = [px(minimum) for minimum, _ in split]
    ratios = [ratio for _, ratio in split if ratio is not None]
    assert ratios, f"aucune piste flexible déclarée : {tracks!r}"
    free = available - gap * (len(tracks) - 1) - sum(minimums)
    assert free > 0, (tracks, available)
    share = free / sum(ratios)
    widths = [
        minimum + (share * (ratio or 0.0))
        for minimum, (_, ratio) in zip(minimums, split)
    ]
    for track, minimum, width in zip(tracks, minimums, widths):
        assert width >= minimum - 0.01, (track, width, minimum)
    return widths


def shell_budget(index_text: str, factor: float) -> dict:
    """La géométrie verticale déclarée de l'inbox servie, à 1500x1000.

    Chaque pièce est lue dans les octets servis ; `factor` ne porte que sur les
    blocs de texte **sans `line-height` déclaré** (un `line-height` déclaré est
    exact et n'est jamais majoré). Le retour porte à la fois les pièces (pour la
    documentation et les contrôles de mutation) et le résultat :
    `available` (hauteur réellement laissée à `.hh-list`), `row` (hauteur peinte
    d'une rangée), `gap`, `pitch` (le pas servi, borné par
    `REVIEW_INBOX_ROW_PITCH_MIN`) et `pageSize` (lignes que `fit` autorise).
    """
    derivation = _shell_derivation()
    layout = _shell_sheet(index_text)
    sheet = layout.sheet
    width, height = SHELL_VIEWPORT

    def declared(selectors, prop, default=None):
        value = sheet.declared(selectors, prop, width, height)
        return default if value is None else value

    def length(selectors, prop, default=None):
        return sheet.length(selectors, prop, width, height, default)

    def box(selectors, kind, edge):
        return sheet.box_length(selectors, kind, edge, width, height)

    def line(selectors, font_size=None):
        if font_size is None:
            font_size = length(selectors, "font-size", f"{SHELL_ROOT_FONT_PX}px")
        raw = declared(selectors, "line-height")
        if raw is not None and re.fullmatch(r"\d*\.?\d+", raw):
            return font_size * float(raw)
        return font_size * factor

    def text_lines(text: str, font_size: float, available: float) -> int:
        assert available > 0, (text, available)
        return max(1, math.ceil(len(text) * font_size * SHELL_CHAR_ADVANCE_EM / available))

    pieces: dict[str, float] = {}
    # Coque et bandeau de déploiement (`body::before`, une ligne déclarée plus
    # l'absorption des deux lignes du texte réécrit au build).
    pieces["shell"] = box(("[data-view-shell]",), "padding", "top") + box(
        ("[data-view-shell]",), "padding", "bottom"
    )
    pieces["banner"] = derivation.banner_outer(
        layout, trainer_open=False, width=width, height=height
    )
    # En-tête de vue : le bouton retour et le bloc titre/sous-titre.
    back = (
        2
        + box((".app-view-back",), "padding", "top")
        + box((".app-view-back",), "padding", "bottom")
        + line((".app-view-back", "button"))
    )
    title_block = (
        line(("h1",))
        + box((".app-view-head .sub", ".sub"), "margin", "top")
        + line((".app-view-head .sub", ".sub"))
    )
    pieces["head"] = max(back, title_block) + box((".app-view-head",), "margin", "bottom")
    # Barre d'onglets de sous-vue (une seule rangée de trois onglets).
    tab = (
        box((".app-subview-tab",), "padding", "top")
        + box((".app-subview-tab",), "padding", "bottom")
        + line((".app-subview-tab",))
    )
    pieces["subview_tabs"] = (
        2
        + box((".app-subviews",), "padding", "top")
        + box((".app-subviews",), "padding", "bottom")
        + tab
        + box(("#mainPage .app-view-body>.app-subviews", ".app-subviews"), "margin", "bottom")
    )
    # Le panneau inbox lui-même : marge, bordure, deux paddings verticaux.
    panel_chain = ("#handSelectionSection", ".hh-selection-section", ".panel")
    pieces["pane_inset"] = (
        box(panel_chain, "margin", "top")
        + 2
        + box(panel_chain, "padding", "top")
        + box(panel_chain, "padding", "bottom")
    )
    pieces["pane_title"] = line((".hh-selection-title",)) + box(
        (".hh-selection-title",), "margin", "bottom"
    )
    # Rangée de contrôles de premier niveau : empilée (libellé au-dessus) ou
    # compactée (libellé à côté, `display:grid`).
    select_box = (
        2
        + box(("select", "button"), "padding", "top")
        + box(("select", "button"), "padding", "bottom")
        + line(("select", "button"))
    )
    label_box = line((".review-inbox-primary-tools label", "label")) + box(
        (".review-inbox-primary-tools label", "label"), "margin", "bottom"
    )
    tools_content = (
        max(label_box, select_box)
        if declared((".review-inbox-primary-tools .field", ".field"), "display") == "grid"
        else label_box + select_box
    )
    pieces["primary_tools"] = (
        box((".review-inbox-primary-tools",), "margin", "top")
        + tools_content
        + box((".review-inbox-primary-tools",), "margin", "bottom")
    )
    summary = (
        box((".review-inbox-filters>summary",), "padding", "top")
        + box((".review-inbox-filters>summary",), "padding", "bottom")
        + line((".review-inbox-filters>summary",))
    )
    pieces["filters"] = (
        box((".review-inbox-filters",), "margin", "top")
        + 2
        + summary
        + box((".review-inbox-filters",), "margin", "bottom")
    )
    pieces["notice"] = (
        box((".review-inbox-notice",), "margin", "top")
        + max(length((".review-inbox-notice",), "min-height", "0px"), line((".review-inbox-notice",)))
        + box((".review-inbox-notice",), "margin", "bottom")
    )
    pieces["list_margin"] = box((".hh-list",), "margin", "top")
    pieces["pager"] = (
        box((".app-list-pager",), "margin", "top")
        + 2
        + box((".app-list-pager button", "button"), "padding", "top")
        + box((".app-list-pager button", "button"), "padding", "bottom")
        + line((".app-list-pager button", "button"))
    )

    chrome = sum(pieces.values())
    available = height - chrome

    # Largeur réellement peinte de la colonne « perte EV » : la rangée est une
    # grille `[open, statut]` et `open` en est elle-même une. Les `fr` sont
    # distribués sur la largeur que la coque laisse à la liste, donc chaque
    # texte déclaré peut être confronté à la place qu'il reçoit vraiment.
    list_width = (
        width
        - box(("[data-view-shell]",), "padding", "left")
        - box(("[data-view-shell]",), "padding", "right")
        - box((".panel",), "padding", "left")
        - box((".panel",), "padding", "right")
        - box((".hh-list",), "padding", "right")
    )
    row_tracks = _grid_tracks(declared((".review-inbox-row",), "grid-template-columns"))
    row_widths = _track_widths(row_tracks, list_width, length((".review-inbox-row",), "gap", "0px"), sheet.px)
    open_tracks = _grid_tracks(declared((".review-inbox-open",), "grid-template-columns"))
    open_widths = _track_widths(open_tracks, row_widths[0], length((".review-inbox-open",), "gap", "0px"), sheet.px)
    loss_column = open_widths[1]

    # Hauteur d'une rangée : la plus haute des quatre cellules déclarées. Les
    # textes de la cellule « perte EV » sont ceux du serveur (`formatBB`) ; leur
    # nombre de lignes est mesuré sur la largeur réellement reçue, donc une
    # colonne trop étroite se paie en hauteur au lieu de passer inaperçue.
    hand_result = line((".review-inbox-hand-result strong", "strong")) + box(
        (".review-inbox-hand-result small", "small"), "margin", "top"
    ) + line((".review-inbox-hand-result small", "small"))
    loss_font = length((".review-inbox-loss",), "font-size", f"{SHELL_ROOT_FONT_PX}px")
    loss_amount_font = length((".review-inbox-loss b", "b"), "font-size", f"{SHELL_ROOT_FONT_PX}px")
    loss_small_font = loss_font * SHELL_SMALL_FONT_RATIO
    # Les trois textes que `paintReviewInboxRows` écrit dans la cellule, à leur
    # taille déclarée : « Perte EV », l'occurrence de `formatBB` et la décision
    # maximale, dans l'ordre du gabarit servi.
    loss_extent = (
        len("Perte EV") * loss_font * SHELL_CHAR_ADVANCE_EM
        + len("3,00 BB") * loss_amount_font * SHELL_CHAR_ADVANCE_EM
        + box((".review-inbox-loss b", "b"), "margin", "left")
        + len("Décision max 1,00 BB") * loss_small_font * SHELL_CHAR_ADVANCE_EM
    )
    loss_line_bottom = loss_small_font * factor
    if declared((".review-inbox-loss b", "b"), "display") == "block":
        # Le montant porte sa propre ligne (déclaration d'avant la task) : les
        # trois textes s'empilent, seule la décision maximale peut se replier.
        loss_lines = 2 + text_lines("Décision max 1,00 BB", loss_small_font, loss_column)
        loss_cell = (
            loss_font * factor
            + box((".review-inbox-loss b", "b"), "margin", "top")
            + loss_amount_font * factor
            + loss_line_bottom * (loss_lines - 2)
        )
    else:
        loss_lines = max(1, math.ceil(loss_extent / loss_column))
        loss_cell = max(loss_font, loss_amount_font) * factor + loss_line_bottom * (loss_lines - 1)
    spot = (
        line((".review-inbox-spot strong", "strong"))
        + box((".review-inbox-spot small", "small"), "margin", "top")
        + line((".review-inbox-spot small", "small"))
    )
    row_content = max(hand_result, loss_cell, spot)
    row = (
        row_content
        + box((".hh-hand",), "padding", "top")
        + box((".hh-hand",), "padding", "bottom")
        + 2
    )
    gap = length((".hh-list",), "gap", "0px")
    pitch_min = int(re.search(r"const REVIEW_INBOX_ROW_PITCH_MIN=(\d+);", index_text).group(1))
    page_min = int(re.search(r"const REVIEW_INBOX_PAGE_SIZE_MIN=(\d+);", index_text).group(1))
    page_max = int(re.search(r"const REVIEW_INBOX_PAGE_SIZE_MAX=(\d+);", index_text).group(1))
    pitch = max(float(pitch_min), row + gap)
    # `reviewInboxFitCount` puis la boucle de `renderReviewInboxPage` : la page
    # part de la cible basse (10), ne se réduit que si elle **déborde vraiment**,
    # et ne dépasse jamais le plafond haut (15).
    fit = max(1, math.floor((available + 2) / pitch))
    guess = max(page_min, min(page_max, fit))
    paints_guess = guess * row + (guess - 1) * gap <= available + 1
    page_size = max(1, guess if paints_guess else fit)
    return {
        "factor": factor,
        "pieces": pieces,
        "chrome": chrome,
        "available": available,
        "row": row,
        "rowContent": row_content,
        "gap": gap,
        "pitch": pitch,
        "pitchMin": pitch_min,
        "fit": fit,
        "pageMin": page_min,
        "pageMax": page_max,
        "pageSize": page_size,
        "pageSizeGuess": guess,
        "lossColumn": loss_column,
        "lossLines": loss_lines,
    }


def fixture_hand_ids() -> list[str]:
    """Les identifiants des 32 mains de la fixture du smoke grande liste."""
    fixture_dir = ROOT / "tests" / "trainer" / "fixtures"
    assert (fixture_dir / "review_inbox_large_list_builder.py").is_file(), fixture_dir
    if str(fixture_dir) not in sys.path:
        sys.path.insert(0, str(fixture_dir))
    import review_inbox_large_list_builder as builder

    assert builder.HAND_TOTAL >= 32, builder.HAND_TOTAL
    ids = [str(spec["hand_id"]) for spec in builder.hand_specs()]
    assert len(ids) == builder.HAND_TOTAL and len(set(ids)) == len(ids), ids
    return ids


def run_shell_budget(budget: dict) -> dict:
    node = shutil.which("node")
    assert node is not None, "node runtime is required for the inbox shell-budget contract"
    completed = subprocess.run(
        [node, "-e", SHELL_BUDGET_RUNTIME_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "INBOX_SHELL_BUDGET": json.dumps(budget)},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def _shell_budget_payload(model: dict, ids: list[str]) -> dict:
    """La géométrie dérivée, dans la forme attendue par le harnais node."""
    return {
        "baseHeight": model["available"] + model["pieces"]["pager"],
        "pagerHeight": model["pieces"]["pager"],
        "rowHeight": model["row"],
        "gap": model["gap"],
        "ids": list(ids),
    }


def _serve_shell_measurement(model: dict, ids: list[str]) -> dict:
    measured = run_shell_budget(_shell_budget_payload(model, ids))["measured"]
    assert measured is not None, "le harnais doit mesurer la coque servie"
    return measured


# Les leviers de la réconciliation T5b, chacun rejoué à l'envers dans une copie
# en mémoire des octets servis : `(token servi, token d'avant)`. Le dernier jeu
# reconstruit exactement les octets d'avant la task, d'où l'ancrage de
# calibration (`SHELL_PRE_CHANGE_MEASURED_PAGE_SIZE`).
SHELL_COMPACTION_REVERTS = (
    (
        ".hh-list{margin-top:4px;",
        ".hh-list{margin-top:10px;",
    ),
    (
        "  .review-inbox-primary-tools{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:4px 0 4px}\n"
        "  .review-inbox-primary-tools .field{display:grid;grid-template-columns:auto minmax(0,1fr);"
        "align-items:center;gap:8px;min-width:210px}\n"
        "  .review-inbox-primary-tools label{margin:0;white-space:nowrap}",
        "  .review-inbox-primary-tools{display:flex;align-items:end;gap:9px;flex-wrap:wrap;margin:10px 0 8px}\n"
        "  .review-inbox-primary-tools .field{min-width:170px}",
    ),
    (
        ".review-inbox-filters{margin:2px 0 4px;",
        ".review-inbox-filters{margin:6px 0 10px;",
    ),
    (
        ".review-inbox-notice{min-height:14px;margin:2px 0 4px;",
        ".review-inbox-notice{min-height:16px;margin:4px 0 7px;",
    ),
    (
        ".review-inbox-loss b{font-size:13px;color:#f1c66d;margin-left:4px}",
        ".review-inbox-loss b{display:block;font-size:15px;color:#f1c66d;margin-top:2px}",
    ),
    (
        ".review-inbox-open{display:grid;grid-template-columns:minmax(120px,0.9fr) 150px",
        ".review-inbox-open{display:grid;grid-template-columns:136px 104px",
    ),
    (
        ".hh-selection-title{margin:0 0 4px;",
        ".hh-selection-title{margin:0 0 8px;",
    ),
    (
        ".app-list-pager{display:flex;flex:0 0 auto;align-items:center;justify-content:flex-end;"
        "gap:10px;margin:4px 0 0}",
        ".app-list-pager{display:flex;flex:0 0 auto;align-items:center;justify-content:flex-end;"
        "gap:10px;margin:10px 0 0}",
    ),
    (
        ".app-list-pager button{width:auto;min-width:104px;padding:6px 12px}",
        ".app-list-pager button{width:auto;min-width:104px;padding:7px 12px}",
    ),
)


def _revert(*labels: str) -> tuple[tuple[str, str], ...]:
    by_token = {token: (token, before) for token, before in SHELL_COMPACTION_REVERTS}
    selected = []
    for label in labels:
        assert label in by_token, label
        selected.append(by_token[label])
    return tuple(selected)


# `(label, reverts, (fit typographique, page typographique, fit majorant, page
# majorante))`. Chaque contrôle doit être vu par la dérivation (`fit` ou page) et
# chaque levier doit être porteur de la cible : sans lui, le modèle conservateur
# ne garantit plus 10 lignes (`fit` ou page sous `REVIEW_INBOX_PAGE_SIZE_MIN`).
SHELL_MUTATION_CONTROLS = (
    (
        "cellule-perte-ev",
        _revert(".review-inbox-loss b{font-size:13px;color:#f1c66d;margin-left:4px}"),
        (9, 9, 7, 7),
    ),
    (
        "rangée-contrôles-premier-niveau",
        _revert(
            "  .review-inbox-primary-tools{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:4px 0 4px}\n"
            "  .review-inbox-primary-tools .field{display:grid;grid-template-columns:auto minmax(0,1fr);"
            "align-items:center;gap:8px;min-width:210px}\n"
            "  .review-inbox-primary-tools label{margin:0;white-space:nowrap}"
        ),
        (10, 10, 9, 9),
    ),
    ("marges-filtres", _revert(".review-inbox-filters{margin:2px 0 4px;"), (11, 11, 9, 10)),
    ("réserve-avis", _revert(".review-inbox-notice{min-height:14px;margin:2px 0 4px;"), (11, 11, 9, 10)),
    (
        "octets-d-avant-la-task",
        SHELL_COMPACTION_REVERTS,
        (SHELL_PRE_CHANGE_MEASURED_PAGE_SIZE, SHELL_PRE_CHANGE_MEASURED_PAGE_SIZE, 6, 6),
    ),
)


def check_shell_budget_measurement() -> None:
    """#395 T5b — la page peinte à 1500x1000, épinglée sur les octets servis."""
    derivation = _shell_derivation()
    # Le modèle conservateur et son avance de glyphe sont *ceux des contrats
    # frères*, jamais une seconde constante choisie ici.
    assert SHELL_MAJORANT_LINE_FACTOR == derivation.DEFAULT_LINE_FACTOR, (
        SHELL_MAJORANT_LINE_FACTOR,
        derivation.DEFAULT_LINE_FACTOR,
    )
    assert SHELL_CHAR_ADVANCE_EM == derivation.CHAR_ADVANCE_EM, (
        SHELL_CHAR_ADVANCE_EM,
        derivation.CHAR_ADVANCE_EM,
    )
    page_min = int(re.search(r"const REVIEW_INBOX_PAGE_SIZE_MIN=(\d+);", INDEX).group(1))
    page_max = int(re.search(r"const REVIEW_INBOX_PAGE_SIZE_MAX=(\d+);", INDEX).group(1))
    assert (page_min, page_max) == (10, 15), (page_min, page_max)
    ids = fixture_hand_ids()
    assert len(ids) == 32, ids

    typographic = shell_budget(INDEX, SHELL_TYPOGRAPHIC_LINE_FACTOR)
    majorant = shell_budget(INDEX, SHELL_MAJORANT_LINE_FACTOR)

    # 1. la valeur épinglée : le modèle conservateur (borne haute des lignes)
    #    doit laisser la liste porter la cible, et le modèle typographique la
    #    dépasser — les deux sont dans la fenêtre 10–15.
    assert majorant["pageSize"] == SHELL_MAJORANT_PAGE_SIZE, majorant
    assert typographic["pageSize"] == SHELL_TYPOGRAPHIC_PAGE_SIZE, typographic
    assert SHELL_MAJORANT_PAGE_SIZE >= page_min, SHELL_MAJORANT_PAGE_SIZE
    assert typographic["pageSize"] >= majorant["pageSize"], (typographic, majorant)
    assert typographic["pageSize"] <= page_max, typographic
    # La cellule « perte EV » reste sur ses deux lignes déclarées : la colonne
    # réellement reçue est assez large pour les trois textes. C'est ce qui rend
    # la hauteur de rangée lisible sans navigateur.
    for model in (typographic, majorant):
        assert model["lossLines"] == 2, model
        assert model["lossColumn"] >= 150, model
    assert majorant["pitch"] >= typographic["pitch"] >= majorant["pitchMin"], (typographic, majorant)

    # 2. la mesure : le vrai `renderReviewInboxPage`, sur les vrais identifiants
    #    de la fixture, dans la coque dérivée. Elle ne déborde pas et la liste
    #    reste paginée (≥ 2 pages pour 32 mains) dans les deux modèles.
    for model in (typographic, majorant):
        measured = _serve_shell_measurement(model, ids)
        assert measured["size"] == model["pageSize"], (model, measured)
        assert measured["paintedCount"] == model["pageSize"], (model, measured)
        assert measured["painted"] == ids[: model["pageSize"]], (model, measured)
        assert not measured["overflow"], (model, measured)
        assert measured["scrollHeight"] <= measured["clientHeight"] + 1, (model, measured)
        assert measured["pageCount"] >= 2, (model, measured)
        assert measured["pagerVisible"] and measured["everyPaintMeasuredWithPager"], (model, measured)

    # 3. non-vacuité : chaque levier de la réconciliation est rejoué à l'envers
    #    dans une copie en mémoire des octets servis, et la dérivation doit le
    #    voir. Le dernier contrôle reconstruit exactement les octets d'avant
    #    cette task : le modèle typographique y retrouve les 8 lignes mesurées
    #    par la revue dans un vrai navigateur (ancrage de calibration).
    served_fit = (
        typographic["fit"],
        typographic["pageSize"],
        majorant["fit"],
        majorant["pageSize"],
    )
    for label, reverts, expected in SHELL_MUTATION_CONTROLS:
        mutated = INDEX
        for token, replacement in reverts:
            assert mutated.count(token) == 1, (label, token)
            mutated = mutated.replace(token, replacement)
        assert mutated != INDEX, label
        typo = shell_budget(mutated, SHELL_TYPOGRAPHIC_LINE_FACTOR)
        major = shell_budget(mutated, SHELL_MAJORANT_LINE_FACTOR)
        seen = (typo["fit"], typo["pageSize"], major["fit"], major["pageSize"])
        assert seen == expected, (label, seen)
        assert seen != served_fit, f"le contrôle {label} doit être vu par la dérivation"
        # Le levier est porteur : sans lui, le modèle conservateur ne tient plus
        # la cible de 10 lignes (ni en capacité mesurée, ni sur la page peinte).
        assert major["fit"] < page_min or major["pageSize"] < page_min, (
            f"le levier {label} doit porter la cible dans le modèle conservateur",
            seen,
        )
        # ...et la dérivation décrit bien la page que le vrai code peint.
        for model in (typo, major):
            measured = _serve_shell_measurement(model, ids)
            assert measured["size"] == model["pageSize"], (label, measured, model["pageSize"])
        if label == "octets-d-avant-la-task":
            assert typo["pageSize"] == SHELL_PRE_CHANGE_MEASURED_PAGE_SIZE, typo
    # ...et la dérivation est sensible dans l'autre sens aussi : retirer de la
    # hauteur rend la page plus grande, donc les pièces sont bien lues une par
    # une et non figées.
    shrunk_text = INDEX.replace(".hh-selection-title{margin:0 0 4px;", ".hh-selection-title{margin:0;")
    assert shrunk_text != INDEX, "le titre de panneau doit rester déclaré pour ce contrôle"
    shrunk = shell_budget(shrunk_text, SHELL_TYPOGRAPHIC_LINE_FACTOR)
    assert shrunk["available"] > typographic["available"], (shrunk, typographic)

    assert INDEX_PATH.read_text(encoding="utf-8") == INDEX, "les mutations ne doivent jamais écrire site/index.html"
    return {
        "typographic": typographic,
        "majorant": majorant,
        "ids": ids,
    }


def main() -> None:
    check_static_contract()
    check_runtime_contract()
    shell = check_shell_budget_measurement()
    measured = shell["majorant"]
    print(
        "review inbox pagination contract checks: OK "
        "(page window 10–15 measured on the constrained shell, shrink without hidden overflow, "
        "bounded pager, filter/sort restart at page 1, selection preserved, "
        f"pinned page size at {SHELL_VIEWPORT[0]}x{SHELL_VIEWPORT[1]} = "
        f"{SHELL_MAJORANT_PAGE_SIZE}–{SHELL_TYPOGRAPHIC_PAGE_SIZE} on the served shell with the "
        f"{len(shell['ids'])}-hand fixture — conservative budget: chrome "
        f"{measured['chrome']:.2f}px, list {measured['available']:.2f}px, row "
        f"{measured['row']:.2f}px, pitch {measured['pitch']:.2f}px)"
    )


if __name__ == "__main__":
    main()
