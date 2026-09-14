#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"pattern not found in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise RuntimeError(f"pattern is not unique in {path}: count={text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_model_b_runtime() -> None:
    path = ROOT / "tools/simulation/model_b_runtime.py"
    replace_once(
        path,
        '    def __init__(self, model_dir: Path, alias: str = "independent_model_b_v2") -> None:\n        self.model_dir = Path(model_dir)\n        self.alias = alias\n',
        '    def __init__(self, model_dir: Path, alias: str = "independent_model_b_v2", population_id: str | None = None) -> None:\n        self.model_dir = Path(model_dir)\n        self.alias = alias\n        self.population_id = population_id\n',
    )
    replace_once(
        path,
        '''    @classmethod\n    def from_registry(cls, root: Path | None = None, registry_path: Path | None = None) -> "ModelBEnvironment":\n        root = Path(root or ROOT)\n        registry_path = Path(registry_path or (root / "training/registry.json"))\n        registry = json.loads(registry_path.read_text(encoding="utf-8"))\n        pointer = registry.get("promoted_independent_model")\n        if not pointer:\n            raise ValueError("training registry has no promoted_independent_model")\n        return cls(root / pointer["model_dir"], alias=pointer["alias"])\n''',
        '''    @classmethod\n    def from_population(cls, population_id: str, root: Path | None = None) -> "ModelBEnvironment":\n        from tools.populations.registry import require_artifact_role, resolve_population\n\n        root = Path(root or ROOT)\n        population = resolve_population(root, population_id)\n        model_dir = root / require_artifact_role(population, "model_b")\n        alias = str(population["artifacts"].get("model_b_alias") or f"model_b:{population_id}")\n        return cls(model_dir, alias=alias, population_id=population_id)\n\n    @classmethod\n    def from_registry(\n        cls,\n        root: Path | None = None,\n        registry_path: Path | None = None,\n        *,\n        population_id: str | None = None,\n    ) -> "ModelBEnvironment":\n        if registry_path is not None:\n            raise ValueError("legacy registry_path selection is disabled; use from_population(population_id, root)")\n        if not population_id:\n            raise ValueError("population_id is required; implicit training/registry.json Model B selection is disabled")\n        return cls.from_population(population_id, root)\n''',
    )


def patch_scenarios() -> None:
    path = ROOT / "tools/simulation/scenarios.py"
    replace_once(
        path,
        '''    population = resolve_population(root, population_id)\n    base, source_meta = eligible_base_scenarios(\n''',
        '''    population = resolve_population(root, population_id)\n    if env.population_id != population_id:\n        raise ValueError(\n            f"Model B population mismatch: expected {population_id}, got {env.population_id!r}"\n        )\n    base, source_meta = eligible_base_scenarios(\n''',
    )
    replace_once(path, '    profile = env.sample_profile(master_seed, hand_id, rep, "profile")\n', '    profile = env.sample_profile(base["population_id"], master_seed, hand_id, rep, "profile")\n')
    replace_once(
        path,
        '''        base["flop"],\n        master_seed,\n        hand_id,\n        rep,\n        "opponent-cards",\n''',
        '''        base["flop"],\n        base["population_id"],\n        master_seed,\n        hand_id,\n        rep,\n        "opponent-cards",\n''',
    )
    replace_once(
        path,
        '''    runout = deterministic_runout(\n        base["hero_cards"], base["flop"], opponent_cards, master_seed, hand_id, rep\n    )\n''',
        '''    runout = deterministic_runout(\n        base["hero_cards"], base["flop"], opponent_cards,\n        base["population_id"], master_seed, hand_id, rep\n    )\n''',
    )
    replace_once(
        path,
        '        "environment_seed": hseed(master_seed, hand_id, rep, "environment"),\n',
        '        "environment_seed": hseed(base["population_id"], master_seed, hand_id, rep, "environment"),\n',
    )


