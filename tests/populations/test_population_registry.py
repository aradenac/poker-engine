#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.populations.registry import (  # noqa: E402
    PopulationRegistryError,
    assert_artifact_compatible,
    load_registry,
    namespace_path,
    require_artifact_role,
    resolve_population,
)


def test_repository_registry_declares_required_populations() -> None:
    registry = load_registry(ROOT)
    populations = registry["populations"]
    assert "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1" in populations
    assert "pokerstars_nlhe_100-200_zoom_play_6max_v1" in populations
    assert "pokerstars_nlhe_250-500_zoom_play_6max_v1" in populations
    assert "pokerstars_nlhe_nl5_zoom_real_eur_6max_v1" in populations
    assert populations["pokerstars_nlhe_100-200_zoom_play_6max_v1"]["data"]["source_unique_hands"] == 23789


def test_namespaces_are_disjoint() -> None:
    registry = load_registry(ROOT)
    seen_runs = set()
    seen_cache = set()
    for population_id in registry["populations"]:
        population = resolve_population(ROOT, population_id)
        run_root = namespace_path(ROOT, population, "runs")
        cache = population["storage"]["cache_namespace"]
        assert run_root not in seen_runs
        assert cache not in seen_cache
        seen_runs.add(run_root)
        seen_cache.add(cache)


def test_scientific_resolution_requires_explicit_population() -> None:
    try:
        resolve_population(ROOT, "")
    except PopulationRegistryError as exc:
        assert "population_id is required" in str(exc)
    else:
        raise AssertionError("missing population_id must fail")


def test_target_does_not_inherit_legacy_promoted_artifacts() -> None:
    target = resolve_population(ROOT, "pokerstars_nlhe_100-200_zoom_play_6max_v1")
    assert target["status"] == "CERTIFIED_DATA_ONLY"
    for role in ("model_a_preflop", "model_a_postflop", "model_b", "hero_strategy", "engine", "pack"):
        assert target["artifacts"][role] is None
    try:
        require_artifact_role(target, "model_a_preflop")
    except PopulationRegistryError as exc:
        assert "has no promoted model_a_preflop" in str(exc)
    else:
        raise AssertionError("target must not silently reuse mixed-format v5")


def test_artifact_population_mismatch_is_rejected() -> None:
    target = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
    assert_artifact_compatible(target, {"population_id": target})
    try:
        assert_artifact_compatible(target, {"population_id": "other-population"})
    except PopulationRegistryError as exc:
        assert "artifact population mismatch" in str(exc)
    else:
        raise AssertionError("cross-population artifact must be rejected")


def test_legacy_unscoped_compatibility_is_explicit_only() -> None:
    legacy = resolve_population(ROOT, "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1")
    assert legacy["compatibility"]["legacy_unscoped_artifacts_allowed"] is True
    assert_artifact_compatible(legacy["population_id"], {}, allow_legacy_unscoped=True)
    try:
        assert_artifact_compatible("pokerstars_nlhe_100-200_zoom_play_6max_v1", {})
    except PopulationRegistryError:
        pass
    else:
        raise AssertionError("new populations require scoped artifact metadata")


def test_registry_rejects_shared_cache_namespace() -> None:
    source = load_registry(ROOT)
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        copied = json.loads(json.dumps(source))
        keys = list(copied["populations"])
        copied["populations"][keys[1]]["storage"]["cache_namespace"] = copied["populations"][keys[0]]["storage"]["cache_namespace"]
        path = root / "training/populations/registry.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(copied), encoding="utf-8")
        try:
            load_registry(root)
        except PopulationRegistryError as exc:
            assert "duplicate cache namespace" in str(exc)
        else:
            raise AssertionError("shared population cache namespace must fail")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"population registry tests: {len(tests)} passed")
