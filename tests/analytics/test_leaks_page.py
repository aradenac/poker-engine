from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class LeakPageContract(unittest.TestCase):
    def test_browser_modules_are_exact_source_copies(self):
        self.assertEqual((ROOT / "src/analytics/leak-analyzer.js").read_bytes(), (ROOT / "site/leak-analyzer.js").read_bytes())
        self.assertEqual((ROOT / "src/analytics/review-score-adapter.js").read_bytes(), (ROOT / "site/review-score-adapter.js").read_bytes())

    def test_standalone_page_contract(self):
        html = (ROOT / "site/leaks.html").read_text(encoding="utf-8")
        js = (ROOT / "site/leaks.js").read_text(encoding="utf-8")
        for asset in ("population-packs.js", "leak-analyzer.js", "review-score-adapter.js", "leaks.js", "leaks.css"):
            self.assertIn(asset, html)
        self.assertNotIn('src="./trainer.js"', html)
        for marker in (
            "scopeSelect", "filterPosition", "filterStreet", "filterFamily", "filterPlayed",
            "filterRecommended", "filterSizingError", "filterJam", "filterOverbet",
            "filterSizingMin", "filterSizingMax", "filterFrom", "filterTo",
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

    def test_statuses_are_explicit(self):
        html = (ROOT / "site/leaks.html").read_text(encoding="utf-8")
        js = (ROOT / "site/leaks.js").read_text(encoding="utf-8")
        self.assertIn("Unsupported / non comparable / within noise", html)
        self.assertIn("UNSUPPORTED", js)
        self.assertIn("NON COMPARABLE", js)
        self.assertIn("WITHIN NOISE", js)

if __name__ == "__main__":
    unittest.main()
