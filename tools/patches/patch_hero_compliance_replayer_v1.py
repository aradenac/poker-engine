#!/usr/bin/env python3
"""Attach the Hero range compliance UI to the existing browser bundle.

The analyser is intentionally still a single static page.  This patch keeps the
large historical `site/index.html` untouched and adds one deterministic loader
to the already-loaded `site/trainer.js`.  The loader then loads the range
repository contract, compliance contract, and replayer adapter in that order.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "site" / "trainer.js"
MARKER = "/* Hero range compliance replayer bootstrap (#98) */"
BLOCK = r'''

/* Hero range compliance replayer bootstrap (#98) */
(function loadHeroRangeComplianceReplayer(){
  if(typeof document==='undefined')return;
  const sources=['./hero-ranges.js','./hero-compliance.js','./hero-compliance-replayer.js'];
  let index=0;
  const next=()=>{
    if(index>=sources.length)return;
    const src=sources[index++];
    const existing=[...document.scripts].find(s=>s.getAttribute('src')===src||String(s.src||'').endsWith(src.replace(/^\.\//,'')));
    if(existing){
      if((src.endsWith('hero-ranges.js')&&window.PokerHeroRanges)||(src.endsWith('hero-compliance.js')&&window.PokerHeroCompliance)||(src.endsWith('hero-compliance-replayer.js')&&window.PokerHeroComplianceReplayer))next();
      else existing.addEventListener('load',next,{once:true});
      return;
    }
    const script=document.createElement('script');script.src=src;script.defer=false;script.addEventListener('load',next,{once:true});
    script.addEventListener('error',()=>console.warn('Hero compliance script failed to load:',src),{once:true});
    document.head.appendChild(script);
  };
  next();
})();
'''.lstrip("\n")


def apply(*, check: bool = False) -> bool:
    text = TARGET.read_text(encoding="utf-8")
    present = MARKER in text
    if check:
        if not present:
            raise SystemExit("Hero compliance loader is not synchronized into site/trainer.js")
        return False
    if present:
        return False
    if not text.endswith("\n"):
        text += "\n"
    TARGET.write_text(text + "\n" + BLOCK, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail unless the loader is already present")
    args = parser.parse_args()
    changed = apply(check=args.check)
    print("hero compliance loader:", "updated" if changed else "current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
