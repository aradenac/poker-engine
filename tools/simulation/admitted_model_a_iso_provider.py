#!/usr/bin/env python3
"""Explicit #352 Model-A-v2 provider for the real #314/#367 ISO runner.

The provider binds the already-admitted sizing-aware candidate by exact id/hash
and uses it only where it is scientifically required: opponent preflop response
to a Hero ISO at an exact supported price.  There is no nearest-price fallback
and no mutation of the active Model-A pointer.

Continuation assumptions are explicit:
- non-VS_ISO preflop and postflop exact nodes reuse the frozen active Model-A
  continuation selected before #367;
- Hero continuation after the fixed candidate uses the frozen #108
  SupportClosedModelAReferencePolicy;
- missing required sizing-aware VS_ISO support fails closed.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.ranges.model_a_posterior_runtime import ModelAPosteriorRuntime
from tools.preflop.model_a_sizing_likelihood import (
    canonical_candidate_sha256,
    resolve_support_likelihood,
)
from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
    _empirical_raise_target,
    _node_action_probability,
    _normalize,
    _normalize_weights,
    _position_map,
    _preflop_decision,
    _remove_blockers,
    _semantic_legal,
    _semantic_trace,
    calibrated_action_matrix,
    exact_postflop_node,
    exact_preflop_node,
    target_frequencies,
)
from tools.simulation.model_a_preflop_rollout import (
    ModelAPreflopContinuationRollout,
    RolloutUnsupported,
    _apply_policy_decision,
    _invoke_policy,
    _sample_fingerprint,
)
from tools.simulation.model_b_runtime import (
    best,
    ccode,
    cid,
    combo_class_ids,
    legal_combos,
    rake_net,
    weighted_choice,
)
from tools.simulation.reference_support_closure import (
    SupportClosedModelAReferencePolicy,
)
from tools.training.fit_model_a_preflop_sizing import load_support_report
from tools.training.fit_model_a_preflop_sizing_v2 import (
    build_candidate as build_v2_candidate,
    load_fit_protocol,
)

ROOT = Path(__file__).resolve().parents[2]
FIT_EVIDENCE = ROOT / "analysis/model_a_preflop_sizing_v2_fit.json"
VALIDATION_EVIDENCE = ROOT / "analysis/model_a_preflop_sizing_v2_validation.json"
REFERENCE_DESCRIPTOR = (
    ROOT / "training/full_hand/HERO_REFERENCE_POLICY_20260917_SUPPORT_CLOSED.json"
)

CANDIDATE_ID = "model-a-preflop-sizing-aware-candidate-v2"
CANDIDATE_SHA256 = "9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19"
VALIDATION_DECISION = "ADMIT_CANDIDATE"
FIT_EVIDENCE_SHA256 = "cacf97c80f44856da6e787b230ab1b564d5c0c83821a894e57b70aba92145738"
VALIDATION_EVIDENCE_SHA256 = "54f6e2affb0a088aa5148c981331abafe705ce7793433f89accbf304dc6f7496"
POPULATION_ID = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
ADMISSION_STATUS = "ADMITTED_FOR_SIZING_EV"


class Issue367ProviderError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _response_action(action: Any) -> str:
    value = str(action or "").upper()
    if value == "LIMP":
        return "CALL"
    if value in {"BET", "RAISE"}:
        return "RAISE"
    return value


def _is_required_sizing_context(decision: Mapping[str, Any]) -> bool:
    return (
        str(decision.get("family") or "").upper() == "VS_ISO"
        and str(decision.get("aggressor_position") or "").upper() == "SB"
    )


def _public_fingerprint(state: NoLimitHoldemState) -> str:
    payload = {
        "state": state.to_snapshot(include_log=False),
        "public_action_log": [
            {
                "index": row.get("index"),
                "street": row.get("street"),
                "player": row.get("player"),
                "action": row.get("action"),
                "target_total_bb": row.get("target_total_bb"),
                "incremental_cost_bb": row.get("incremental_cost_bb"),
            }
            for row in state.action_log
        ],
    }
    return "preflop-public:" + _canonical_sha(payload)


def load_admitted_candidate() -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild the #352 TRAIN candidate and bind it to persisted admission evidence."""
    fit = json.loads(FIT_EVIDENCE.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION_EVIDENCE.read_text(encoding="utf-8"))
    if fit.get("candidate_sha256") != CANDIDATE_SHA256:
        raise Issue367ProviderError("#352 fit candidate SHA mismatch")
    if fit.get("evidence_sha256") != FIT_EVIDENCE_SHA256:
        raise Issue367ProviderError("#352 fit evidence SHA mismatch")
    if validation.get("outcome") != VALIDATION_DECISION:
        raise Issue367ProviderError("#352 decision is not ADMIT_CANDIDATE")
    if validation.get("evidence_sha256") != VALIDATION_EVIDENCE_SHA256:
        raise Issue367ProviderError("#352 VALIDATION evidence SHA mismatch")
    if validation.get("test_consumed") is not False:
        raise Issue367ProviderError("#352 admission unexpectedly consumed TEST")
    if validation.get("active_model_replaced") is not False:
        raise Issue367ProviderError("#352 must not replace the active Model A")

    fit_protocol = load_fit_protocol()
    _, report = load_support_report()
    candidate, rebuilt_fit = build_v2_candidate(fit_protocol, report)
    rebuilt_sha = canonical_candidate_sha256(candidate)
    if rebuilt_sha != CANDIDATE_SHA256:
        raise Issue367ProviderError(
            f"rebuilt #352 candidate SHA mismatch: {rebuilt_sha}"
        )
    if rebuilt_fit.get("candidate_sha256") != CANDIDATE_SHA256:
        raise Issue367ProviderError("rebuilt #352 fit candidate identity drifted")
    return candidate, validation


