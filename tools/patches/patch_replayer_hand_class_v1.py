#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "site" / "index.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    anchor = '''function replaySeatHtml(player,step,hand){\n'''
    helper = '''function replayHandClass(cards){\n  if(!Array.isArray(cards)||cards.length!==2||cards.some(c=>typeof c!=="string"||c.length<2)) return "";\n  const ranks="23456789TJQKA";\n  const a=String(cards[0]),b=String(cards[1]);\n  const ar=a[0].toUpperCase(),br=b[0].toUpperCase();\n  const ai=ranks.indexOf(ar),bi=ranks.indexOf(br);\n  if(ai<0||bi<0)return "";\n  if(ar===br)return ar+br;\n  const hi=ai>bi?ar:br,lo=ai>bi?br:ar;\n  return hi+lo+(a.slice(1).toLowerCase()===b.slice(1).toLowerCase()?"s":"o");\n}\n\nfunction replaySeatHtml(player,step,hand){\n'''
    text = replace_once(text, anchor, helper, "hand-class helper")

    old_cards = '''  let cards=st.cards;\n  if(!cards && player.knownCards?.length===2 && step?.label==="Showdown") cards=player.knownCards;\n  const cardsHtml=(cards&&cards.length===2?cards:[null,null]).map(c=>`<div class="hole-card${c===null?" empty":""}">${c===null?"🂠":cardHtml(c)}</div>`).join("");\n'''
    new_cards = '''  let cards=st.cards;\n  if(!cards && player.knownCards?.length===2 && step?.label==="Showdown") cards=player.knownCards;\n  const handClass=replayHandClass(cards);\n  const cardsHtml=(cards&&cards.length===2?cards:[null,null]).map(c=>`<div class="hole-card${c===null?" empty":""}">${c===null?"🂠":cardHtml(c)}</div>`).join("");\n'''
    text = replace_once(text, old_cards, new_cards, "visible-card hand class")

    old_badges = '''  const badges=[\n    player.name===hand.heroName?'<span class="seat-badge hero">Hero</span>':'',\n    st.folded?'<span class="seat-badge folded">Fold</span>':''\n  ].join("");\n'''
    new_badges = '''  const badges=[\n    player.name===hand.heroName?'<span class="seat-badge hero">Hero</span>':'',\n    st.folded?'<span class="seat-badge folded">Fold</span>':'',\n    handClass?`<span class="seat-badge known hand-class" data-hand-class="${escapeHtml(handClass)}" title="Classe de main visible">${escapeHtml(handClass)}</span>`:''\n  ].join("");\n'''
    text = replace_once(text, old_badges, new_badges, "hand-class badge")

    PATH.write_text(text, encoding="utf-8")
    print("patched replayer visible hand classes issue #73")


if __name__ == "__main__":
    main()
