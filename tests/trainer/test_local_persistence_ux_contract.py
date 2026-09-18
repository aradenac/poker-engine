#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / 'site/index.html').read_text(encoding='utf-8')

def main() -> None:
    # Normal persistence is a compact indicator, not a permanent status panel.
    assert 'id="localPersistenceStatus" class="local-persistence-chip busy"' in INDEX
    assert 'id="localPersistenceStatus" class="status"' not in INDEX
    assert 'Données enregistrées dans ce navigateur' in INDEX
    assert 'Les Hand Histories, modèles, préférences et sélections restent sur cet appareil' in INDEX

    # Advanced controls are explicit and collapsed by default.
    assert '<details id="localPersistenceDetails" class="local-persistence-details">' in INDEX
    assert '<details id="localPersistenceDetails" class="local-persistence-details" open' not in INDEX
    assert 'id="localPersistenceRetryBtn"' in INDEX
    assert 'id="localPersistenceClearBtn"' in INDEX

    # Visible state is intentionally simple while technical details live behind Advanced.
    assert 'localPersistenceStatus.textContent=error?"Sauvegarde locale en erreur":busy?"Sauvegarde…":"Sauvegardé localement"' in INDEX
    assert 'if(error&&localPersistenceDetails) localPersistenceDetails.open=true' in INDEX

    # Erase is explicit, confirmed, cancels scheduled writes, clears the store and reloads.
    assert 'async function localDbClearAll()' in INDEX
    assert 'tx.objectStore(LOCAL_STORE).clear()' in INDEX
    erase = INDEX.split('async function clearLocalPersistenceWithConfirmation()',1)[1].split('function currentLocalPrefs()',1)[0]
    assert 'window.confirm(' in erase
    assert 'if(!confirmed)' in erase
    assert 'clearTimeout(state.persistPrefsTimer)' in erase
    assert 'clearTimeout(state.reviewPersistTimer)' in erase
    assert 'clearInterval(state.hhWatchTimer)' in erase
    assert 'await localDbClearAll()' in erase
    assert 'window.location.reload()' in erase

    # Retry performs an actual local write rather than only changing presentation.
    retry = INDEX.split('async function retryLocalPersistence()',1)[1].split('async function clearLocalPersistenceWithConfirmation()',1)[0]
    assert 'await localDbSet("prefs",currentLocalPrefs())' in retry
    assert 'state.persistenceReady=true' in retry

    print('local persistence UX contract checks: OK')

if __name__ == '__main__':
    main()
