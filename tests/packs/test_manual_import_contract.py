from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ManualImportContractTests(unittest.TestCase):
    def test_standalone_surface_and_contract_exist(self):
        html = (ROOT / "site/manual-import.html").read_text(encoding="utf-8")
        js = (ROOT / "site/manual-import.js").read_text(encoding="utf-8")
        css = (ROOT / "site/manual-import.css").read_text(encoding="utf-8")

        self.assertIn("Import manuel", html)
        self.assertIn("Revenir au pack actif", html)
        self.assertIn("./population-packs.js", html)
        self.assertIn("./manual-import.js", html)
        self.assertIn("poker-manual-override/v1", js)
        self.assertIn("MANUAL_OVERRIDE", js)
        self.assertIn("NON_STANDARD", js)
        self.assertIn("RESTORE_ACTIVE_PACK", js)
        self.assertIn("hero_ranges", js)
        self.assertIn("model_a_preflop", js)
        self.assertIn("model_a_postflop", js)
        self.assertIn(".badge.override", css)

    def test_manual_overrides_use_non_pack_storage_and_atomic_transaction(self):
        manual = (ROOT / "site/manual-import.js").read_text(encoding="utf-8")
        packs = (ROOT / "site/population-packs.js").read_text(encoding="utf-8")

        shared = (ROOT / "site/pack-identity.js").read_text(encoding="utf-8")
        self.assertIn('DB_NAME="PokerRangeEquityOffline"', manual)
        self.assertIn('const DB_NAME=Identity.STORAGE_CONTRACT.db_name', packs)
        self.assertIn('db_name:"poker-population-packs-v1"', shared)
        self.assertNotIn('PokerRangeEquityOffline', shared)
        self.assertIn('db.transaction(STORE,"readwrite")', manual)
        self.assertIn("Transaction override annulée", manual)
        self.assertIn("Activation atomique non vérifiée", manual)

    def test_pack_switches_are_fail_closed_while_override_is_active(self):
        packs = (ROOT / "site/population-packs.js").read_text(encoding="utf-8")
        self.assertIn("assertManualOverrideAllowsTarget", packs)
        self.assertIn("RESTORE_ACTIVE_PACK", packs)
        self.assertGreaterEqual(
            packs.count("await assertManualOverrideAllowsTarget(target)"),
            2,
            "activate and rollback must both guard against stale manual overrides",
        )

    def test_restore_is_all_roles_and_pack_policy_controls_hero_preservation(self):
        manual = (ROOT / "site/manual-import.js").read_text(encoding="utf-8")
        self.assertIn('const del=["populationModelSource","postflopModelSource"]', manual)
        self.assertIn('if(!preserveHero)del.push("rangeSource")', manual)
        self.assertIn("preserve_hero_manual_ranges", manual)
        self.assertIn("preserve_manual_ranges", manual)
        self.assertIn("RESTORE_ACTIVE_PACK incomplet", manual)


if __name__ == "__main__":
    unittest.main()
