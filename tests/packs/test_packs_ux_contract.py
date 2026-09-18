from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "site/packs.html").read_text(encoding="utf-8")
APP = (ROOT / "site/packs-app.js").read_text(encoding="utf-8")


class PacksUxContractTests(unittest.TestCase):
    def test_primary_surface_uses_user_facing_update_language(self) -> None:
        self.assertIn("<h1>Population & mises à jour</h1>", HTML)
        self.assertIn('id="activeHeading">Version active</span>', HTML)
        self.assertIn("Revenir à la version précédente", HTML)
        self.assertIn("Rechercher les mises à jour", HTML)
        self.assertNotIn("Catalogue same-origin", HTML)
        self.assertNotIn("IndexedDB", HTML)
        self.assertNotIn("SHA-256", HTML)

    def test_technical_controls_remain_available_but_collapsed(self) -> None:
        self.assertIn('<details class="panel advanced">', HTML)
        self.assertIn("Import, export et détails techniques", HTML)
        self.assertIn('id="importZip"', HTML)
        self.assertIn('id="exportBtn"', HTML)
        self.assertIn("Garanties d’activation", HTML)
        self.assertIn('class="technical-details"', APP)
        for label in ("Révision runtime", "Composants", "Provenance", "Compatibilité", "Activation"):
            self.assertIn(label, APP)

    def test_statuses_and_actions_are_explicit(self) -> None:
        for label in (
            "Version active",
            "Utiliser cette version",
            "Mettre à jour",
            "Installer",
            "mise à jour disponible",
            "recommandée",
            "installée",
            "incompatible",
        ):
            self.assertIn(label, APP)


if __name__ == "__main__":
    unittest.main()