def patch_sequential_arena() -> None:
    path = ROOT / "tools/simulation/sequential_postflop.py"
    replace_once(
        path,
        'sys.path.insert(0, str(ROOT))\n\nfrom tools.simulation.model_b_runtime import (  # noqa: E402\n',
        'sys.path.insert(0, str(ROOT))\n\nfrom tools.populations.registry import namespace_path, require_artifact_role, resolve_population  # noqa: E402\nfrom tools.simulation.model_b_runtime import (  # noqa: E402\n',
    )
    replace_once(
        path,
        '''def default_paths(root: Path) -> dict[str, Path]:\n    registry = json.loads((root / "training/registry.json").read_text(encoding="utf-8"))\n    return {\n        "engine": root / "site/index.html",\n        "preflop": root / registry["promoted_model"]["preflop"],\n        "postflop": root / registry["promoted_model"]["postflop"],\n    }\n''',
        '''def default_paths(root: Path, population_id: str) -> dict[str, Path | str]:\n    population = resolve_population(root, population_id)\n    return {\n        "engine": root / require_artifact_role(population, "engine"),\n        "preflop": root / require_artifact_role(population, "model_a_preflop"),\n        "postflop": root / require_artifact_role(population, "model_a_postflop"),\n        "model_b": root / require_artifact_role(population, "model_b"),\n        "cache_namespace": str(population["storage"]["cache_namespace"]),\n    }\n''',
    )
    replace_once(
        path,
        '''def load_or_build_manifest(args, env: ModelBEnvironment) -> dict:\n    if args.scenario_manifest:\n        manifest = json.loads(Path(args.scenario_manifest).read_text(encoding="utf-8"))\n        if manifest.get("model_b", {}).get("artifact_sha256") != env.artifact_fingerprints():\n            raise ValueError("scenario manifest Model B fingerprints do not match selected environment")\n        return manifest\n    return build_scenario_manifest(\n        env=env,\n        count=args.n,\n        reps=args.reps,\n        master_seed=args.seed,\n        start=args.start,\n        split=args.split,\n        hero=args.hero,\n        root=ROOT,\n    )\n''',
        '''def load_or_build_manifest(args, env: ModelBEnvironment) -> dict:\n    population = resolve_population(ROOT, args.population)\n    if env.population_id != args.population:\n        raise ValueError(\n            f"Model B population mismatch: expected {args.population}, got {env.population_id!r}"\n        )\n    if args.scenario_manifest:\n        manifest = json.loads(Path(args.scenario_manifest).read_text(encoding="utf-8"))\n        if manifest.get("population_id") != args.population:\n            raise ValueError(\n                f"scenario manifest population mismatch: expected {args.population}, got {manifest.get('population_id')!r}"\n            )\n        if manifest.get("cache_namespace") != population["storage"]["cache_namespace"]:\n            raise ValueError("scenario manifest cache namespace does not match selected population")\n        if manifest.get("model_b", {}).get("artifact_sha256") != env.artifact_fingerprints():\n            raise ValueError("scenario manifest Model B fingerprints do not match selected environment")\n        return manifest\n    return build_scenario_manifest(\n        population_id=args.population,\n        env=env,\n        count=args.n,\n        reps=args.reps,\n        master_seed=args.seed,\n        start=args.start,\n        split=args.split,\n        hero=args.hero,\n        root=ROOT,\n    )\n''',
    )
    replace_once(
        path,
        '''async def run(args) -> dict:\n    env = (ModelBEnvironment(Path(args.model_b_dir), alias="candidate")\n           if args.model_b_dir else ModelBEnvironment.from_registry(ROOT))\n    manifest = load_or_build_manifest(args, env)\n''',
        '''async def run(args) -> dict:\n    defaults = default_paths(ROOT, args.population)\n    if args.model_b_dir:\n        if not args.model_b_population:\n            raise ValueError("--model-b-population is required with --model-b-dir")\n        if args.model_b_population != args.population:\n            raise ValueError(\n                f"explicit Model B population mismatch: arena={args.population} model_b={args.model_b_population}"\n            )\n        env = ModelBEnvironment(\n            Path(args.model_b_dir), alias="candidate", population_id=args.model_b_population\n        )\n    else:\n        env = ModelBEnvironment.from_population(args.population, ROOT)\n    manifest = load_or_build_manifest(args, env)\n''',
    )
    replace_once(path, '    defaults = default_paths(ROOT)\n    engine = Path(args.engine or defaults["engine"])\n', '    engine = Path(args.engine or defaults["engine"])\n')
    replace_once(
        path,
        '    metadata = {\n        "engine": {"path": engine.relative_to(ROOT).as_posix() if engine.is_relative_to(ROOT) else engine.as_posix(), "sha256": sha256_file(engine)},\n',
        '    metadata = {\n        "population_id": args.population,\n        "cache_namespace": defaults["cache_namespace"],\n        "engine": {"path": engine.relative_to(ROOT).as_posix() if engine.is_relative_to(ROOT) else engine.as_posix(), "sha256": sha256_file(engine)},\n',
    )
    replace_once(
        path,
        '''def parse_args() -> argparse.Namespace:\n    defaults = default_paths(ROOT)\n    parser = argparse.ArgumentParser(description=__doc__)\n''',
        '''def parse_args() -> argparse.Namespace:\n    parser = argparse.ArgumentParser(description=__doc__)\n    parser.add_argument("--population", required=True, help="explicit population id from training/populations/registry.json")\n''',
    )
    replace_once(path, '    parser.add_argument("--engine", default=defaults["engine"].as_posix())\n', '    parser.add_argument("--engine", default="")\n')
    replace_once(path, '    parser.add_argument("--preflop-model", default=defaults["preflop"].as_posix())\n', '    parser.add_argument("--preflop-model", default="")\n')
    replace_once(path, '    parser.add_argument("--postflop-model", default=defaults["postflop"].as_posix())\n', '    parser.add_argument("--postflop-model", default="")\n')
    replace_once(
        path,
        '    parser.add_argument("--model-b-dir", default="", help="explicit independent candidate model directory; does not modify promoted pointers")\n',
        '    parser.add_argument("--model-b-dir", default="", help="explicit independent candidate model directory; does not modify promoted pointers")\n    parser.add_argument("--model-b-population", default="", help="population binding for an explicit Model B candidate")\n',
    )
    replace_once(
        path,
        '''    parser.add_argument("--out", default="artifacts/sequential_arena_v2.json")\n    return parser.parse_args()\n''',
        '''    parser.add_argument("--out", default="")\n    args = parser.parse_args()\n    if not args.out:\n        population = resolve_population(ROOT, args.population)\n        args.out = (namespace_path(ROOT, population, "runs") / "manual" / "sequential_arena_v2.json").as_posix()\n    return args\n''',
    )


