#!/usr/bin/env python3
"""Make Hero compliance consume real replayer card IDs and honor editor deep links.

Issue #140 follow-up to #98. The replayer stores hole cards as integer IDs 0..51,
while the first compliance adapter accepted only text cards. The Hero editor also
ignored its query string. This patch is marker-based and idempotent.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPLAYER = ROOT / "site" / "hero-compliance-replayer.js"
EDITOR = ROOT / "site" / "hero-ranges-app.js"

OLD_CARD_PARTS = '''  function cardParts(card){
    const s=String(card||'').trim();
    if(s.length<2)return null;
    const rank=s[0].toUpperCase(),suit=SUITS[s[1].toLowerCase?.()||s[1]]||SUITS[s[1]];
    if(!RANKS.includes(rank)||!suit)return null;
    return {rank,suit};
  }
'''
NEW_CARD_PARTS = '''  function cardParts(card){
    const raw=String(card??'').trim(),numeric=Number(card);
    if((typeof card==='number'||/^\\d+$/.test(raw))&&Number.isInteger(numeric)&&numeric>=0&&numeric<52){
      return {rank:RANKS[numeric%13],suit:'shdc'[(numeric/13)|0]};
    }
    const s=raw;
    if(s.length<2)return null;
    const rank=s[0].toUpperCase(),suit=SUITS[s[1].toLowerCase?.()||s[1]]||SUITS[s[1]];
    if(!RANKS.includes(rank)||!suit)return null;
    return {rank,suit};
  }
'''

OLD_EDITOR_END = 'initOptions();renderAll();\n'
NEW_EDITOR_END = '''function applyDeepLink(){
  const q=new URLSearchParams(window.location.search);
  const population=q.get("population"),position=String(q.get("position")||"").toUpperCase(),stack=Number(q.get("stack")),spot=String(q.get("spot")||"").toUpperCase();
  const handRaw=String(q.get("hand")||"").trim(),hand=HeroRanges.HAND_CLASSES.find(x=>x.toUpperCase()===handRaw.toUpperCase())||"";
  if(population)els.population.value=population;
  if(HeroRanges.POSITIONS.includes(position))els.position.value=position;
  if(Number.isFinite(stack)&&stack>0)els.stack.value=String(stack);
  if(HeroRanges.SPOTS.includes(spot))els.spot.value=spot;
  if(hand)selectedHand=hand;
}

initOptions();applyDeepLink();renderAll();
'''


def patch_once(path: Path, old: str, new: str, label: str, *, check: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if check:
        raise SystemExit(f"{label} is not applied")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one marker, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changes = [
        patch_once(REPLAYER, OLD_CARD_PARTS, NEW_CARD_PARTS, "numeric Hero card adapter", check=args.check),
        patch_once(EDITOR, OLD_EDITOR_END, NEW_EDITOR_END, "Hero editor deep link", check=args.check),
    ]
    print("real-HH compliance patch:", "updated" if any(changes) else "current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
