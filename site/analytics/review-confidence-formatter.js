(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerReviewConfidenceFormatter=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  // Pure presentation layer for the optional `hybrid` projection of
  // `poker-review-inbox-item/v1` (`poker-review-hybrid-result/v1`, #424).
  // It formats values that were already decided elsewhere: it never parses a
  // hand history, never touches a DOM node and never computes an EV, a range
  // or a probability. `abstains`/`support_state` are authoritative inputs and
  // are never re-derived from the EV.
  const HYBRID_SCHEMA='poker-review-hybrid-result/v1';

  const SUPPORT_STATES={
    STRONG_SUPPORT:'STRONG_SUPPORT',
    ROBUST:'ROBUST',
    SPARSE_ESTIMATED:'SPARSE_ESTIMATED',
    OOD_UNSUPPORTED:'OOD_UNSUPPORTED',
    LOW_CONFIDENCE_TOO_CLOSE:'LOW_CONFIDENCE_TOO_CLOSE'
  };
  const SUPPORT_STATE_VALUES=Object.freeze(Object.values(SUPPORT_STATES));
  const CONFIDENCE_LEVELS={HIGH:'HIGH',MEDIUM:'MEDIUM',LOW:'LOW'};
  const CONFIDENCE_LEVEL_VALUES=Object.freeze(Object.values(CONFIDENCE_LEVELS));

  // Tones are a closed vocabulary the UI maps to a colour. `abstain` is
  // deliberately distinct from `caution`: an abstention is not a weak opinion,
  // it is the explicit absence of one.
  const TONE={POSITIVE:'positive',NEUTRAL:'neutral',CAUTION:'caution',ABSTAIN:'abstain'};

  const SUPPORT_STATE_LABELS={
    STRONG_SUPPORT:'Support fort',
    ROBUST:'Support robuste',
    SPARSE_ESTIMATED:'Support limité (estimation)',
    OOD_UNSUPPORTED:'Hors distribution (non supporté)',
    LOW_CONFIDENCE_TOO_CLOSE:'Verdict trop proche'
  };
  const SUPPORT_STATE_TONES={
    STRONG_SUPPORT:TONE.POSITIVE,
    ROBUST:TONE.POSITIVE,
    SPARSE_ESTIMATED:TONE.CAUTION,
    OOD_UNSUPPORTED:TONE.ABSTAIN,
    LOW_CONFIDENCE_TOO_CLOSE:TONE.CAUTION
  };

  // Absolute certainty is never a reviewable statement: a High confidence is
  // still a confidence, never a guarantee. No label below carries a certainty
  // token, and every free-text output is filtered through `guardCertainty`.
  const CONFIDENCE_LABELS={
    HIGH:'Confiance élevée',
    MEDIUM:'Confiance moyenne',
    LOW:'Confiance faible'
  };
  // The `certain` pattern is word-bounded so the legitimate scientific
  // vocabulary (`uncertain`, `uncertainty_note`) is never mistaken for a
  // certainty claim.
  const CERTAINTY_PATTERNS=[
    /\b100\s*%/,
    /(?<![a-z0-9à-ÿ])certain(?:e|es|s)?(?![a-z0-9à-ÿ])/,
    /(?<![a-z0-9à-ÿ])certitude(?:s)?(?![a-z0-9à-ÿ])/,
    /(?<![a-z0-9à-ÿ])infaillible(?:s)?(?![a-z0-9à-ÿ])/,
    /(?<![a-z0-9à-ÿ])garanti(?:e|es|s)?(?![a-z0-9à-ÿ])/,
    /(?<![a-z0-9à-ÿ])absolu(?:e|es|s)?(?![a-z0-9à-ÿ])/
  ];

  const ESTIMATE_PREFIX='≈';
  const ESTIMATE_SUFFIX='(estimation)';
  const BB_UNIT=' bb';
  // A too-close verdict is a real verdict gap, not a nuance: the candidate
  // lines sit within noise of each other, so no action is singled out.
  const TOO_CLOSE_NOTICE='Verdict trop proche : les options sont quasi équivalentes, aucune action n’est mise en avant.';
  const ABSTENTION_NOTICE='';

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function finiteNumber(v){
    if(typeof v==='number')return Number.isFinite(v)?v:null;
    if(typeof v==='string'&&v.trim()){const n=Number(v);return Number.isFinite(n)?n:null;}
    return null;
  }
  function containsAbsoluteCertainty(value){
    const s=text(value).toLowerCase();
    if(!s)return false;
    return CERTAINTY_PATTERNS.some(re=>re.test(s));
  }
  // The hard rule is enforced at the output boundary, not only in the label
  // tables: provided text that would surface an absolute certainty is dropped
  // instead of being echoed as formatter output.
  function guardCertainty(value){
    const s=text(value);
    if(!s)return '';
    return containsAbsoluteCertainty(s)?'':s;
  }
  function normalizeSupportState(v){
    const key=upper(v);
    return SUPPORT_STATE_VALUES.includes(key)?key:null;
  }
  function isEstimated(input){
    return Boolean(input&&input.is_estimate)||normalizeSupportState(input&&input.support_state)===SUPPORT_STATES.SPARSE_ESTIMATED;
  }
  function formatBb(value){
    const n=Math.abs(value)<1e-9?0:value;
    return n.toFixed(2)+BB_UNIT;
  }

  // support_state -> {label_fr, tone}. An absent or unknown state fabricates
  // nothing: the label stays empty and the tone falls back to neutral.
  function formatSupportStateLabel(state){
    const key=normalizeSupportState(state);
    if(!key)return {label_fr:'',tone:TONE.NEUTRAL};
    return {label_fr:SUPPORT_STATE_LABELS[key],tone:SUPPORT_STATE_TONES[key]};
  }

  // Qualitative confidence only. There is intentionally no numeric or
  // percentage rendering, so no level can ever read as `100%`.
  function formatConfidenceLevel(level){
    const key=upper(level);
    return CONFIDENCE_LABELS[key]||'';
  }

  // EV display. A sparse estimate is never presented as an exact number: the
  // `≈` prefix and the `(estimation)` suffix are applied when the caller flags
  // `is_estimate` or when `support_state` is SPARSE_ESTIMATED, independently of
  // the flag. A missing or non-numeric value renders as an empty string rather
  // than a synthetic `0.00 bb`.
  function formatEvDisplay(input){
    const src=input&&typeof input==='object'?input:{};
    // Fail-closed guard, evaluated before any coercion of `ev_bb`: an
    // abstention or an out-of-distribution spot has no reviewable EV, so an
    // inconsistent upstream payload that still ships a finite number must not
    // smuggle a value past the abstention semantics.
    if(src.abstains===true||upper(src.abstains)==='TRUE')return '';
    if(normalizeSupportState(src.support_state)===SUPPORT_STATES.OOD_UNSUPPORTED)return '';
    const ev=finiteNumber(src.ev_bb);
    if(ev==null)return '';
    const body=formatBb(ev);
    return isEstimated(src)?(ESTIMATE_PREFIX+' '+body+' '+ESTIMATE_SUFFIX):body;
  }

  // Abstention rendering. When the model abstains, or when the spot sits
  // outside the supported distribution, the formatter returns no actionable
  // text at all: an abstention is not a recommendation and must never be
  // dressed as one. A genuine (non-abstaining) reason is echoed verbatim,
  // minus any absolute-certainty wording.
  function formatAbstentionReason(input){
    const src=input&&typeof input==='object'?input:{};
    const abstains=src.abstains===true||upper(src.abstains)==='TRUE';
    const ood=normalizeSupportState(src.support_state)===SUPPORT_STATES.OOD_UNSUPPORTED;
    if(abstains||ood)return ABSTENTION_NOTICE;
    return guardCertainty(src.abstention_reason);
  }

  // Dedicated notice for a too-close verdict. `too_close` is the explicit flag;
  // the `LOW_CONFIDENCE_TOO_CLOSE` support state carries the same semantics and
  // is accepted as an equivalent trigger.
  function formatTooCloseNotice(hybrid){
    const src=hybrid&&typeof hybrid==='object'?hybrid:{};
    const close=src.too_close===true||upper(src.too_close)==='TRUE';
    const stateClose=normalizeSupportState(src.support_state)===SUPPORT_STATES.LOW_CONFIDENCE_TOO_CLOSE;
    if(!close&&!stateClose)return '';
    return TOO_CLOSE_NOTICE;
  }

  // Advanced (provenance) view: the traceability fields the technical view
  // shows, with a fixed key order and `null` for every absent field so the
  // consumer never has to distinguish `undefined` from a missing column.
  function formatAdvancedProvenance(hybrid){
    const src=hybrid&&typeof hybrid==='object'?hybrid:{};
    const p=src.provenance&&typeof src.provenance==='object'?src.provenance:{};
    return {
      route:guardCertainty(p.route)||null,
      source:guardCertainty(p.source)||null,
      model_id:guardCertainty(p.model_id)||null,
      model_hash:guardCertainty(p.model_hash)||null,
      ood_status:guardCertainty(p.ood_status)||null,
      ood_reason:guardCertainty(p.ood_reason)||null,
      support_state:normalizeSupportState(src.support_state),
      uncertainty_note:guardCertainty(src.uncertainty_note)||null
    };
  }

  return {
    HYBRID_SCHEMA,SUPPORT_STATES,SUPPORT_STATE_VALUES,CONFIDENCE_LEVELS,CONFIDENCE_LEVEL_VALUES,TONE,
    SUPPORT_STATE_LABELS,SUPPORT_STATE_TONES,CONFIDENCE_LABELS,
    ESTIMATE_PREFIX,ESTIMATE_SUFFIX,TOO_CLOSE_NOTICE,ABSTENTION_NOTICE,
    formatSupportStateLabel,formatConfidenceLevel,formatEvDisplay,formatAbstentionReason,
    formatTooCloseNotice,formatAdvancedProvenance,
    containsAbsoluteCertainty
  };
});
