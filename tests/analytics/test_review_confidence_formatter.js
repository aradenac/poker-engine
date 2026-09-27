'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Formatter=require('../../src/analytics/review-confidence-formatter.js');

const SRC=path.join(__dirname,'..','..','src','analytics','review-confidence-formatter.js');
const SCHEMA=JSON.parse(fs.readFileSync(path.join(__dirname,'..','..','contracts','analytics','review-inbox.schema.json'),'utf8'));

// #424: the formatter is a pure presentation layer over the T1 `hybrid`
// projection (`poker-review-hybrid-result/v1`). No DOM, no EV/range computation.
{
  const source=fs.readFileSync(SRC,'utf8');
  assert.doesNotMatch(source,/\bdocument\b/);
  assert.doesNotMatch(source,/\bwindow\b/);
  assert.doesNotMatch(source,/\bquerySelector\b|\bgetElementById\b|\baddEventListener\b/);
  // The formatter only reads values the caller already decided: no evaluator,
  // no range maths, no leak/EV engine dependency.
  assert.doesNotMatch(source,/require\(['"][^'"]*(leak-analyzer|review-score-adapter|review-inbox|analysis-state)/);
}

// The formatter vocabulary must stay aligned with the frozen T1 schema enums.
{
  const schemaStates=SCHEMA.$defs.hybrid.properties.support_state.enum;
  assert.deepEqual([...Formatter.SUPPORT_STATE_VALUES].sort(),[...schemaStates].sort());
  const schemaLevels=SCHEMA.$defs.hybrid.properties.confidence_level.enum;
  assert.deepEqual([...Formatter.CONFIDENCE_LEVEL_VALUES].sort(),[...schemaLevels].sort());
}

// support_state -> {label_fr, tone}. Unknown/absent states fabricate nothing.
{
  const strong=Formatter.formatSupportStateLabel('STRONG_SUPPORT');
  assert.equal(strong.label_fr,'Support fort');
  assert.equal(strong.tone,Formatter.TONE.POSITIVE);
  assert.deepEqual(Object.keys(strong).sort(),['label_fr','tone']);

  const robust=Formatter.formatSupportStateLabel('ROBUST');
  assert.equal(robust.label_fr,'Support robuste');
  assert.equal(robust.tone,Formatter.TONE.POSITIVE);

  const sparse=Formatter.formatSupportStateLabel('SPARSE_ESTIMATED');
  assert.match(sparse.label_fr,/estimation/i);
  assert.equal(sparse.tone,Formatter.TONE.CAUTION);

  const ood=Formatter.formatSupportStateLabel('OOD_UNSUPPORTED');
  assert.equal(ood.tone,Formatter.TONE.ABSTAIN);

  const close=Formatter.formatSupportStateLabel('LOW_CONFIDENCE_TOO_CLOSE');
  assert.equal(close.tone,Formatter.TONE.CAUTION);

  // lower-case input is normalized, unknown input stays neutral and empty.
  assert.equal(Formatter.formatSupportStateLabel('robust').label_fr,'Support robuste');
  for(const missing of [null,undefined,'','DOES_NOT_EXIST',42,{}]){
    const out=Formatter.formatSupportStateLabel(missing);
    assert.equal(out.label_fr,'');
    assert.equal(out.tone,Formatter.TONE.NEUTRAL);
  }
  // A returned label object is fresh on every call (pure, no shared mutable state).
  assert.notEqual(Formatter.formatSupportStateLabel('ROBUST'),Formatter.formatSupportStateLabel('ROBUST'));
}

// confidence_level -> qualitative French label, never a percentage or certainty.
{
  assert.equal(Formatter.formatConfidenceLevel('HIGH'),'Confiance élevée');
  assert.equal(Formatter.formatConfidenceLevel('MEDIUM'),'Confiance moyenne');
  assert.equal(Formatter.formatConfidenceLevel('LOW'),'Confiance faible');
  assert.equal(Formatter.formatConfidenceLevel('high'),'Confiance élevée');
  for(const missing of [null,undefined,'','UNKNOWN']){
    assert.equal(Formatter.formatConfidenceLevel(missing),'');
  }
}

// EV display: an exact value stays bare, an estimate is always marked.
{
  assert.equal(Formatter.formatEvDisplay({ev_bb:-0.35}),'-0.35 bb');
  assert.equal(Formatter.formatEvDisplay({ev_bb:1,support_state:'ROBUST'}),'1.00 bb');
  assert.equal(Formatter.formatEvDisplay({ev_bb:0}),'0.00 bb');

  const flagged=Formatter.formatEvDisplay({ev_bb:-0.35,is_estimate:true});
  assert.ok(flagged.startsWith(Formatter.ESTIMATE_PREFIX),'flagged estimate keeps the ≈ prefix');
  assert.ok(flagged.endsWith(Formatter.ESTIMATE_SUFFIX),'flagged estimate keeps the (estimation) suffix');

  // Hard acceptance: SPARSE_ESTIMATED is never rendered as an exact value,
  // even when the caller forgot to set `is_estimate`.
  const sparse=Formatter.formatEvDisplay({ev_bb:0.42,is_estimate:false,support_state:'SPARSE_ESTIMATED'});
  assert.ok(sparse.startsWith('≈'),'sparse EV carries the ≈ prefix');
  assert.ok(sparse.includes('(estimation)'),'sparse EV carries the estimation marker');
  assert.notEqual(sparse,'0.42 bb');

  // No value -> nothing fabricated (never a synthetic 0.00 bb).
  for(const bad of [null,undefined,{}, {ev_bb:null},{ev_bb:'n/a'},{ev_bb:NaN},{ev_bb:true}]) {
    assert.equal(Formatter.formatEvDisplay(bad),'');
  }
  // Non-sparse states do not gain an estimation marker.
  assert.equal(Formatter.formatEvDisplay({ev_bb:-1.5,support_state:'STRONG_SUPPORT'}),'-1.50 bb');
}

// Abstention: no recommendation text is ever produced for an abstention or an
// out-of-distribution spot.
{
  const actionable='Vous devriez folder car EV-';
  assert.equal(Formatter.formatAbstentionReason({abstains:true,abstention_reason:actionable}),'');
  assert.equal(Formatter.formatAbstentionReason({abstains:true,support_state:'ROBUST',abstention_reason:actionable}),'');
  assert.equal(Formatter.formatAbstentionReason({abstains:false,support_state:'OOD_UNSUPPORTED',abstention_reason:actionable}),'');
  assert.equal(Formatter.formatAbstentionReason({support_state:'OOD_UNSUPPORTED'}),'');
  assert.equal(Formatter.formatAbstentionReason({}),'');
  assert.equal(Formatter.formatAbstentionReason(null),'');

  // A genuine reason on a supported, non-abstaining spot is echoed.
  assert.equal(
    Formatter.formatAbstentionReason({abstains:false,abstention_reason:'  Spot hors distribution  '}),
    'Spot hors distribution'
  );

  // Whatever the branch, the output never recommends an action.
  for(const input of [
    {abstains:true,abstention_reason:actionable},
    {support_state:'OOD_UNSUPPORTED',abstention_reason:actionable},
    {abstains:false,abstention_reason:'Position neutre'}
  ]){
    const out=Formatter.formatAbstentionReason(input);
    assert.doesNotMatch(out,/\b(recommand|conseil|jouer|folder|call|raise)\w*/i);
  }
}

// Too-close notice is dedicated and only fires on a real too-close verdict.
{
  assert.equal(Formatter.formatTooCloseNotice({too_close:false}),'');
  assert.equal(Formatter.formatTooCloseNotice({}),'');
  assert.equal(Formatter.formatTooCloseNotice(null),'');
  assert.equal(Formatter.formatTooCloseNotice({too_close:false,support_state:'ROBUST'}),'');

  const notice=Formatter.formatTooCloseNotice({too_close:true});
  assert.ok(notice.length>0);
  assert.match(notice,/trop proche/i);
  assert.equal(Formatter.formatTooCloseNotice({support_state:'LOW_CONFIDENCE_TOO_CLOSE'}),notice);
  assert.doesNotMatch(notice,/\b(recommand|conseil|jouer|folder|call|raise)\w*/i);
}

// Advanced provenance view: fixed key order, nulls for absent fields.
{
  const hybrid={
    schema:Formatter.HYBRID_SCHEMA,
    support_state:'SPARSE_ESTIMATED',
    uncertainty_note:'Intervalle large sur cet échantillon',
    provenance:{route:'HYBRID_BACKOFF',source:'model_b+model_a',model_id:'gbm-2026-09',model_hash:'sha256:abcd',ood_status:'IN_DISTRIBUTION',ood_reason:null}
  };
  const view=Formatter.formatAdvancedProvenance(hybrid);
  assert.deepEqual(Object.keys(view),['route','source','model_id','model_hash','ood_status','ood_reason','support_state','uncertainty_note']);
  assert.equal(view.route,'HYBRID_BACKOFF');
  assert.equal(view.source,'model_b+model_a');
  assert.equal(view.model_id,'gbm-2026-09');
  assert.equal(view.model_hash,'sha256:abcd');
  assert.equal(view.ood_status,'IN_DISTRIBUTION');
  assert.equal(view.ood_reason,null);
  assert.equal(view.support_state,'SPARSE_ESTIMATED');
  assert.equal(view.uncertainty_note,'Intervalle large sur cet échantillon');

  // Absent hybrid/provenance -> all null, nothing invented.
  for(const missing of [null,undefined,{}, {support_state:'nope'}, {provenance:null}]){
    const empty=Formatter.formatAdvancedProvenance(missing);
    for(const key of ['route','source','model_id','model_hash','ood_status','ood_reason','support_state','uncertainty_note']){
      assert.equal(empty[key],null,`${key} stays null for ${JSON.stringify(missing)}`);
    }
  }

  // The input object is not mutated by the projection.
  const before=JSON.stringify(hybrid);
  Formatter.formatAdvancedProvenance(hybrid);
  assert.equal(JSON.stringify(hybrid),before);
}

// Hard rule: no formatter output may ever carry absolute certainty, including
// hostile free-text inputs and every confidence level.
{
  const states=[...Formatter.SUPPORT_STATE_VALUES,null,'UNKNOWN'];
  const levels=[...Formatter.CONFIDENCE_LEVEL_VALUES,null,'UNKNOWN'];
  const texts=['','100% sûr','résultat certain','preuve absolue','spot incertain','UNCERTAIN'];
  const outputs=[];
  for(const support_state of states){
    for(const confidence_level of levels){
      outputs.push(Formatter.formatSupportStateLabel(support_state).label_fr);
      outputs.push(Formatter.formatConfidenceLevel(confidence_level));
      for(const is_estimate of [true,false]){
        outputs.push(Formatter.formatEvDisplay({ev_bb:0.25,is_estimate,support_state}));
      }
      for(const abstention_reason of texts){
        outputs.push(Formatter.formatAbstentionReason({abstains:false,abstention_reason,support_state}));
      }
      outputs.push(Formatter.formatTooCloseNotice({too_close:true,support_state}));
      for(const uncertainty_note of texts){
        outputs.push(Formatter.formatAdvancedProvenance({support_state,uncertainty_note,provenance:{route:'R',ood_reason:texts[1]}}).uncertainty_note);
        outputs.push(Formatter.formatAdvancedProvenance({support_state,uncertainty_note,provenance:{route:'R',ood_reason:texts[1]}}).ood_reason);
      }
    }
  }
  outputs.push(Formatter.TOO_CLOSE_NOTICE);
  for(const out of outputs){
    // The provenance view legitimately returns `null` for a dropped/absent field.
    assert.ok(out==null||typeof out==='string',`unexpected output type: ${typeof out}`);
    const rendered=out==null?'':out;
    assert.equal(Formatter.containsAbsoluteCertainty(rendered),false,`certainty leaked in: ${rendered}`);
    assert.doesNotMatch(rendered,/100\s*%/,`'100%' leaked in: ${rendered}`);
  }
  // The detector itself is word-aware: it flags certainty but not `uncertain`.
  assert.equal(Formatter.containsAbsoluteCertainty('100% garanti'),true);
  assert.equal(Formatter.containsAbsoluteCertainty('résultat certain'),true);
  assert.equal(Formatter.containsAbsoluteCertainty('uncertainty_note'),false);
}

// #424 T5: end-to-end rendering of the five canonical `support_state` fixtures.
// Each inline fixture is a complete `poker-review-hybrid-result/v1` projection;
// the composed row must never fabricate certainty, an estimation marker or a
// recommendation its own projection did not carry.
{
  const FIXTURES=[
    {name:'STRONG_SUPPORT',hybrid:{
      schema:Formatter.HYBRID_SCHEMA,support_state:'STRONG_SUPPORT',confidence_level:'HIGH',
      is_estimate:false,ev_bb:-0.8,uncertainty_note:null,abstains:false,abstention_reason:null,too_close:false,
      provenance:{route:'DIRECT_MODEL_A',source:'model_a',model_id:'gbm-2026-09',model_hash:'sha256:1111',ood_status:'IN_DISTRIBUTION',ood_reason:null}}},
    {name:'ROBUST',hybrid:{
      schema:Formatter.HYBRID_SCHEMA,support_state:'ROBUST',confidence_level:'HIGH',
      is_estimate:false,ev_bb:1,uncertainty_note:null,abstains:false,abstention_reason:'Position claire',too_close:false,
      provenance:{route:'DIRECT_MODEL_B',source:'model_b',model_id:'gbm-2026-09',model_hash:'sha256:2222',ood_status:'IN_DISTRIBUTION',ood_reason:null}}},
    {name:'SPARSE_ESTIMATED',hybrid:{
      schema:Formatter.HYBRID_SCHEMA,support_state:'SPARSE_ESTIMATED',confidence_level:'MEDIUM',
      is_estimate:true,ev_bb:0.42,uncertainty_note:'Intervalle large sur cet échantillon',abstains:false,abstention_reason:null,too_close:false,
      provenance:{route:'HYBRID_BACKOFF',source:'model_b+model_a',model_id:'gbm-2026-09',model_hash:'sha256:3333',ood_status:'IN_DISTRIBUTION',ood_reason:null}}},
    {name:'OOD_UNSUPPORTED',hybrid:{
      schema:Formatter.HYBRID_SCHEMA,support_state:'OOD_UNSUPPORTED',confidence_level:'LOW',
      is_estimate:false,ev_bb:null,uncertainty_note:'Spot hors du domaine du modèle',abstains:false,abstention_reason:'Vous devriez folder car EV-',too_close:false,
      provenance:{route:'ABSTAIN',source:'none',model_id:'gbm-2026-09',model_hash:'sha256:4444',ood_status:'OUT_OF_DISTRIBUTION',ood_reason:'SPOT_NOT_IN_TRAINING_RANGE'}}},
    {name:'LOW_CONFIDENCE_TOO_CLOSE',hybrid:{
      schema:Formatter.HYBRID_SCHEMA,support_state:'LOW_CONFIDENCE_TOO_CLOSE',confidence_level:'LOW',
      is_estimate:true,ev_bb:-0.05,uncertainty_note:'Marge trop faible pour conclure',abstains:false,abstention_reason:null,too_close:true,
      provenance:{route:'HYBRID_BACKOFF',source:'model_b',model_id:'gbm-2026-09',model_hash:'sha256:5555',ood_status:'IN_DISTRIBUTION',ood_reason:null}}}
  ];
  const render=h=>({
    label:Formatter.formatSupportStateLabel(h.support_state).label_fr,
    tone:Formatter.formatSupportStateLabel(h.support_state).tone,
    confidence:Formatter.formatConfidenceLevel(h.confidence_level),
    ev:Formatter.formatEvDisplay(h),
    abstention:Formatter.formatAbstentionReason(h),
    too_close:Formatter.formatTooCloseNotice(h),
    provenance:Formatter.formatAdvancedProvenance(h)
  });
  const rows=new Map(FIXTURES.map(f=>[f.name,render(f.hybrid)]));

  // The inline fixtures cover the frozen enum exactly, so no state is untested.
  assert.deepEqual([...rows.keys()].sort(),[...Formatter.SUPPORT_STATE_VALUES].sort());

  // No composed field of any fixture may surface absolute certainty.
  for(const [name,row] of rows){
    assert.equal(row.tone,Formatter.SUPPORT_STATE_TONES[name],'the tone must match the fixture state');
    assert.ok(row.label.length>0,'every declared state has a label');
    for(const field of ['label','confidence','ev','abstention','too_close']){
      assert.equal(Formatter.containsAbsoluteCertainty(row[field]),false,`${name}.${field} leaked certainty`);
      assert.doesNotMatch(row[field],/100\s*%/,`${name}.${field} leaked '100%'`);
    }
  }

  // Supported, non-estimated spots: a bare exact EV and no caution notice.
  for(const name of ['STRONG_SUPPORT','ROBUST']){
    const row=rows.get(name);
    assert.equal(row.tone,Formatter.TONE.POSITIVE);
    assert.doesNotMatch(row.ev,/≈/,'a supported exact EV carries no ≈ prefix');
    assert.doesNotMatch(row.ev,/estimation/,'a supported exact EV carries no estimation marker');
    assert.equal(row.too_close,'');
    assert.equal(rows.get('ROBUST').abstention,'Position claire','a genuine reason is echoed');
    assert.equal(rows.get('STRONG_SUPPORT').abstention,'');
  }

  // SPARSE_ESTIMATED: the EV is always marked as an estimate, never bare.
  const sparse=rows.get('SPARSE_ESTIMATED');
  assert.equal(sparse.tone,Formatter.TONE.CAUTION);
  assert.ok(sparse.ev.startsWith(Formatter.ESTIMATE_PREFIX),'the sparse EV keeps the ≈ prefix');
  assert.ok(sparse.ev.endsWith(Formatter.ESTIMATE_SUFFIX),'the sparse EV keeps the (estimation) suffix');
  assert.doesNotMatch(sparse.ev,/^[\d-]/,'a sparse EV never starts with a bare number');
  assert.match(sparse.label,/estimation/i,'the sparse label is explicitly marked as an estimation');

  // OOD_UNSUPPORTED with an actionable-looking reason but `abstains:false`: the
  // support state alone must drop the recommendation. No EV, no abstention text
  // and no recommendation verb anywhere in the composed row.
  const ood=rows.get('OOD_UNSUPPORTED');
  assert.equal(ood.abstention,'','an OOD spot never renders a reason, even without the abstains flag');
  assert.equal(ood.tone,Formatter.TONE.ABSTAIN);
  assert.equal(ood.ev,'','an unsupported spot renders no EV');
  for(const field of ['label','confidence','ev','abstention','too_close']){
    assert.doesNotMatch(ood[field],/\b(recommand|conseil|jouer|folder|call|raise)\w*/i,`OOD.${field} must never carry a recommendation`);
  }
  // The `abstains` flag is an independent authority: a supported spot that
  // abstains is just as silent as an unsupported one.
  assert.equal(Formatter.formatAbstentionReason({support_state:'ROBUST',abstains:true,abstention_reason:'Vous devriez folder car EV-'}),'');
  assert.equal(Formatter.formatAbstentionReason({support_state:'STRONG_SUPPORT',abstains:true,abstention_reason:'Il faut raise'}),'');

  // LOW_CONFIDENCE_TOO_CLOSE: the dedicated too-close notice, still traceable.
  const close=rows.get('LOW_CONFIDENCE_TOO_CLOSE');
  assert.equal(close.tone,Formatter.TONE.CAUTION);
  assert.equal(close.too_close,Formatter.TOO_CLOSE_NOTICE,'a too-close verdict uses its own dedicated message');
  assert.match(close.too_close,/trop proche/i);
  assert.doesNotMatch(close.too_close,/\b(recommand|conseil|jouer|folder|call|raise)\w*/i);

  // The advanced view keeps its fixed key order and the full provenance for
  // each fixture, with the OOD verdict carried through.
  for(const f of FIXTURES){
    const view=render(f.hybrid).provenance,p=f.hybrid.provenance;
    assert.deepEqual(Object.keys(view),['route','source','model_id','model_hash','ood_status','ood_reason','support_state','uncertainty_note']);
    assert.equal(view.route,p.route,`${f.name} route`);
    assert.equal(view.source,p.source,`${f.name} source`);
    assert.equal(view.model_id,p.model_id,`${f.name} model_id`);
    assert.equal(view.model_hash,p.model_hash,`${f.name} model_hash`);
    assert.equal(view.ood_status,p.ood_status,`${f.name} ood_status`);
    assert.equal(view.support_state,f.hybrid.support_state,`${f.name} support_state`);
  }
  const oodView=rows.get('OOD_UNSUPPORTED').provenance;
  assert.equal(oodView.route,'ABSTAIN');
  assert.equal(oodView.ood_status,'OUT_OF_DISTRIBUTION');
  assert.equal(oodView.ood_reason,'SPOT_NOT_IN_TRAINING_RANGE');
  assert.equal(oodView.uncertainty_note,'Spot hors du domaine du modèle');
}

// Purity: repeated calls return structurally identical results.
{
  const hybrid={support_state:'SPARSE_ESTIMATED',is_estimate:true,ev_bb:-0.7,too_close:true,abstains:false};
  const snapshot=()=>[
    Formatter.formatSupportStateLabel(hybrid.support_state),
    Formatter.formatConfidenceLevel('HIGH'),
    Formatter.formatEvDisplay(hybrid),
    Formatter.formatAbstentionReason(hybrid),
    Formatter.formatTooCloseNotice(hybrid),
    Formatter.formatAdvancedProvenance(hybrid)
  ];
  assert.deepEqual(snapshot(),snapshot());
}

console.log(JSON.stringify({
  status:'PASS',
  schema:Formatter.HYBRID_SCHEMA,
  support_states:Formatter.SUPPORT_STATE_VALUES.length,
  confidence_levels:Formatter.CONFIDENCE_LEVEL_VALUES.length,
  tones:Object.values(Formatter.TONE)
}));
