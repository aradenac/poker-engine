#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / 'site/index.html').read_text(encoding='utf-8')


def main() -> None:
    # Both primary dialogs expose accessible dialog semantics and a fallback focus target.
    assert 'class="population-modal" role="dialog" aria-modal="true" aria-labelledby="populationRangeModalTitle" tabindex="-1"' in INDEX
    assert 'class="action-verdict-detail-modal" role="dialog" aria-modal="true" aria-labelledby="actionDetailModalTitle" tabindex="-1"' in INDEX

    # One shared keyboard/focus contract handles initial focus, trap, Escape and restoration.
    for marker in (
        'const modalFocusOrigins=new WeakMap()',
        'function modalFocusableElements(backdrop)',
        'function openAccessibleModal(backdrop',
        'function closeAccessibleModal(backdrop)',
        'function handleAccessibleModalKeydown(e)',
        'document.addEventListener("keydown",handleAccessibleModalKeydown)',
        'origin.focus({preventScroll:true})',
    ):
        assert marker in INDEX, marker
    assert 'if(e.key!=="Tab")return;' in INDEX
    assert 'if(e.key==="Escape")' in INDEX
    assert 'e.shiftKey' in INDEX

    # Each modal uses the common focus lifecycle rather than hand-rolled visibility only.
    assert 'openAccessibleModal(actionDetailModal,{initialFocus:()=>actionDetailModalClose})' in INDEX
    assert 'closeAccessibleModal(actionDetailModal)' in INDEX
    assert 'openAccessibleModal(populationRangeModal,{initialFocus:()=>populationRangeModalClose})' in INDEX
    assert 'closeAccessibleModal(populationRangeModal)' in INDEX

    # Keyboard focus is visibly distinguishable, and current replay state is semantic, not color-only.
    assert ':focus-visible' in INDEX
    assert 'aria-current="step"' in INDEX

    # Critical dense desktop labels get an explicit >=10 px floor; mobile is not part of this issue.
    desktop = INDEX.split('@media(min-width:901px){', 1)[1].split('}', 1)[0]
    for selector in ('.decision-primary-card .k', '.population-modal-cell .freq', '.street-event .action-badge'):
        assert selector in desktop, selector
    assert 'font-size:10px' in desktop

    print('desktop accessibility contract checks: OK')


if __name__ == '__main__':
    main()
