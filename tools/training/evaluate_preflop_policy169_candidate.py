#!/usr/bin/env python3
"""Evaluate the frozen #101 preflop policy169 candidate without TEST leakage.

The evaluator reuses the v83/v5 structural matcher implemented by
``evaluate_preflop_topology_candidate.py`` and scores the exact probability
family consumed by the browser:

* all rows: combo-weighted ``population_model.policy169_q_b64``
  P(action|context) when available, otherwise the node action marginal;
* revealed rows: exact policy169 P(action|hand_class,context).

VALIDATION is paired by ``hand_id`` and is the only selection split. TEST is
refused unless an immutable VALIDATION report explicitly authorizes it and pins
the exact candidate digest. This tool never mutates a model or registry.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.training.evaluate_preflop_topology_candidate import by_actor, find_closest  # noqa: E402
from tools.training.preflop_policy169 import (  # noqa: E402
    decode_policy169,
    hand_weights,
    policy_marginals,
    policy_probability,
)

SCHEMA = "poker-preflop-policy169-evaluation/v1"
EPS = 1e-12


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return obj


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def bootstrap_hand_mean(rows: list[dict[str, Any]], *, samples: int, seed: int) -> dict[str, Any]:
    grouped: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        grouped[str(row["hand_id"])].append(float(row["delta_nll"]))
    hands = sorted(grouped)
    if not hands:
        return {"hands": 0, "samples": samples, "seed": seed, "mean": 0.0, "ci95": [0.0, 0.0], "probability_candidate_better": 0.0}
    rng = random.Random(seed)
    draws = []
    for _ in range(samples):
        total = 0.0
        count = 0
        for _slot in hands:
            hid = hands[rng.randrange(len(hands))]
            vals = grouped[hid]
            total += sum(vals)
            count += len(vals)
        draws.append(total / max(1, count))
    mean = sum(float(row["delta_nll"]) for row in rows) / len(rows)
    return {
        "hands": len(hands),
        "samples": samples,
        "seed": seed,
        "mean": mean,
        "ci95": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "probability_candidate_better": sum(x < 0 for x in draws) / len(draws),
    }


class RuntimePolicyScorer:
    def __init__(self, model: dict[str, Any]):
        self.nodes = list(model.get("nodes") or [])
        self.index = by_actor(self.nodes)
        root = model.get("hand_grid") or {}
        if isinstance(root, dict):
            self.fallback_grid = list(root.get("classes") or [])
            self.root_meta = root.get("meta") or {}
        else:
            self.fallback_grid = list(root or [])
            self.root_meta = {}
        self._marginals: dict[str, dict[str, float]] = {}
        self._has_policy: dict[str, bool] = {}

    @staticmethod
    def _node_id(node: dict[str, Any]) -> str:
        return str(node.get("id") or node.get("canonical_key") or "")

    @staticmethod
    def _runtime_policy_object(node: dict[str, Any]) -> Any:
        return ((node.get("population_model") or {}).get("policy169_q_b64"))

    def _policy_marginal(self, node: dict[str, Any], action: str) -> float | None:
        nid = self._node_id(node)
        if nid not in self._has_policy:
            self._has_policy[nid] = isinstance(self._runtime_policy_object(node), dict)
        if not self._has_policy[nid]:
            return None
        if nid not in self._marginals:
            policy = decode_policy169(node, self.fallback_grid)
            grid = list(policy)
            weights = hand_weights(grid, self.root_meta)
            actions = list(next(iter(policy.values())).keys()) if policy else []
            self._marginals[nid] = policy_marginals(policy, actions=actions, weights=weights)
        return self._marginals[nid].get(action)

    def predict(self, row: dict[str, Any], *, conditional_hand: bool) -> dict[str, Any]:
        match = find_closest(self.index, row)
        if not match:
            return {"probability": EPS, "node_id": None, "exact": False, "policy169": False}
        node = match["node"]
        action = str(row.get("action") or "").upper()
        has_policy = isinstance(self._runtime_policy_object(node), dict)
        if conditional_hand:
            hand = row.get("known_hand_class")
            if not hand or not has_policy:
                return {"probability": None, "node_id": self._node_id(node), "exact": bool(match["exact"]), "policy169": has_policy}
            p = policy_probability(node, str(hand), action, self.fallback_grid)
        else:
            p = self._policy_marginal(node, action)
            if p is None:
                p = float(((node.get("population_model") or {}).get("frequencies") or {}).get(action, 0.0) or 0.0)
        return {
            "probability": max(EPS, min(1.0, float(p))),
            "node_id": self._node_id(node),
            "exact": bool(match["exact"]),
            "policy169": has_policy,
        }


def iter_scored_rows(decisions: Path, split: str) -> list[dict[str, Any]]:
    rows = []
    with decisions.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("split") != split or row.get("street") != "preflop" or row.get("is_hero"):
                continue
            rows.append(row)
    return rows


def score_models(rows: list[dict[str, Any]], prior: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    ps = RuntimePolicyScorer(prior)
    cs = RuntimePolicyScorer(candidate)
    all_detail = []
    known_detail = []
    prior_nll = candidate_nll = 0.0
    known_prior_nll = known_candidate_nll = 0.0
    affected_rows = affected_known = candidate_policy_rows = 0
    exact_prior = exact_candidate = 0

    for row in rows:
        pp = ps.predict(row, conditional_hand=False)
        cp = cs.predict(row, conditional_hand=False)
        pn, cn = -math.log(pp["probability"]), -math.log(cp["probability"])
        prior_nll += pn; candidate_nll += cn
        changed = pp["node_id"] != cp["node_id"] or abs(pp["probability"] - cp["probability"]) > 1e-15
        affected_rows += int(changed)
        candidate_policy_rows += int(cp["policy169"])
        exact_prior += int(pp["exact"]); exact_candidate += int(cp["exact"])
        all_detail.append({"hand_id": str(row["hand_id"]), "delta_nll": cn - pn, "changed": changed})

        if row.get("known_hand_class"):
            pk = ps.predict(row, conditional_hand=True)
            ck = cs.predict(row, conditional_hand=True)
            if pk["probability"] is not None and ck["probability"] is not None:
                pkn, ckn = -math.log(pk["probability"]), -math.log(ck["probability"])
                known_prior_nll += pkn; known_candidate_nll += ckn
                kchanged = pk["node_id"] != ck["node_id"] or abs(pk["probability"] - ck["probability"]) > 1e-15
                affected_known += int(kchanged)
                known_detail.append({"hand_id": str(row["hand_id"]), "delta_nll": ckn - pkn, "changed": kchanged})

    n = len(all_detail)
    nk = len(known_detail)
    return {
        "all_rows": {
            "rows": n,
            "prior_logloss": prior_nll / max(1, n),
            "candidate_logloss": candidate_nll / max(1, n),
            "delta_candidate_minus_prior": (candidate_nll - prior_nll) / max(1, n),
            "affected_rows": affected_rows,
            "candidate_policy169_rows": candidate_policy_rows,
            "prior_exact_matches": exact_prior,
            "candidate_exact_matches": exact_candidate,
            "detail": all_detail,
        },
        "revealed_hand_rows": {
            "rows": nk,
            "hands": len({x["hand_id"] for x in known_detail}),
            "prior_logloss": known_prior_nll / max(1, nk),
            "candidate_logloss": known_candidate_nll / max(1, nk),
            "delta_candidate_minus_prior": (known_candidate_nll - known_prior_nll) / max(1, nk),
            "affected_rows": affected_known,
            "detail": known_detail,
        },
    }


def compact_metric(metric: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in metric.items() if k != "detail"} | {"paired_bootstrap": bootstrap}


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    split = "VALIDATION" if args.phase == "validation" else "TEST"
    protocol = load_json(args.protocol)
    if protocol.get("schema") != "poker-preflop-policy169-experiment/v1":
        raise SystemExit("unexpected #101 protocol schema")
    if protocol.get("status") != "FROZEN_BEFORE_EXPERIMENT":
        raise SystemExit("#101 protocol must be frozen before evaluation")

    candidate_sha = sha256_file(args.candidate)
    validation_selection = None
    if split == "TEST":
        if not args.validation_selection:
            raise SystemExit("TEST requires --validation-selection")
        validation_selection = load_json(args.validation_selection)
        if validation_selection.get("phase") != "VALIDATION" or validation_selection.get("test_authorized") is not True:
            raise SystemExit("protected TEST is not authorized by VALIDATION")
        pinned = str(((validation_selection.get("inputs") or {}).get("candidate") or {}).get("sha256") or "")
        if pinned != candidate_sha:
            raise SystemExit(f"candidate changed after VALIDATION: {candidate_sha} != {pinned}")

    prior = load_json(args.prior)
    candidate = load_json(args.candidate)
    rows = iter_scored_rows(args.decisions, split)
    scored = score_models(rows, prior, candidate)
    cfg = protocol.get("evaluation") or {}
    samples = int(cfg.get("bootstrap_samples") or 5000)
    seed = int(cfg.get("bootstrap_seed") or 20260915) + (1 if split == "TEST" else 0)
    all_boot = bootstrap_hand_mean(scored["all_rows"]["detail"], samples=samples, seed=seed)
    known_boot = bootstrap_hand_mean(scored["revealed_hand_rows"]["detail"], samples=samples, seed=seed + 1000)
    all_metric = compact_metric(scored["all_rows"], all_boot)
    known_metric = compact_metric(scored["revealed_hand_rows"], known_boot)

    minimum_rows = int(((cfg.get("required_hand_conditioned") or {}).get("minimum_validation_rows")) or 100)
    minimum_hands = int(((cfg.get("required_hand_conditioned") or {}).get("minimum_validation_hands")) or 50)
    support_ok = known_metric["rows"] >= minimum_rows and known_metric["hands"] >= minimum_hands
    affected_ok = all_metric["affected_rows"] > 0 and known_metric["affected_rows"] > 0
    dual_ci_ok = float(all_boot["ci95"][1]) <= 0.0 and float(known_boot["ci95"][1]) <= 0.0
    accepted = support_ok and affected_ok and dual_ci_ok

    if split == "VALIDATION":
        outcome = "VALIDATION_FINALIST" if accepted else "RETAIN_PRIOR"
        test_authorized = bool(accepted)
    else:
        outcome = "FINALIST_CONFIRMED" if accepted else "RETAIN_PRIOR"
        test_authorized = None

    result = {
        "schema": SCHEMA,
        "phase": split,
        "issue": 101,
        "protocol": {"path": str(args.protocol), "sha256": sha256_file(args.protocol)},
        "selection_split": "VALIDATION",
        "test_used": split == "TEST",
        "test_used_for_selection": False,
        "production_effect": "NONE",
        "inputs": {
            "prior": {"path": str(args.prior), "sha256": sha256_file(args.prior)},
            "candidate": {"path": str(args.candidate), "sha256": candidate_sha},
            "decisions": {"path": str(args.decisions), "sha256": sha256_file(args.decisions)},
        },
        "runtime_contract": {
            "matcher": "tools/training/evaluate_preflop_topology_candidate.py v83/v5 parity",
            "all_rows_probability": "combo-weighted population_model.policy169_q_b64 P(action|context), marginal fallback only when policy169 unavailable",
            "revealed_probability": "exact runtime policy169 P(action|known_hand_class,context)",
            "hero_rows": "EXCLUDED",
            "future_information": "FORBIDDEN",
        },
        "metrics": {"all_rows": all_metric, "revealed_hand_rows": known_metric},
        "gate": {
            "minimum_revealed_rows": minimum_rows,
            "minimum_revealed_hands": minimum_hands,
            "support_ok": support_ok,
            "affected_support_ok": affected_ok,
            "dual_ci95_upper_le_zero": dual_ci_ok,
        },
        "outcome": outcome,
        "test_authorized": test_authorized,
        "reason": (
            "both frozen VALIDATION metrics satisfy affected-support, minimum-support and paired-hand CI95 gates"
            if accepted else
            "frozen dual gate not established; retain prior and keep protected TEST locked"
        ) if split == "VALIDATION" else (
            "locked TEST confirms the frozen VALIDATION finalist on both metrics"
            if accepted else
            "locked TEST does not confirm the frozen VALIDATION finalist"
        ),
    }
    if validation_selection is not None:
        result["validation_selection"] = {
            "path": str(args.validation_selection),
            "sha256": sha256_file(args.validation_selection),
        }
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("validation", "test"), default="validation")
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--prior", required=True, type=Path)
    p.add_argument("--candidate", required=True, type=Path)
    p.add_argument("--decisions", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--validation-selection", type=Path)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    compact = {
        "phase": result["phase"],
        "outcome": result["outcome"],
        "test_authorized": result.get("test_authorized"),
        "gate": result["gate"],
        "metrics": result["metrics"],
    }
    print(json.dumps(compact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
