#!/usr/bin/env python3
"""#424 T6 - Smoke Review : parite site + non-regression filtres/pagination.

Verification statique (aucun navigateur, aucun serveur), dans le style des
contrats `*_ui_contract.py` : on lit les octets servis de `site/index.html` et
des miroirs Review, et on confirme

  * la parite octet-a-octet entre les sources d'edition `src/analytics/*` et les
    modules servis `site/analytics/*` (un miroir desynchronise casse ici) ;
  * que le panneau « vue avancee » ajoute en T4 est present et correctement
    reference dans la coque servie : ordre des `<script>`, garde par item,
    cablage du toggle, panneau replie par defaut et CSS `:not([hidden])` ;
  * que les filtres/pagination du Review restent cables comme #395/#424 les a
    laisses : pager borne, codes de tri persistes, filtre de resultat et remise
    a la page 1 a chaque changement de premier niveau.

La non-vacuite est rejouee en memoire : chaque mutation des octets servis doit
faire echouer la meme verification, donc le smoke ne peut pas passer sur un garde
plus faible (panneau ouvert par defaut, panneau non garde par `hybrid`, tag de
script retire, pager supprime).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Modules Review dont la source d'edition et le miroir servi doivent rester
# identiques (la vue avancee T4 vit dans `review-confidence-formatter.js`,
# consomme la projection `hybrid` du `review-score-adapter.js` et est peinte par
# `review-inbox.js`).
PAIRS = (
    ("src/analytics/analysis-state.js", "site/analytics/analysis-state.js"),
    ("src/analytics/leak-analyzer.js", "site/analytics/leak-analyzer.js"),
    ("src/analytics/review-score-adapter.js", "site/analytics/review-score-adapter.js"),
    ("src/analytics/review-confidence-formatter.js", "site/analytics/review-confidence-formatter.js"),
    ("src/analytics/review-inbox.js", "site/analytics/review-inbox.js"),
    ("src/analytics/review-dashboard.js", "site/analytics/review-dashboard.js"),
)

# Ordre de chargement attendu des modules Review dans la coque servie.
SCRIPT_ORDER = (
    '<script src="./analytics/analysis-state.js"></script>',
    '<script src="./analytics/review-score-adapter.js"></script>',
    '<script src="./analytics/review-confidence-formatter.js"></script>',
    '<script src="./analytics/review-inbox.js"></script>',
    '<script src="./analytics/review-dashboard.js"></script>',
)

# Fonctions dediees de la vue avancee : presentes au gabarit servi.
ADVANCED_DECLARATIONS = (
    "function reviewInboxAdvancedFormatter(",
    "function reviewInboxAdvancedProvenance(",
    "function reviewInboxAdvancedView(",
    "function reviewInboxAdvancedModelLabel(",
    "function reviewInboxAdvancedOodLabel(",
    "function reviewInboxAdvancedField(",
    "function reviewInboxAdvancedPanel(",
    "function toggleReviewInboxAdvanced(",
)

# Les valeurs formatees viennent du miroir de confiance : aucune n'est fabriquee
# dans la coque.
ADVANCED_CONSUMPTION = (
    "Formatter.formatSupportStateLabel(hybrid.support_state)",
    "Formatter.formatConfidenceLevel(hybrid.confidence_level)",
    "Formatter.formatEvDisplay(hybrid)",
    "Formatter.formatAbstentionReason(hybrid)",
    "Formatter.formatTooCloseNotice(hybrid)",
    "Formatter.formatAdvancedProvenance(item?.hybrid||null)",
)

# Câblage de la vue avancee dans la rangee : garde par item, panneau replie par
# defaut, toggle dans la cellule statut, panneau ajoute a la rangee.
ADVANCED_WIRING = (
    "if(item.hybrid){",
    "const advanced=reviewInboxAdvancedPanel(item,h.id);",
    'advancedToggle.type="button";advancedToggle.className="review-inbox-advanced-toggle";',
    'advancedToggle.setAttribute("aria-controls",advanced.id);',
    'advancedToggle.setAttribute("aria-expanded",String(reviewInboxAdvancedIsOpen(h.id)));',
    'advancedToggle.addEventListener("click",()=>toggleReviewInboxAdvanced(h.id,advancedToggle,advanced));',
    "status.append(advancedToggle);",
    "row.append(advanced);",
    "panel.hidden=!reviewInboxAdvancedIsOpen(handId);",
)

# Le CSS ne neutralise jamais l'attribut `hidden` : le `display:grid` n'est
# declare que sur l'etat deplie, donc la rangee simple ne reserve aucune hauteur.
ADVANCED_CSS = (
    ".review-inbox-advanced{grid-column:1/-1;",
    ".review-inbox-advanced:not([hidden]){display:grid;",
    '.review-inbox-advanced-toggle[aria-expanded="true"]',
    ".review-inbox-status:has(.review-inbox-advanced-toggle){flex-wrap:wrap}",
)

# Non-regression filtres/pagination du Review (#395/#424).
FILTERS_PAGINATION = (
    'id="reviewResultFilter"',
    'id="hhListPager"',
    'id="hhPagePrev"',
    'id="hhPageNext"',
    'id="hhPageInfo"',
    'class="app-list-pager-info" role="status" aria-live="polite"',
    "const REVIEW_INBOX_PAGE_SIZE_MIN=10;",
    "const REVIEW_INBOX_PAGE_SIZE_MAX=15;",
    "const REVIEW_INBOX_PAGE_SIZE_DEFAULT=REVIEW_INBOX_PAGE_SIZE_MIN;",
    "function updateReviewInboxPager(",
    "const REVIEW_INBOX_SORT_CODES=[",
    'const REVIEW_INBOX_DEFAULT_SORT="recent_desc";',
    "state.reviewInboxPage=0;",
    "state.hhSort=normalizeReviewInboxSortCode(hhSortSelect.value);",
)

# Mutations en memoire : chacune doit faire echouer `check`, sinon le smoke
# passerait sur un garde trop faible. Le jeton doit etre present une seule fois.
MUTATIONS = {
    # un module de la vue avancee retire de la coque -> ordre/presence casse
    "drop-formatter-script": (
        '<script src="./analytics/review-confidence-formatter.js"></script>',
        "",
    ),
    # la vue avancee n'est plus gardee par la projection hybride
    "ungated-advanced": ("if(item.hybrid){", "if(true){"),
    # le panneau est peint ouvert au lieu d'etre replie par defaut
    "default-open": (
        "panel.hidden=!reviewInboxAdvancedIsOpen(handId);",
        "panel.hidden=false;",
    ),
    # le pager de l'inbox disparait
    "drop-pager": ('id="hhListPager"', ""),
}


def check(index_text: str) -> None:
    """Assert the served shell still carries the reviewed wiring.

    Raises AssertionError (never a bare lookup error) on any drift so the
    mutation replay can treat "raises" and "passes" as the two states to test.
    """

    def present(token: str, label: str | None = None) -> None:
        assert token in index_text, label or token

    # 1. Parite de chargement : les modules Review sont presents et charges dans
    #    un ordre qui laisse la vue avancee disponible avant son consommateur.
    for tag in SCRIPT_ORDER:
        present(tag, f"missing review script tag: {tag}")
    positions = [index_text.index(tag) for tag in SCRIPT_ORDER]
    assert positions == sorted(positions), "review modules must keep their load order"

    # 2. Le miroir de confiance expose le formateur consomme par la coque.
    present("window.PokerReviewConfidenceFormatter")

    # 3. La vue avancee est peinte par des fonctions dediees qui ne lisent que les
    #    sorties formatees (aucun recalcul local).
    for declared in ADVANCED_DECLARATIONS:
        present(declared)
    for consumed in ADVANCED_CONSUMPTION:
        present(consumed)

    # 4. Câblage par item : garde `hybrid`, toggle dans la cellule statut,
    #    panneau replie par defaut, panneau ajoute a la rangee.
    for token in ADVANCED_WIRING:
        present(token)

    # 5. Le CSS respecte l'attribut `hidden` (panneau replie = aucune hauteur).
    for token in ADVANCED_CSS:
        present(token)

    # 6. Non-regression filtres/pagination du Review.
    for token in FILTERS_PAGINATION:
        present(token)


def main() -> None:
    # La parite octet-a-octet entre source d'edition et miroir servi : un miroir
    # desynchronise fait echouer le smoke avant meme la lecture de la coque.
    for source, runtime in PAIRS:
        source_text = (ROOT / source).read_text(encoding="utf-8")
        runtime_text = (ROOT / runtime).read_text(encoding="utf-8")
        assert runtime_text == source_text, f"mirror drift: {source} != {runtime}"

    index_text = (ROOT / "site/index.html").read_text(encoding="utf-8")
    check(index_text)

    # Non-vacuite : chaque mutation doit casser la meme verification.
    for name, (token, replacement) in MUTATIONS.items():
        assert index_text.count(token) == 1, f"mutation token must be unique: {name}"
        mutated = index_text.replace(token, replacement)
        try:
            check(mutated)
        except AssertionError:
            continue
        raise AssertionError(f"the {name} mutation must fail the smoke harness")

    print("review advanced-view smoke checks: OK")


if __name__ == "__main__":
    sys.exit(main())
