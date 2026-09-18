#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    # HH mode is no longer a user concept.
    assert 'id="hhModeBtn"' not in INDEX
    assert 'Mode Hand History' not in INDEX
    assert 'enterHistoryMode' not in INDEX

    # Explicit hand selection activates the internal Review context and opens Replayer.
    select = block('function selectHistoryHandById', 'function updateHistoryUi')
    assert 'if(!state.hhMode){saveManualSnapshot();state.hhMode=true;}' in select
    assert 'state.selectedHand=hand' in select
    assert 'loadSelectedHistoryHand(true)' in select
    assert 'openReplayerPage({scrollTop:true})' in select

    # Leaving Review restores the independent manual Equity Lab but does not destroy the selection.
    back = block('function returnToHandsPage', 'function leaveHistoryMode')
    assert 'if(state.hhMode) leaveHistoryMode();' in back
    leave = block('function leaveHistoryMode', 'function loadSelectedHistoryHand')
    assert 'state.hhMode=false' in leave
    assert 'restoreManualSnapshot()' in leave
    assert 'state.selectedHand=null' not in leave

    # Hand list keeps the remembered selection visible even outside Review.
    assert 'state.selectedHand?.id===h.id?" selected":""' in INDEX

    # Local restore derives Review from the persisted view, not a legacy user toggle.
    restore = block('async function restoreLocalState', 'renderSlots();')
    assert 'prefs?.appView==="replayer"&&state.selectedHand' in restore
    assert 'prefs?.hhMode&&state.selectedHand' not in restore
    assert 'state.hhMode=false' in restore

    # The internal flag remains available to scientific reconstruction paths.
    assert 'state.replaySteps=makeReplaySteps(state.hhMode?state.selectedHand:null)' in INDEX
    assert 'if(!state.hhMode||!state.selectedHand||!state.replaySteps.length)return' in INDEX

    # Manual interaction can still exit Review independently of imported HH data.
    clear = INDEX.split('$("clearCards").addEventListener', 1)[1].split('function escapeHtml', 1)[0]
    assert 'if(state.hhMode) leaveHistoryMode();' in clear

    print('implicit Review context checks: OK')


if __name__ == '__main__':
    main()
