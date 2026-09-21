from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class LeakPageContract(unittest.TestCase):
    def test_browser_modules_are_exact_source_copies(self):
        self.assertEqual((ROOT / "src/analytics/leak-analyzer.js").read_bytes(), (ROOT / "site/leak-analyzer.js").read_bytes())
        self.assertEqual((ROOT / "src/analytics/review-score-adapter.js").read_bytes(), (ROOT / "site/review-score-adapter.js").read_bytes())
        self.assertEqual((ROOT / "src/analytics/review-score-adapter.js").read_bytes(), (ROOT / "site/analytics/review-score-adapter.js").read_bytes())

    def test_standalone_page_contract(self):
        html = (ROOT / "site/leaks.html").read_text(encoding="utf-8")
        js = (ROOT / "site/leaks.js").read_text(encoding="utf-8")
        for asset in ("population-packs.js", "hero-ranges.js", "hero-range-migration.js",
                      "hero-strategy-resolver.js", "leak-analyzer.js", "review-score-adapter.js",
                      "leaks.js", "leaks.css"):
            self.assertIn(asset, html)
        self.assertNotIn('src="./trainer.js"', html)
        # The resolver, the shared contextual override helper and the adapter must
        # be wired before the page derives its Review scope/identity.
        for earlier, later in (
            ("hero-ranges.js", "hero-range-migration.js"),
            ("hero-range-migration.js", "hero-strategy-resolver.js"),
            ("hero-strategy-resolver.js", "leaks.js"),
        ):
            self.assertLess(html.index(earlier), html.index(later), (earlier, later))
        for marker in (
            "scopeSelect", "filterPosition", "filterStreet", "filterFamily", "filterPlayed",
            "filterRecommended", "filterSizingError", "filterJam", "filterOverbet",
            "filterSizingMin", "filterSizingMax", "filterFrom", "filterTo", "scopeIdentity",
            "metricTotalLoss", "metricBb100", "leaksBody", "decisionsBody", "diagnosticsBody", "sourcePanel"
        ):
            self.assertIn(marker, html)
        for marker in (
            "PokerRangeEquityOffline", "reviewScores", "hhSources", "PokerPopulationPacks",
            "adaptPersistedReviewData", "scopeKey", "min_played_size_pot_ratio",
            "max_played_size_pot_ratio", "sizing_error", "jam", "overbet",
            "exportReportJSON", "exportReportCSV", "handSource"
        ):
            self.assertIn(marker, js)
        # The Review scope identity is population-bound and comes from the resolver.
        for marker in ("PokerHeroStrategyResolver", "resolveHeroStrategy", "Resolver.identity",
                       "reviewScopeFromResolution", "hero_provenance"):
            self.assertIn(marker, js)
        # #task-a0n: the Review surface consumes the same contextual override
        # helper as the Trainer/header and reports the active/inactive state tied
        # to the resolved context instead of a global presence.
        for marker in ("PokerHeroRangeMigration", "personalOverrideStatus", "personalOverrideStatusFor",
                       "scope.override", "renderScopeIdentity", "scopeIdentity"):
            self.assertIn(marker, js, marker)
        self.assertNotIn("'review-engine'", js)
        self.assertNotIn('"hero-custom"', js)
        self.assertNotIn("hero-custom", js)
        self.assertNotIn("strategy_id:'Custom'", js)
        self.assertNotIn('strategy_id:"Custom"', js)

    def test_statuses_are_explicit(self):
        html = (ROOT / "site/leaks.html").read_text(encoding="utf-8")
        js = (ROOT / "site/leaks.js").read_text(encoding="utf-8")
        self.assertIn("Unsupported / non comparable / within noise", html)
        self.assertIn("UNSUPPORTED", js)
        self.assertIn("NON COMPARABLE", js)
        self.assertIn("WITHIN NOISE", js)

    def test_review_scope_transmits_the_admission_binding(self):
        js = (ROOT / "site/leaks.js").read_text(encoding="utf-8")
        # #task-0jt: the Review scope forwards the complete admission binding
        # (role/hash/provenance/candidate/generation/binding) and the coverage
        # bound, not a bare {status,population_id} token.
        for marker in (
            "heroAdmissionFromProvenance",
            "role:'hero_strategy'",
            "declared_sha256",
            "actual_sha256",
            "source_path",
            "binding_sha256",
            "candidate_id",
            "generation_id",
            "artifact:{",
            "provenance:{",
            "required_context_keys",
            "generation_manifest",
        ):
            self.assertIn(marker, js, marker)
        self.assertNotIn("status:provenance.status,population_id:provenance.population_id", js)
        # The legacy reference is not fabricated into an admissible strategy and
        # is never presented under a "Custom" identity.
        self.assertIn("provenance.candidate_id||null", js)
        self.assertIn("provenance.generation_id||null", js)
        self.assertIn("provenance.binding_sha256||null", js)
        self.assertNotIn("strategy_id:'Custom'", js)
        self.assertNotIn('strategy_id:"Custom"', js)

if __name__ == "__main__":
    unittest.main()
