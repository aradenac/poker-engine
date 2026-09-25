#!/usr/bin/env python3
"""Spot Lab view contract (#394 T4).

The formerly stacked manual tools are moved — never duplicated — into the Spot
Lab view and grouped into sub-views. This static contract pins:

- the Spot Lab shell exposes the four manual-tool panes as tabs/sous-vues;
- `opponentsSection` / `cardsSection` / `rangeDisplaySection` / `equitySection`
  each exist exactly once and live inside the Spot Lab shell, never in Review;
- the advanced sources/models surface (`#rangesSection`) stays hidden and is not
  a sub-view pane, so no tab can unveil it;
- a sub-view is scoped to its owning view shell, so the DOM move cannot blank a
  neighbouring view;
- the floating equity widget obeys the documented visibility rule
  (`docs/spotlab-view.md`): Spot Lab + Replayer only.

It is a static/representation contract only and changes no equity computation.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
DOC = (ROOT / "docs/spotlab-view.md").read_text(encoding="utf-8")


def shell(name: str, end: str) -> str:
    return INDEX.split(f'id="{name}"', 1)[1].split(f'id="{end}"', 1)[0]


MANUAL_PANES = {
    "opponentsSection": "spotlab-situation",
    "cardsSection": "spotlab-board",
    "rangeDisplaySection": "spotlab-range",
    "equitySection": "spotlab-equity",
}


def main() -> None:
    spotlab = shell("spotlabPage", "mainPage")
    review = shell("mainPage", "strategyPage")

    # The Spot Lab shell owns a tablist whose thumbnails select the manual panes.
    assert 'data-view-shell="spotlab"' in INDEX
    assert '<div class="app-subviews" role="tablist" aria-label="Sous-vues du Spot Lab">' in spotlab
    for pane, tab in MANUAL_PANES.items():
        assert f'data-app-subview="{tab}"' in spotlab, tab
        assert f'data-app-subview-panel="{tab}"' in spotlab, pane

    # Every manual pane is a single, uniquely identified node inside Spot Lab.
    for pane, tab in MANUAL_PANES.items():
        occurrences = len(re.findall(rf'id="{pane}"', INDEX))
        assert occurrences == 1, (pane, occurrences)
        assert f'id="{pane}"' in spotlab, pane
        assert f'id="{pane}"' not in review, pane
        assert f'id="{pane}" class="panel wide app-subview-panel" data-app-subview-panel="{tab}"' in spotlab, (pane, tab)

    # Method/trials selectors stay inside the opponents pane.
    opponents_pane = spotlab.split('id="opponentsSection"', 1)[1].split("</section>", 1)[0]
    assert 'id="methodSelect"' in opponents_pane
    assert 'id="trialsSelect"' in opponents_pane

    # The 169 matrix and its edition controls stay inside the Ranges pane.
    range_pane = spotlab.split('id="rangeDisplaySection"', 1)[1].split("</section>", 1)[0]
    assert 'id="matrix"' in range_pane
    assert 'id="rangeEditionBtn"' in range_pane
    # The tab id that selects the Ranges pane is contractual too: the desktop
    # smoke (#394 T1) mounts the pane by a real click on `#spotlabRangeTab`
    # before hit-testing `#rangeDisplaySection` and `#matrix`, so the id has to
    # exist exactly once inside the Spot Lab shell, wired to the pane it mounts.
    assert 'id="spotlabRangeTab"' in spotlab
    assert INDEX.count('id="spotlabRangeTab"') == 1
    assert 'aria-controls="rangeDisplaySection"' in spotlab
    assert 'aria-labelledby="spotlabRangeTab"' in spotlab
    # The manual Hero/board picker stays inside the Board pane.
    board_pane = spotlab.split('id="cardsSection"', 1)[1].split("</section>", 1)[0]
    for control in ('id="heroSlots"', 'id="boardSlots"', 'id="deck"', 'id="streetPicker"'):
        assert control in board_pane, control

    # Advanced sources/models remain hidden and are NOT a sub-view pane.
    assert 'id="rangesSection" class="panel wide" hidden aria-hidden="true" data-legacy-import-surface="advanced-only"' in spotlab
    assert 'data-app-subview-panel' not in spotlab.split('id="rangesSection"', 1)[1].split("</section>", 1)[0]

    # The move must not drag a manual tool into the Review shell.
    for pane in MANUAL_PANES:
        assert f'id="{pane}"' not in review, pane
    for stale in ('id="methodSelect"', 'id="trialsSelect"'):
        assert stale not in review, stale

    # Sub-view activation is scoped to the owning view shell (no cross-view leak).
    assert 'function activateAppSubview(name){' in INDEX
    assert 'return (node&&node.closest("[data-view-shell]"))||document;' in INDEX
    activate = INDEX.split("function activateAppSubview(name){", 1)[1].split("function activateAppSubviewForTarget", 1)[0]
    assert "const scope=appSubviewScopeFor(tab);" in activate
    assert "appSubviewPanels(scope).forEach" in activate
    # The pane query is only ever issued through the scoped helper: no other call
    # site may hide panes document-wide.
    assert INDEX.count('querySelectorAll("[data-app-subview-panel]")') == 1
    assert 'return Array.from(root.querySelectorAll("[data-app-subview-panel]"));' in INDEX

    # Spot Lab is independent of an imported hand: its manual path is the
    # non-history branch, and its own equity is what the floating widget shows.
    assert 'if(!state.hhMode){state.mainEquity=null;renderFloatingEquity();}' in INDEX
    assert 'if(!state.hhMode) floatingEquity.classList.add("pending");' in INDEX
    assert 'addOpponentBtn.disabled=state.hhMode||!state.ranges.length||state.opponents.length>=5;' in INDEX

    # Floating-equity visibility rule (documented) — Spot Lab + Replayer only.
    assert 'body[data-app-view="spotlab"] #floatingEquity,' in INDEX
    assert 'body[data-app-view="replayer"] #floatingEquity{display:block}' in INDEX
    assert "#floatingEquity{\n    display:none;" in INDEX
    # ...and the rule is documented, with the manual-tool mapping and the ids.
    assert "Floating-equity visibility rule" in DOC
    assert 'body[data-app-view="spotlab"] #floatingEquity,' in DOC
    assert "exactly once" in DOC
    assert "methodSelect" in DOC and "trialsSelect" in DOC
    assert "manual-import.html" in DOC

    # The <901px rendering is documented: the sub-view pattern is global (only
    # the 100dvh shell is desktop-only), so a Spot Lab pane is never unreachable
    # below 901px. The full mobile inventory is versioned in the shell document.
    assert "## 6. Rendu <901px" in DOC
    assert "is **global**" in DOC
    assert "activateAppSubview(name)" in DOC
    assert "docs/ux-desktop-view-shell.md" in DOC
    assert "no unreachable pane" in DOC or "no pane without a tab" in DOC

    print("spot lab sub-views contract checks: OK")


if __name__ == "__main__":
    main()
