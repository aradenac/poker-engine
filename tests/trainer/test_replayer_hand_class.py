#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site" / "index.html"
PATCH = ROOT / "tools" / "patches" / "patch_replayer_hand_class_v1.py"

text = SITE.read_text(encoding="utf-8")
patch = PATCH.read_text(encoding="utf-8")

assert "function replayHandClass(cards)" in text, "hand-class helper missing from assembled site"
assert 'const handClass=replayHandClass(cards);' in text, "seat renderer must derive class from current visible cards"
assert 'data-hand-class="${escapeHtml(handClass)}"' in text, "hand-class badge missing"
assert 'replayHandClass(player.knownCards)' not in text, "must not derive replay label directly from final known cards"
assert 'if(!cards && player.knownCards?.length===2 && step?.label==="Showdown") cards=player.knownCards;' in text, "showdown reveal contract changed"
assert "patch_replayer_hand_class" not in text, "patch implementation marker leaked into product HTML"
assert "replace_once" in patch, "patch must remain deterministic/idempotent"

m = re.search(r"function replayHandClass\(cards\)\{.*?\n\}", text, re.S)
assert m, "unable to extract replayHandClass"
helper = m.group(0)
cases = [
    (["As", "Ks"], "AKs"),
    (["Ah", "Kd"], "AKo"),
    (["7c", "7d"], "77"),
    (["2d", "Ac"], "A2o"),
    (["Tc", "9c"], "T9s"),
    (None, ""),
    ([None, None], ""),
    (["As"], ""),
]
script = helper + "\n" + f"const cases={json.dumps(cases)};\n" + "for (const [cards,expected] of cases){const got=replayHandClass(cards);if(got!==expected){throw new Error(JSON.stringify({cards,expected,got}))}}\n"
subprocess.run(["node", "-e", script], check=True, cwd=ROOT)

print("replayer hand-class contract OK")
