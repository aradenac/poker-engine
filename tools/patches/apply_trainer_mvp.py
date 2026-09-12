#!/usr/bin/env python3
"""Integrate the player trainer into the monolithic static analyser.

The patch is intentionally marker-based and idempotent. It keeps the existing
analyser/replayer code untouched apart from adding the Training entry points and
loading the dedicated trainer assets.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "site/index.html"
TRAINER = ROOT / "site/trainer.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one marker, found {count}")
    return text.replace(old, new, 1)


def patch_index() -> None:
    text = INDEX.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "</head>\n<body>",
        '<link rel="stylesheet" href="./trainer.css">\n</head>\n<body>',
        "trainer stylesheet",
    )

    text = replace_once(
        text,
        '  <a href="#replayerSection">Replayer</a>\n',
        '  <a href="#replayerSection">Replayer</a>\n  <a id="trainerNavLink" href="#trainerPage">Training</a>\n',
        "trainer quick-nav link",
    )

    marker = '  <div class="sub">Calculateur d’équité Hold’em exact, autonome et hors ligne.</div>\n'
    addition = marker + '  <div class="actions" style="margin:-10px 0 14px"><button id="trainerOpenBtn" type="button" class="primary">Training 6-max</button></div>\n'
    text = replace_once(text, marker, addition, "trainer main button")

    trainer_markup = '''<div id="trainerPage" class="trainer-page mode-hidden" aria-hidden="true">
  <div class="trainer-shell">
    <div class="trainer-head">
      <button id="trainerBackBtn" type="button" class="secondary">← Analyseur</button>
      <div>
        <div class="trainer-title">Training 6-max</div>
        <div class="trainer-sub">100 BB · profils population observés · coaching ACTION / SIZING / EV</div>
      </div>
      <div class="trainer-head-spacer"></div>
      <div class="trainer-mode-group" role="group" aria-label="Mode d'entraînement">
        <button type="button" class="trainer-mode-btn" data-trainer-mode="guided">Guidé</button>
        <button type="button" class="trainer-mode-btn active" data-trainer-mode="training">Entraînement</button>
        <button type="button" class="trainer-mode-btn" data-trainer-mode="test">Test</button>
      </div>
    </div>
    <div class="trainer-grid">
      <section class="trainer-main">
        <div class="trainer-toolbar">
          <button id="trainerNewHandBtn" type="button" class="primary">Nouvelle main</button>
          <button id="trainerContinueBtn" type="button" class="secondary" style="display:none">Continuer</button>
          <div id="trainerStatus" class="trainer-status" aria-live="polite"></div>
        </div>
        <div id="trainerTable"></div>
        <div id="trainerControls"></div>
      </section>
      <aside class="trainer-side">
        <div id="trainerRecommendation"></div>
        <div id="trainerFeedback"></div>
        <section>
          <div class="trainer-section-title">Session</div>
          <div id="trainerStats"></div>
        </section>
        <section>
          <div class="trainer-section-title">Erreurs par spot</div>
          <div id="trainerBreakdown" class="trainer-breakdown"></div>
        </section>
        <section>
          <div class="trainer-section-title">Profils à table</div>
          <div id="trainerProfiles" class="trainer-profile-list"></div>
        </section>
        <section>
          <div class="trainer-section-title">Bilan Test</div>
          <div id="trainerTestLog" class="trainer-test-log"></div>
        </section>
        <div class="trainer-note">Model B v2 pilote les profils, fréquences d’action et sizings adverses. Limite actuelle : sa politique postflop est conditionnée par le profil et le contexte, mais pas encore par la combo cachée exacte. Le moteur Model A reste l’unique source de recommandation Hero et d’EV.</div>
      </aside>
    </div>
  </div>
</div>

'''
    if 'id="trainerPage"' not in text:
        marker = '<div id="replayerPage" class="replayer-page mode-hidden" aria-hidden="true">\n'
        if text.count(marker) != 1:
            raise SystemExit(f"trainer page insertion: expected one replayer marker, found {text.count(marker)}")
        text = text.replace(marker, trainer_markup + marker, 1)

    if '<script src="./trainer.js"></script>' not in text:
        marker = '</body>\n</html>'
        if text.count(marker) != 1:
            raise SystemExit("trainer script insertion: body marker not unique")
        text = text.replace(marker, '<script src="./trainer.js"></script>\n</body>\n</html>', 1)

    INDEX.write_text(text, encoding="utf-8")


def patch_trainer() -> None:
    text = TRAINER.read_text(encoding="utf-8")

    old = '  const sb=trainerSeatForPosition({positions},"SB"),bb=trainerSeatForPosition({positions},"BB");contrib[sb]=.5;contrib[bb]=1;\n'
    new = '  const sb=trainerSeatForPosition({positions},"SB"),bb=trainerSeatForPosition({positions},"BB");contrib[sb]=.5;contrib[bb]=1;stacks[sb]-=.5;stacks[bb]-=1;\n'
    if new not in text:
        if text.count(old) != 1:
            raise SystemExit("blind stack patch marker not found exactly once")
        text = text.replace(old, new, 1)

    legacy = '  // Forced blind chips were posted before the voluntary actions.\n  if(sb!==pfaSeat&&sb!==callerSeat)stacks[sb]-=.5;if(bb!==pfaSeat&&bb!==callerSeat)stacks[bb]-=1;\n'
    text = text.replace(legacy, '')

    TRAINER.write_text(text, encoding="utf-8")


def main() -> None:
    patch_index()
    patch_trainer()
    print("trainer MVP integration patch applied")


if __name__ == "__main__":
    main()