def load_frozen_reference_policy() -> tuple[ModelAContinuationPolicy, SupportClosedModelAReferencePolicy, dict[str, Any]]:
    descriptor = json.loads(REFERENCE_DESCRIPTOR.read_text(encoding="utf-8"))
    if descriptor.get("population_id") != POPULATION_ID:
        raise Issue367ProviderError("reference population mismatch")
    runtime = descriptor.get("runtime") or {}
    if runtime.get("class") != "SupportClosedModelAReferencePolicy":
        raise Issue367ProviderError("unexpected frozen Hero reference runtime")
    artifacts = descriptor.get("artifacts") or {}
    pre = ROOT / artifacts["preflop_model"]["path"]
    post = ROOT / artifacts["postflop_baseline"]["path"]
    overlay = ROOT / artifacts["postflop_selected_overlay"]["path"]
    for name, path in (("preflop_model", pre), ("postflop_baseline", post), ("postflop_selected_overlay", overlay)):
        expected = str(artifacts[name]["sha256"])
        actual = _sha256(path)
        if actual != expected:
            raise Issue367ProviderError(
                f"frozen reference {name} SHA mismatch: {actual} != {expected}"
            )
    delegate = ModelAContinuationPolicy.from_paths(pre, post, overlay)
    hero = SupportClosedModelAReferencePolicy(delegate)
    return delegate, hero, descriptor


