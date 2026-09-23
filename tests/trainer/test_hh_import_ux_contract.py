#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def main() -> None:
    section = INDEX.split('<section id="historiesSection"', 1)[1].split('</section>', 1)[0]
    advanced = section.split('<details class="hh-import-advanced">', 1)[1].split('</details>', 1)[0]

    # The normal path needs one obvious import action and one optional watcher.
    assert 'for="hhFileInput">Importer mes mains</label>' in section
    assert 'id="hhWatchBtn"' in section
    assert section.index('id="hhWatchBtn"') < section.index('<details class="hh-import-advanced">')
    assert 'Par défaut, un nouvel import remplace les mains actuellement chargées.' in section

    # Secondary choices and debug/maintenance actions stay available but collapsed.
    for element_id in ('hhImportMode', 'hhClearBtn', 'hhWatchStopBtn', 'hhBenchmarkExportBtn'):
        assert f'id="{element_id}"' in advanced, element_id
    assert 'id="hhModeBtn"' not in section
    assert 'Mode Hand History' not in section
    assert '<details class="hh-import-advanced" open' not in section

    # Existing semantics are preserved: replace is still the safe default and add remains explicit.
    assert 'hhImportMode:"replace"' in INDEX
    assert 'state.hhImportMode=hhImportModeSelect.value==="add"?"add":"replace"' in INDEX
    assert 'mergeMode==="add" ? mergeSourceSnapshots' in INDEX
    assert 'persistHHSources(sourceRecords)' in INDEX
    assert 'startHHWatch' in INDEX and 'readWatchedFiles' in INDEX

    # First-level feedback reports recognisable files, parsed hands, errors and freshness.
    assert 'function hhImportSummaryText' in INDEX
    assert 'fichier${files.length>1?"s":""} sélectionné' in INDEX
    assert 'erreur${errorCount>1?"s":""} de lecture/parsing' in INDEX
    assert 'mise à jour ${time}' in INDEX
    assert 'recognizedFiles' in INDEX
    assert 'parseErrors' in INDEX
    assert 'readErrors' in INDEX
    assert 'import en cours…' in INDEX
    assert 'Import impossible : aucun fichier sélectionné n’a pu être lu.' in INDEX

    # Selecting a hand still enters HH mode automatically, so moving the explicit toggle is safe.
    select = INDEX.split('function selectHistoryHandById', 1)[1].split('function updateHistoryUi', 1)[0]
    assert 'if(!state.hhMode){saveManualSnapshot();state.hhMode=true;}' in select

    # #394 T3: the import and the hand selection belong to the Review view, which
    # opens the Replayer on selection. The Replayer "Retour" returns to that same
    # view with the selection preserved — a pure view change: no document scroll,
    # no re-scheduled background review scoring.
    review_view = INDEX.split('<div id="mainPage"', 1)[1].split('<div id="strategyPage"', 1)[0]
    assert 'id="historiesSection"' in review_view and 'id="handSelectionSection"' in review_view
    assert 'id="hhFileInput"' in review_view and 'id="hhWatchBtn"' in review_view
    assert 'state.selectedHand?.id===h.id?" selected":""' in INDEX
    back = INDEX[INDEX.index('function returnToHandsPage'):INDEX.index('function leaveHistoryMode')]
    assert 'activateAppSubview("inbox")' in back
    assert 'scrollIntoView' not in back
    assert 'scheduleBackgroundReviewScoring' not in back

    print('HH import UX contract checks: OK')


if __name__ == '__main__':
    main()