def patch_tests() -> None:
    runtime = ROOT / "tests/simulation/test_model_b_runtime.py"
    replace_once(runtime, 'ROOT = Path(__file__).resolve().parents[2]\nsys.path.insert(0, str(ROOT))\n', f'ROOT = Path(__file__).resolve().parents[2]\nLEGACY = "{LEGACY}"\nsys.path.insert(0, str(ROOT))\n')
    replace_once(runtime, '        cls.env = ModelBEnvironment.from_registry(ROOT)\n', '        cls.env = ModelBEnvironment.from_population(LEGACY, ROOT)\n')
    replace_once(runtime, '        self.assertEqual(self.env.alias, "independent_model_b_v2")\n', '        self.assertEqual(self.env.alias, "independent_model_b_v2")\n        self.assertEqual(self.env.population_id, LEGACY)\n')
    replace_once(
        runtime,
        '    def test_action_probabilities_are_legal_and_normalized(self):\n',
        '''    def test_implicit_global_registry_selection_is_rejected(self):\n        with self.assertRaisesRegex(ValueError, "population_id is required"):\n            ModelBEnvironment.from_registry(ROOT)\n\n    def test_action_probabilities_are_legal_and_normalized(self):\n''',
    )

    scenarios = ROOT / "tests/simulation/test_scenarios.py"
    replace_once(scenarios, 'ROOT = Path(__file__).resolve().parents[2]\nsys.path.insert(0, str(ROOT))\n', f'ROOT = Path(__file__).resolve().parents[2]\nLEGACY = "{LEGACY}"\nsys.path.insert(0, str(ROOT))\n')
    replace_once(scenarios, '        cls.env = ModelBEnvironment.from_registry(ROOT)\n', '        cls.env = ModelBEnvironment.from_population(LEGACY, ROOT)\n')
    replace_once(scenarios, '        cls.a = build_scenario_manifest(\n            env=cls.env,\n', '        cls.a = build_scenario_manifest(\n            population_id=LEGACY,\n            env=cls.env,\n')
    replace_once(scenarios, '        cls.b = build_scenario_manifest(\n            env=cls.env,\n', '        cls.b = build_scenario_manifest(\n            population_id=LEGACY,\n            env=cls.env,\n')
    replace_once(
        scenarios,
        '        self.assertEqual(self.a["split"], "TEST")\n',
        '        self.assertEqual(self.a["split"], "TEST")\n        self.assertEqual(self.a["population_id"], LEGACY)\n        self.assertEqual(self.a["cache_namespace"], LEGACY)\n',
    )
    replace_once(
        scenarios,
        '    def test_cards_are_unique(self):\n',
        '''    def test_model_b_population_mismatch_is_rejected(self):\n        wrong = ModelBEnvironment(self.env.model_dir, alias="fixture", population_id="other_population")\n        with self.assertRaisesRegex(ValueError, "Model B population mismatch"):\n            build_scenario_manifest(\n                population_id=LEGACY, env=wrong, count=1, reps=1, master_seed=1, split="TEST", root=ROOT\n            )\n\n    def test_cards_are_unique(self):\n''',
    )