class Issue367OpponentPolicy(ModelAContinuationPolicy):
    """Hybrid continuation with fail-closed v2 exact sizing response likelihoods."""

    def __init__(
        self,
        candidate: Mapping[str, Any],
        frozen_reference: ModelAContinuationPolicy,
    ) -> None:
        self.sizing_candidate = copy.deepcopy(dict(candidate))
        self.reference = frozen_reference
        self.non_sizing_reference = SupportClosedModelAReferencePolicy(frozen_reference)
        super().__init__(
            frozen_reference.preflop_model,
            frozen_reference.postflop_model,
            identity={
                "candidate_id": CANDIDATE_ID,
                "candidate_sha256": CANDIDATE_SHA256,
                "population_id": POPULATION_ID,
                "admission_status": ADMISSION_STATUS,
                "sizing_required_for": "VS_ISO_AGGRESSOR_SB_EXACT_PRICE",
                "non_sizing_delegate": copy.deepcopy(frozen_reference.identity),
                "nearest_price": False,
            },
        )
        self.postflop_support_closure = collections.Counter()

    def _resolve_sizing(
        self,
        decision: Mapping[str, Any],
        hand_class: str | None,
    ) -> dict[str, Any]:
        resolved = resolve_support_likelihood(
            candidate=self.sizing_candidate,
            context=decision,
            hand_class=hand_class,
        )
        if resolved.get("status") != "RESOLVED":
            raise ModelAUnsupportedContext(
                "required admitted sizing-aware v2 exact-price support missing: "
                + str(resolved.get("support_context_key") or "")
            )
        return resolved

    def action_probabilities(
        self,
        state: NoLimitHoldemState,
        *,
        actor: str,
        hole_cards: Sequence[str],
        **context: Any,
    ) -> dict[str, Any]:
        if state.street != "preflop":
            return self.reference.action_probabilities(
                state, actor=actor, hole_cards=hole_cards, **context
            )
        trace, replay, preflop_history, _, _ = _semantic_trace(state)
        del trace
        if replay.to_snapshot(include_log=False) != state.to_snapshot(include_log=False):
            raise AssertionError("semantic replay diverged from public game state")
        decision = _preflop_decision(state, actor, preflop_history)
        if not _is_required_sizing_context(decision):
            return self.reference.action_probabilities(
                state, actor=actor, hole_cards=hole_cards, **context
            )
        if len(hole_cards) != 2:
            raise ValueError("Model A requires exactly two acting-player hole cards")
        hand_class = combo_class_ids(cid(hole_cards[0]), cid(hole_cards[1]))
        resolved = self._resolve_sizing(decision, hand_class)
        view = state.legal_view(actor)
        supported = {
            action: float(probability)
            for action, probability in (resolved.get("probabilities") or {}).items()
            if _semantic_legal(action, decision, view)
        }
        probabilities = _normalize(supported)
        return {
            "probabilities": probabilities,
            "semantic_context": decision,
            "node_id": resolved.get("node_id"),
            "support": int(resolved.get("support") or 0),
            "source": "ADMITTED_MODEL_A_V2_EXACT_PRICE",
            "sizing_source": "EXACT_PRICE_ONLY_NO_NEAREST",
        }

    def _posterior_from_history(
        self,
        state: NoLimitHoldemState,
        actor: str,
        trace: Sequence[Mapping[str, Any]],
    ) -> tuple[list[tuple[int, int]], list[float]]:
        combos = list(legal_combos([], []))
        weights = [1.0 / len(combos)] * len(combos)
        current_board: list[str] = []
        for item in trace:
            if str(item.get("player") or "") != actor:
                continue
            decision = item.get("decision") or {}
            semantic = str(item.get("semantic_action") or "")
            if str(item.get("street") or "") == "preflop":
                if _is_required_sizing_context(decision):
                    action = _response_action(semantic)
                    updated = []
                    for combo, weight in zip(combos, weights):
                        hand = combo_class_ids(*combo)
                        resolved = self._resolve_sizing(decision, hand)
                        probability = float(
                            (resolved.get("probabilities") or {}).get(action, 0.0)
                            or 0.0
                        )
                        updated.append(weight * max(1e-12, probability))
                    weights = _normalize_weights(updated)
                else:
                    node = exact_preflop_node(self.reference.preflop_model, decision)
                    if node is None:
                        raise ModelAUnsupportedContext(
                            "missing exact non-sizing preflop Model-A node in prior history"
                        )
                    weights = _normalize_weights(
                        [
                            weight
                            * max(
                                1e-12,
                                _node_action_probability(
                                    node,
                                    self.reference.preflop_model,
                                    combo,
                                    semantic,
                                ),
                            )
                            for combo, weight in zip(combos, weights)
                        ]
                    )
                continue

            board = list(decision.get("board") or [])
            if board != current_board:
                combos, weights = _remove_blockers(combos, weights, board)
                current_board = board
            node = exact_postflop_node(self.reference.postflop_model, decision)
            if node is None:
                raise ModelAUnsupportedContext(
                    "missing exact postflop Model-A node in prior history"
                )
            target = target_frequencies(
                node, decision, self.reference.postflop_model
            )
            actions, matrix = calibrated_action_matrix(
                combos,
                weights,
                decision,
                target,
                self.reference.postflop_model,
            )
            if semantic not in actions:
                raise ModelAUnsupportedContext(
                    f"prior postflop action {semantic} is outside exact-node support"
                )
            idx = actions.index(semantic)
            weights = _normalize_weights(
                [
                    weight * max(1e-12, matrix[row][idx])
                    for row, weight in enumerate(weights)
                ]
            )
        if list(state.board) != current_board:
            combos, weights = _remove_blockers(combos, weights, state.board)
        return combos, weights

    def posterior_support_for_trace(
        self,
        trace: Sequence[Mapping[str, Any]],
        player: str,
    ) -> tuple[list[str], int]:
        node_ids: list[str] = []
        supports: list[int] = []
        for item in trace:
            if str(item.get("player") or "") != player:
                continue
            if str(item.get("street") or "") != "preflop":
                continue
            decision = item.get("decision") or {}
            if _is_required_sizing_context(decision):
                resolved = self._resolve_sizing(decision, None)
                action = _response_action(item.get("semantic_action"))
                if action not in (resolved.get("probabilities") or {}):
                    raise ModelAUnsupportedContext(
                        f"observed sizing response {action} outside v2 support"
                    )
                node_id = str(resolved.get("node_id") or "")
                support = int(resolved.get("support") or 0)
            else:
                node = exact_preflop_node(self.reference.preflop_model, decision)
                if node is None:
                    raise ModelAUnsupportedContext(
                        "missing exact non-sizing preflop support node"
                    )
                node_id = str(node.get("id") or "")
                support = int(
                    (node.get("coverage") or {}).get("population_decisions") or 0
                )
            if not node_id or support <= 0:
                raise ModelAUnsupportedContext("posterior support identity is invalid")
            node_ids.append(node_id)
            supports.append(support)
        return node_ids, min(supports) if supports else 0

    @staticmethod
    def _passive_postflop_fallback(
        state: NoLimitHoldemState,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        legal = list(state.legal_view(actor)["legal_actions"])
        if "CHECK" in legal:
            action = "CHECK"
        elif "CALL" in legal:
            action = "CALL"
        elif "FOLD" in legal:
            action = "FOLD"
        else:
            raise ModelAUnsupportedContext(
                f"no passive postflop closure available for {actor}: {legal}"
            )
        return {
            "action": action,
            "semantic_action": action,
            "target_total_bb": None,
            "incremental_cost_bb": (
                float(state.legal_view(actor)["to_call_bb"]) if action == "CALL" else 0.0
            ),
            "source": "ISSUE367_POSTFLOP_SUPPORT_CLOSURE",
            "support": 0,
            "sizing_source": None,
            "closure_reason": reason,
        }

    def decide(
        self,
        state: NoLimitHoldemState,
        *,
        seed_parts: Sequence[object],
        **context: Any,
    ) -> dict[str, Any]:
        actor = str(context["actor"])
        if state.street != "preflop":
            try:
                return self.reference.decide(
                    state, seed_parts=tuple(seed_parts), **context
                )
            except ModelAUnsupportedContext as exc:
                self.postflop_support_closure[str(exc)] += 1
                return self._passive_postflop_fallback(state, actor, str(exc))

        trace, replay, preflop_history, _, _ = _semantic_trace(state)
        del trace
        if replay.to_snapshot(include_log=False) != state.to_snapshot(include_log=False):
            raise AssertionError("semantic replay diverged from public game state")
        semantic_context = _preflop_decision(state, actor, preflop_history)
        if not _is_required_sizing_context(semantic_context):
            return dict(
                self.non_sizing_reference.decide(
                    state, seed_parts=tuple(seed_parts), **context
                )
            )

        info = self.action_probabilities(state, **context)
        if info.get("source") != "ADMITTED_MODEL_A_V2_EXACT_PRICE":
            raise AssertionError("required VS_ISO context did not bind admitted v2")
        probabilities = dict(info["probabilities"])
        semantic = str(
            weighted_choice(
                list(probabilities),
                list(probabilities.values()),
                *seed_parts,
                "model-a-v2-action",
            )
        )
        view = state.legal_view(actor)
        target = None
        sizing_source = None
        if semantic in {"LIMP", "CALL"}:
            core = "CALL"
        elif semantic in {"BET", "RAISE"}:
            core = "RAISE"
            reference_node = exact_preflop_node(
                self.reference.preflop_model, info["semantic_context"]
            )
            if reference_node is None:
                raise ModelAUnsupportedContext(
                    "v2 selected RAISE but exact active sizing node is unavailable"
                )
            target, sizing_source = _empirical_raise_target(
                reference_node, state, actor
            )
            sizing_source = "ACTIVE_EXACT_NODE_SIZING_ONLY:" + str(sizing_source)
        elif semantic == "JAM":
            core = "RAISE"
            target = float(view["max_raise_to_bb"])
            sizing_source = "JAM_BOUNDARY"
        else:
            core = semantic
        incremental = (
            float(target) - float(view["actor_street_contribution_bb"])
            if core == "RAISE"
            else float(view["to_call_bb"])
            if core == "CALL"
            else 0.0
        )
        return {
            "action": core,
            "semantic_action": semantic,
            "target_total_bb": target,
            "incremental_cost_bb": round(incremental, 9),
            "probabilities": probabilities,
            "node_id": info["node_id"],
            "support": info["support"],
            "source": info["source"],
            "sizing_source": sizing_source,
            "semantic_context": info["semantic_context"],
        }


class Issue367ScientificProvider:
    """Provider API consumed by #357 in SCIENTIFIC mode."""

    def __init__(
        self,
        *,
        hero_hole_cards: Sequence[str],
        expected_candidate_sha256: str = CANDIDATE_SHA256,
        expected_decision: str = VALIDATION_DECISION,
    ) -> None:
        if expected_candidate_sha256 != CANDIDATE_SHA256:
            raise Issue367ProviderError("configured candidate SHA does not match #352")
        if expected_decision != VALIDATION_DECISION:
            raise Issue367ProviderError("configured admission decision does not match #352")
        self.candidate, self.validation = load_admitted_candidate()
        reference, hero_reference, descriptor = load_frozen_reference_policy()
        self.opponent_policy = Issue367OpponentPolicy(self.candidate, reference)
        self.hero_reference = hero_reference
        self.reference_descriptor = descriptor
        self.hero_hole_cards = tuple(str(x) for x in hero_hole_cards)
        self.rollout = ModelAPreflopContinuationRollout(
            opponent_policy=self.opponent_policy,
            hero_hole_cards=self.hero_hole_cards,
            hero_continuation_policy=self.hero_reference,
        )
        source_id = (
            "analysis/model_a_preflop_sizing_v2_validation.json"
            f"#evidence_sha256={VALIDATION_EVIDENCE_SHA256}"
        )
        self.posterior_runtime = ModelAPosteriorRuntime(
            self.opponent_policy,
            population_id=POPULATION_ID,
            model_id=CANDIDATE_ID,
            model_version=CANDIDATE_SHA256,
            source_id=source_id,
        )
        self._posterior_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._posterior_variants: dict[tuple[str, str, str], set[str]] = collections.defaultdict(set)
        self._support_closure_by_alt: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        self._preflop_support_closure_by_alt: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    def metadata(self) -> dict[str, Any]:
        return {
            "provider_kind": "MODEL_A",
            "admission_status": ADMISSION_STATUS,
            "scientific_effect": "SCIENTIFIC_ADMITTED",
            "identity": {
                "population_id": POPULATION_ID,
                "model_id": CANDIDATE_ID,
                "model_version": CANDIDATE_SHA256,
                "source_id": (
                    "issue-352:ADMIT_CANDIDATE:"
                    + VALIDATION_EVIDENCE_SHA256
                ),
            },
            "provenance": {
                "issue": 367,
                "parent_issue": 314,
                "admission_issue": 352,
                "candidate_sha256": CANDIDATE_SHA256,
                "fit_evidence_sha256": FIT_EVIDENCE_SHA256,
                "validation_evidence_sha256": VALIDATION_EVIDENCE_SHA256,
                "validation_decision": VALIDATION_DECISION,
                "active_model_pointer_mutated": False,
                "test_consumed": False,
                "nearest_price": False,
                "hero_continuation": self.reference_descriptor["runtime"]["class"],
            },
        }

    def materialize_world(
        self,
        public_context: Mapping[str, Any],
        decision_id: str,
        sample_index: int,
        seed: int,
    ) -> dict[str, Any]:
        state = NoLimitHoldemState.from_snapshot(public_context["state_snapshot"])
        hero = str(state.next_actor or "")
        if not hero:
            raise Issue367ProviderError("public decision state has no next Hero actor")
        holes = self.rollout._sample_private_cards(state, hero=hero, seed=int(seed))
        board = self.rollout._sample_board(state, holes, seed=int(seed))
        return {
            "decision_id": str(decision_id),
            "sample_index": int(sample_index),
            "seed": int(seed),
            "hero": hero,
            "decision_stack_bb": float(state.stacks_bb[hero]),
            "public_state_fingerprint": str(public_context["public_state_fingerprint"]),
            "state_snapshot": copy.deepcopy(public_context["state_snapshot"]),
            "holes": {player: list(cards) for player, cards in sorted(holes.items())},
            "board": list(board),
            "sample_fingerprint_sha256": _sample_fingerprint(holes, board),
        }

    @staticmethod
    def _apply_alternative(
        state: NoLimitHoldemState,
        hero: str,
        alternative: Mapping[str, Any],
    ) -> None:
        action = str(alternative.get("action") or "").upper()
        if action == "OVERLIMP":
            state.apply_action(hero, "CALL")
            return
        if action == "ISO":
            sizing = alternative.get("target_sizing") or {}
            target = sizing.get("target_total_bb")
            if target is None:
                target = alternative.get("target_total_bb")
            if target is None:
                raise Issue367ProviderError("ISO alternative lacks exact target_total_bb")
            state.apply_action(hero, "RAISE", target_total_bb=float(target))
            return
        if action == "FOLD":
            state.apply_action(hero, "FOLD")
            return
        raise Issue367ProviderError(f"unsupported #367 alternative action {action}")

    def _posterior_after_action(
        self,
        state: NoLimitHoldemState,
        *,
        alternative_id: str,
        player: str,
        response: str,
        sample_index: int,
    ) -> tuple[str, dict[str, Any]]:
        positions = _position_map(state)
        position = str(positions[player]).upper()
        ref_id = f"issue367:{alternative_id}:{position}:{response}"
        record = self.posterior_runtime.posterior_record(
            state,
            player=player,
            moment="AFTER_ACTION",
            hand_id="ISSUE367-KTS-SB-2LIMP",
            step_id=f"{alternative_id}:{position}:{response}",
            public_state_fingerprint=_public_fingerprint(state),
        )
        if record.get("status") != "AVAILABLE":
            raise ModelAUnsupportedContext(
                f"posterior unavailable after {alternative_id} {position} {response}: "
                + str(record.get("reason") or record.get("backoff_reason") or "")
            )
        fingerprint = str(record.get("distribution_fingerprint") or "")
        key = (alternative_id, position, response)
        self._posterior_variants[key].add(fingerprint)
        # #322 compact refs are one stable representative per position/response.
        # Sampling paths can differ before the same response.  We retain the first
        # deterministic sample representative and separately audit every observed
        # distribution fingerprint in the result provenance.
        if key not in self._posterior_cache:
            self._posterior_cache[key] = copy.deepcopy(record)
        return ref_id, copy.deepcopy(self._posterior_cache[key])

    def evaluate_alternative(
        self,
        world: Mapping[str, Any],
        alternative: Mapping[str, Any],
    ) -> dict[str, Any]:
        alt_id = str(alternative.get("id") or "")
        hero = str(world["hero"])
        state = NoLimitHoldemState.from_snapshot(world["state_snapshot"])
        self._apply_alternative(state, hero, alternative)

        holes = {
            player: tuple(cards)
            for player, cards in (world.get("holes") or {}).items()
        }
        board = list(world["board"])
        first_preflop_response_seen: set[str] = set()
        continuers: list[dict[str, Any]] = []
        decision_no = collections.Counter()
        settlement = None
        actions = 0

        for _ in range(self.rollout.max_actions + 20):
            if len(state.live_players) == 1:
                settlement = state.settle_by_fold(net_pot_fn=rake_net)
                break
            actor = state.next_actor
            if actor is not None:
                if actions >= self.rollout.max_actions:
                    raise RolloutUnsupported("continuation exceeded max_actions")
                policy = (
                    self.hero_reference
                    if actor == hero
                    else self.opponent_policy
                )
                seed_parts = (
                    int(world["seed"]),
                    int(world["sample_index"]),
                    alt_id,
                    actor,
                    int(decision_no[actor]),
                    state.street,
                )
                before_street = state.street
                decision = _invoke_policy(
                    policy,
                    NoLimitHoldemState.from_snapshot(state.to_snapshot()),
                    seed_parts=seed_parts,
                    actor=actor,
                    hole_cards=holes[actor],
                )
                closure = decision.get("benchmark_reference_support_closure")
                if (
                    closure
                    and before_street == "preflop"
                    and actor != hero
                ):
                    reason = str(closure.get("reason") or "UNSPECIFIED")
                    self._preflop_support_closure_by_alt[alt_id][reason] += 1
                first_response = (
                    before_street == "preflop"
                    and str(alternative.get("action") or "").upper() == "ISO"
                    and actor != hero
                    and actor not in first_preflop_response_seen
                )
                _apply_policy_decision(state, actor, decision)
                if first_response:
                    first_preflop_response_seen.add(actor)
                    core_action = str(decision.get("action") or "").upper()
                    semantic = str(
                        decision.get("semantic_action") or core_action
                    ).upper()
                    response = None
                    if core_action == "CALL":
                        response = "CALL"
                    elif core_action == "RAISE":
                        response = "JAM" if semantic == "JAM" else "3BET"
                    if response is not None:
                        ref_id, record = self._posterior_after_action(
                            state,
                            alternative_id=alt_id,
                            player=actor,
                            response=response,
                            sample_index=int(world["sample_index"]),
                        )
                        continuers.append(
                            {
                                "position": record["position"],
                                "response": response,
                                "posterior_ref_id": ref_id,
                                "posterior_record": record,
                            }
                        )
                decision_no[actor] += 1
                actions += 1
                continue

            if state.street == "river":
                ranks = {
                    player: best(list(holes[player]) + list(board))
                    for player in state.live_players
                }
                settlement = state.settle_showdown(ranks, net_pot_fn=rake_net)
                break
            if state.street == "preflop":
                next_cards = list(board[:3])
            elif state.street == "flop":
                next_cards = [board[3]]
            elif state.street == "turn":
                next_cards = [board[4]]
            else:
                raise RolloutUnsupported(f"unknown street {state.street!r}")
            state.advance_street(next_cards)
        else:
            raise RolloutUnsupported("continuation failed to terminate")

        if settlement is None:
            raise RolloutUnsupported("continuation terminated without settlement")
        if self.opponent_policy.postflop_support_closure:
            self._support_closure_by_alt[alt_id].update(
                self.opponent_policy.postflop_support_closure
            )
            self.opponent_policy.postflop_support_closure.clear()

        ending = float(state.stacks_bb[hero])
        return {
            "ev_bb": ending - float(world["decision_stack_bb"]),
            "continuers": continuers,
            "terminal": settlement.terminal,
            "rake_bb": float(settlement.rake_bb),
            "actions_after_candidate": actions,
        }

    def audit(self) -> dict[str, Any]:
        variants = {
            "|".join(key): sorted(values)
            for key, values in sorted(self._posterior_variants.items())
        }
        closure = {
            alt: dict(sorted(counter.items()))
            for alt, counter in sorted(self._support_closure_by_alt.items())
        }
        preflop_closure = {
            alt: dict(sorted(counter.items()))
            for alt, counter in sorted(
                self._preflop_support_closure_by_alt.items()
            )
        }
        return {
            "posterior_distribution_variants": variants,
            "preflop_non_sizing_support_closure_by_alternative": preflop_closure,
            "postflop_support_closure_by_alternative": closure,
            "posterior_ref_policy": (
                "FIRST_DETERMINISTIC_SAMPLE_PER_ALTERNATIVE_POSITION_RESPONSE;"
                "ALL_OBSERVED_DISTRIBUTION_FINGERPRINTS_AUDITED"
            ),
            "nearest_price": False,
            "active_model_pointer_mutated": False,
            "test_consumed": False,
        }


__all__ = [
    "Issue367ProviderError",
    "Issue367OpponentPolicy",
    "Issue367ScientificProvider",
    "load_admitted_candidate",
    "CANDIDATE_ID",
    "CANDIDATE_SHA256",
    "VALIDATION_DECISION",
    "FIT_EVIDENCE_SHA256",
    "VALIDATION_EVIDENCE_SHA256",
]
