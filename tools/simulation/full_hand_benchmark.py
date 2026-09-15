#!/usr/bin/env python3
"""Run full-hand multiway scenarios against the #104 retained Model-B reference."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.full_hand_arena import run_full_hand, summarize_results
from tools.simulation.full_hand_scenarios import eligible_table_templates, materialize_full_hand_scenario
from tools.simulation.model_b_public_reference import RetainedPublicModelBPolicy
from tools.simulation.model_b_runtime import hseed, rake_net
from tools.populations.registry import resolve_population
from tools.training.independent_profiles.reveal_aware_ranges import certified_records

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_SCHEMA = "full-hand-model-b-benchmark/v1"
MANIFEST_SCHEMA = "full-hand-arena-scenario-manifest/v1"


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ProfileSource:
    """Profile distribution/assignments used by #104, population-scoped for #105."""

    def __init__(self, document: Mapping[str, Any], *, population_id: str, alias: str) -> None:
        self.profiles = dict(document)
        rows = sorted(self.profiles.get("profiles", []), key=lambda row: int(row["profile"]))
        if not rows:
            raise ValueError("profile source has no profiles")
        self.profile_ids = [int(row["profile"]) for row in rows]
        self.profile_weights = [float(row["appearance_weight"]) for row in rows]
        if sum(max(0.0, value) for value in self.profile_weights) <= 0:
            raise ValueError("profile source has no positive appearance mass")
        self.population_id = str(population_id)
        self.alias = str(alias)

    @classmethod
    def from_path(cls, path: Path, *, population_id: str) -> "ProfileSource":
        path = Path(path)
        document = json.loads(path.read_text(encoding="utf-8"))
        return cls(document, population_id=population_id, alias=f"profiles:{path.as_posix()}")


class PassiveHeroPolicy:
    """Deterministic smoke/reference Hero policy; not a promoted strategy."""

    policy_id = "passive-reference-smoke/v1"

    def decide(self, state, *, seed_parts: Sequence[object], **context: Any) -> dict[str, Any]:
        legal = list(state.legal_view(str(context["actor"]))["legal_actions"])
        if "CHECK" in legal:
            return {"action": "CHECK"}
        if "CALL" in legal:
            return {"action": "CALL"}
        return {"action": "FOLD"}


def build_manifest_from_archives(
    *,
    population_id: str,
    profiles: ProfileSource,
    archives: Sequence[Path],
    certification: Path,
    count: int,
    reps: int,
    master_seed: int,
    start: int = 0,
    split: str = "TRAIN",
    hero: str = "RoiDePiqueNique",
    root: Path = ROOT,
) -> dict[str, Any]:
    if profiles.population_id != population_id:
        raise ValueError(
            f"profile population mismatch: expected {population_id}, got {profiles.population_id}"
        )
    if int(count) < 1 or int(reps) < 1 or int(start) < 0:
        raise ValueError("count/reps must be positive and start non-negative")
    if not archives:
        raise ValueError("explicit certified source archives are required")

    population = resolve_population(root, population_id)
    certified, certification_summary = certified_records(
        [Path(path) for path in archives],
        {str(population["identity"]["stake"])},
        Path(certification),
    )
    allowed_hand_ids = {str(record.hand_id) for record in certified}

    templates, source = eligible_table_templates(
        population_id=population_id,
        hero=hero,
        split=split,
        root=root,
        archives=[Path(path) for path in archives],
    )
    pre_certification_count = len(templates)
    templates = [item for item in templates if str(item["source_hand_id"]) in allowed_hand_ids]
    source = {
        **source,
        "selection_contract": "certified-predeal-table-geometry-only",
        "pre_certification_eligible_templates": pre_certification_count,
        "certified_eligible_templates": len(templates),
        "certification": certification_summary,
    }
    ordered = sorted(
        templates,
        key=lambda item: (
            hseed(population_id, master_seed, "table-template", item["source_hand_id"]),
            item["source_hand_id"],
        ),
    )
    selected = ordered[int(start) : int(start) + int(count)]
    if len(selected) != int(count):
        raise ValueError(
            f"requested {count} independent templates from offset {start}, only {len(selected)} available"
        )

    player_profiles = profiles.profiles.get("player_profile", {})
    scenarios = [
        materialize_full_hand_scenario(
            template,
            profile_ids=profiles.profile_ids,
            profile_weights=profiles.profile_weights,
            player_profiles=player_profiles,
            master_seed=int(master_seed),
            rep=rep,
        )
        for template in selected
        for rep in range(int(reps))
    ]
    fingerprint = _sha256_json([
        {
            "scenario_id": item["scenario_id"],
            "cluster_id": item["cluster_id"],
            "hole_cards": item["hole_cards"],
            "board": item["board"],
            "profiles": item["profiles"],
            "component_seeds": item["component_seeds"],
        }
        for item in scenarios
    ])
    return {
        "schema": MANIFEST_SCHEMA,
        "population_id": population_id,
        "split": split.upper(),
        "hero": hero,
        "master_seed": int(master_seed),
        "requested_hands": int(count),
        "selected_independent_templates": len(selected),
        "reps": int(reps),
        "start": int(start),
        "eligible_templates": len(templates),
        "source": source,
        "model_b_profiles": {
            "alias": profiles.alias,
            "profile_ids": profiles.profile_ids,
        },
        "randomness_contract": {
            "deck": "pre-sampled independently of all policies",
            "opponent_actions": "separate deterministic seed namespace",
            "hero_policy": "separate deterministic seed namespace",
            "monte_carlo": "separate deterministic seed namespace",
        },
        "scenario_fingerprint_sha256": fingerprint,
        "scenarios": scenarios,
    }