def patch_registry() -> None:
    path = ROOT / "training/populations/registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    legacy = data["populations"][LEGACY]
    legacy["artifacts"]["model_b_alias"] = "independent_model_b_v2"
    legacy["artifacts"]["engine"] = "user/releases/poker_range_equity_offline_multiway_v83.html"
    legacy["artifacts"]["engine_version"] = "v83"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def patch_workflow() -> None:
    path = ROOT / ".github/workflows/sequential-arena.yml"
    text = path.read_text(encoding="utf-8")
    if "LEGACY_POPULATION:" not in text:
        text = text.replace('permissions:\n  contents: read\n', f'permissions:\n  contents: read\n\nenv:\n  LEGACY_POPULATION: {LEGACY}\n', 1)
    text = text.replace("      - 'training/registry.json'\n", "      - 'training/registry.json'\n      - 'training/populations/**'\n      - 'tools/populations/**'\n      - 'tests/populations/**'\n")
    text = text.replace(
        'run: python3 -m py_compile tools/simulation/*.py tools/sequential_postflop_population_sim_v4.py tools/evaluate_promotion_gates.py tests/test_promotion_gates.py',
        'run: python3 -m py_compile tools/simulation/*.py tools/populations/*.py tools/sequential_postflop_population_sim_v4.py tools/evaluate_promotion_gates.py tests/populations/*.py tests/test_promotion_gates.py',
    )
    text = text.replace('      - name: Model B runtime tests\n        run: python3 tests/simulation/test_model_b_runtime.py\n', '      - name: Population registry and Model B runtime tests\n        run: |\n          python3 tests/populations/test_population_registry.py\n          python3 tests/simulation/test_model_b_runtime.py\n')
    text = text.replace(
        '          python3 -m tools.simulation.sequential_postflop \\\n            --generate-only',
        '          python3 -m tools.simulation.sequential_postflop \\\n            --population "$LEGACY_POPULATION" --generate-only',
    )
    text = text.replace(
        '          python3 -m tools.simulation.sequential_postflop \\\n            --n 1',
        '          python3 -m tools.simulation.sequential_postflop \\\n            --population "$LEGACY_POPULATION" --n 1',
    )
    text = text.replace(
        '          python3 tools/sequential_postflop_population_sim_v4.py \\\n            --scenario-manifest',
        '          python3 tools/sequential_postflop_population_sim_v4.py \\\n            --population "$LEGACY_POPULATION" --scenario-manifest',
    )
    text = text.replace(
        '          python3 -m tools.simulation.sequential_postflop \\\n            --scenario-manifest',
        '          python3 -m tools.simulation.sequential_postflop \\\n            --population "$LEGACY_POPULATION" --scenario-manifest',
    )
    text = text.replace(
        '          python3 -m tools.simulation.baseline_runner \\\n            --n ',
        '          python3 -m tools.simulation.baseline_runner \\\n            --population "$LEGACY_POPULATION" --n ',
    )
    text = text.replace("          assert a['schema']=='sequential-arena-scenario-manifest/v1'\n", "          assert a['schema']=='sequential-arena-scenario-manifest/v2'\n          assert a['population_id']==os.environ['LEGACY_POPULATION']\n")
    text = text.replace('          import json\n          a=json.load', '          import json, os\n          a=json.load', 1)
    text = text.replace("          assert d['schema']=='sequential-independent-arena/v2'\n", "          assert d['schema']=='sequential-independent-arena/v2'\n          assert d['metadata']['population_id']==os.environ['LEGACY_POPULATION']\n", 1)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    patch_model_b_runtime()
    patch_scenarios()
    patch_sequential_arena()
    patch_tests()
    patch_registry()
    patch_workflow()
    print("issue95 population isolation refactor applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