def run_benchmark(
    manifest: Mapping[str, Any],
    *,
    opponent_policy: RetainedPublicModelBPolicy,
    hero_policy,
) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"unsupported scenario manifest schema: {manifest.get('schema')!r}")
    if manifest.get("population_id") != opponent_policy.population_id:
        raise ValueError(
            f"Model B population mismatch: scenarios={manifest.get('population_id')!r}, "
            f"policy={opponent_policy.population_id!r}"
        )
    results = [
        run_full_hand(
            scenario,
            hero_policy=hero_policy,
            opponent_policy=opponent_policy,
            net_pot_fn=rake_net,
        )
        for scenario in manifest.get("scenarios", [])
    ]
    if not results:
        raise ValueError("benchmark manifest contains no scenarios")
    policy_id = getattr(hero_policy, "policy_id", type(hero_policy).__name__)
    return {
        "schema": BENCHMARK_SCHEMA,
        "population_id": manifest["population_id"],
        "scenario_manifest": {
            key: value for key, value in manifest.items() if key != "scenarios"
        },
        "model_b": opponent_policy.identity(),
        "hero_policy": {
            "id": str(policy_id),
            "promotion_status": "SMOKE_REFERENCE_NOT_PROMOTED"
            if isinstance(hero_policy, PassiveHeroPolicy)
            else "CALLER_SUPPLIED",
        },
        "rake_contract": "tools.simulation.model_b_runtime.rake_net historical 5.5% capped at 13.925 BB",
        "summary": summarize_results(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--reference-behavior", type=Path, required=True)
    parser.add_argument(
        "--issue-104-result",
        type=Path,
        default=ROOT / "training/runs/20260915_model_b_card_aware_v1/RESULT.json",
    )
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--certification", type=Path, required=True)
    parser.add_argument("--split", default="TRAIN")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--hero", default="RoiDePiqueNique")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    policy = RetainedPublicModelBPolicy.from_paths(args.reference_behavior, args.issue_104_result)
    if policy.population_id != args.population:
        raise ValueError(
            f"#104 retained reference population {policy.population_id!r} != requested {args.population!r}"
        )
    profiles = ProfileSource.from_path(args.profiles, population_id=args.population)
    manifest = build_manifest_from_archives(
        population_id=args.population,
        profiles=profiles,
        archives=args.archive,
        certification=args.certification,
        count=args.count,
        reps=args.reps,
        master_seed=args.seed,
        start=args.start,
        split=args.split,
        hero=args.hero,
        root=ROOT,
    )
    report = run_benchmark(
        manifest,
        opponent_policy=policy,
        hero_policy=PassiveHeroPolicy(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "model_b": report["model_b"],
        "summary": report["summary"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
