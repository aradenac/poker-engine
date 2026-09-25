#!/usr/bin/env python3
"""Anti-claims guard for issue #394 — `poker-issue-394-stale-claims-guard/v1`.

The #394 review rejected three affirmations that were still versioned while the
delivered code said the opposite. The documents and the comments were corrected;
this module is the static contract that keeps them corrected. It scans **every
versioned text file** and fails on the first file that re-introduces one of the
three stale claims:

1. ``nav-entry-points-to-standalone-editor`` — the `#quickNav` Strategy entry
   keeps a *real* link to the standalone editor ``./hero-ranges.html``.
   ``site/index.html`` contradicts it: the entry is
   ``<a href="#strategyPage" data-product-domain="strategy">Strategy</a>`` (an
   in-app navigation), and the only real ``./hero-ranges.html`` links are the
   Accueil mode card, ``#heroRangesOpenBtn`` and ``#strategyPageEditorLink``.

2. ``narrow-rendering-out-of-scope`` — the ``<901px`` rendering is untouched /
   outside the rule's scope. ``site/index.html`` contradicts it: only the
   ``100dvh`` / no-global-scroll rule is desktop-only, while the
   sub-view / tab / pane pattern is **global** (base rules outside every media
   query, `activateAppSubview` without a width guard), so the dense views stay
   tabbed below ``901px``.

3. ``fit-measured-by-out-of-repo-harness`` — the desktop fit measurement leans
   on a harness that lives outside the checkout. The repository contradicts it:
   ``tests/trainer/smoke_modes_desktop.py`` owns the measurement, its
   ``--report`` materialises the JSON report, the frozen ``browser-smoke`` job of
   ``.github/workflows/trainer-smoke.yml`` is the only authority for the verdict,
   and ``docs/desktop-modes-fit-evidence.md`` cites no path outside the checkout.

Each claim is carried as a set of *affermative* patterns (the rejected phrasings
themselves, whitespace-normalised) plus a structural block that proves the code
contradicts the claim, so the guard is not vacuous: it fails both when a stale
claim is re-written and when the contradicting implementation disappears.

Only this file is exempt from the scan — it necessarily carries the rejected
phrasings as detector input. Everything else that git versions is scanned.

    python3 tools/check_issue394_stale_claims.py            # EXIT=0 when clean
    python3 tools/check_issue394_stale_claims.py --self-test # + non-vacuity proof

The ``--self-test`` replays each detector against the historical revision that
carried the claim (``git show <rev>:<path>``); it is skipped, never faked, when
the revision is absent from a shallow checkout.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()

# Text payloads only; generated model assets and any large payload are skipped
# (a prose claim never lives in a 5 MiB model dump).
TEXT_SUFFIXES = (
    ".cjs", ".cfg", ".css", ".htm", ".html", ".js", ".json", ".markdown", ".md",
    ".mjs", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml",
)
MAX_SCANNED_BYTES = 1_000_000


@dataclass(frozen=True)
class StaleClaim:
    claim_id: str
    title: str
    patterns: tuple[str, ...]
    # Historical revisions that carried the claim, for `--self-test` only.
    historical: tuple[tuple[str, str], ...] = field(default=())


STALE_CLAIMS: tuple[StaleClaim, ...] = (
    StaleClaim(
        claim_id="nav-entry-points-to-standalone-editor",
        title="#quickNav Strategy entry keeps the real ./hero-ranges.html link",
        patterns=(
            r"keep a real `href` to the standalone editor",
            r"that entry's `href` is the standalone editor",
            r"\*\*Strategy\*\* mode is the one exception",
        ),
        historical=(("a6cefc7", "docs/ux-desktop-view-shell.md"),),
    ),
    StaleClaim(
        claim_id="narrow-rendering-out-of-scope",
        title="the <901px rendering is untouched / outside the rule's scope",
        patterns=(
            r"hors périmètre de cette règle",
            r"<901px.{0,120}?(untouched|inchang[ée]e?|non modifi[ée]e?|out of scope)",
            r"(untouched|inchang[ée]e?|non modifi[ée]e?).{0,120}?<901px",
        ),
        historical=(
            ("dda6f60", "site/index.html"),
            ("c3da3fe", "site/trainer.css"),
        ),
    ),
    StaleClaim(
        claim_id="fit-measured-by-out-of-repo-harness",
        title="the desktop fit measurement leans on a harness outside the checkout",
        patterns=(
            r"hors dépôt et non versionnés",
            r"harnais.{0,80}?hors contrat",
            r"PYTHONPATH.{0,20}?hors dépôt",
            r"/tmp/nx3",
        ),
        historical=(("c83c72f", "docs/desktop-modes-fit-evidence.md"),),
    ),
)


def flat(text: str) -> str:
    """Collapse wrapping so the detectors are stable across reflow."""
    return " ".join(text.split())


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True
    ).stdout


def versioned_text_files() -> list[str]:
    tracked = [path for path in git("ls-files", "-z").split("\0") if path]
    selected: list[str] = []
    for rel in tracked:
        if rel == SELF:
            continue
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        path = ROOT / rel
        try:
            if path.stat().st_size > MAX_SCANNED_BYTES:
                continue
        except OSError:  # pragma: no cover - tracked file removed meanwhile
            continue
        selected.append(rel)
    return selected


def scan_versioned_files(files: list[str]) -> list[tuple[str, str, str]]:
    """Every (file, claim, matched text) that re-affirms a stale claim."""
    violations: list[tuple[str, str, str]] = []
    for rel in files:
        try:
            text = flat((ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        for claim in STALE_CLAIMS:
            for pattern in claim.patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    violations.append((rel, claim.claim_id, match.group(0)))
    return violations


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def check_nav_entry_claim_is_contradicted() -> None:
    index = read("site/index.html")
    nav = index.split('<nav id="quickNav"', 1)[1].split("</nav>", 1)[0]
    assert '<a href="#strategyPage" data-product-domain="strategy">Strategy</a>' in nav, nav
    assert "hero-ranges.html" not in nav, (
        "the #quickNav Strategy entry is an in-app navigation; the real editor "
        "links live outside the navigation"
    )
    for real_link in (
        '<a class="mode-card" data-app-view="strategy" data-hero-ranges-entry href="./hero-ranges.html">',
        '<a id="heroRangesOpenBtn" href="./hero-ranges.html"',
        '<a id="strategyPageEditorLink"',
    ):
        assert real_link in index, real_link


def check_narrow_rendering_claim_is_contradicted() -> None:
    index = read("site/index.html")
    shell = flat(index)
    # The corrected scope statement: the shell rule is desktop-only, the
    # sub-view pattern is global.
    assert "reste **desktop only**" in shell
    assert "lui, est **global**" in shell
    assert ".app-subview-panel[hidden]{display:none!important}" in index
    activate = index.split("function activateAppSubview(name){", 1)[1].split(
        "function activateAppSubviewForTarget", 1
    )[0]
    assert "matchMedia" not in activate, "the pane toggle must not be width-guarded"
    # The static guard that owns the global-scope proof stays in place.
    accessibility = read("tests/trainer/test_desktop_accessibility_contract.py")
    assert "must be declared outside any media query" in accessibility
    assert "it is never desktop-only" in accessibility


def check_fit_measurement_claim_is_contradicted() -> None:
    smoke = read("tests/trainer/smoke_modes_desktop.py")
    assert "--report" in smoke
    assert "artifacts/desktop-modes-fit/measurements.json" in smoke
    entrypoint = read("tests/trainer/smoke_trainer.py")
    assert "smoke_modes_desktop.py" in entrypoint
    workflow = read(".github/workflows/trainer-smoke.yml")
    assert "run: python3 tests/trainer/smoke_trainer.py" in workflow
    evidence = read("docs/desktop-modes-fit-evidence.md")
    assert "/tmp/" not in evidence, "the fit evidence may not cite a path outside the checkout"
    assert "browser-smoke" in evidence
    assert "seule autorité" in flat(evidence)


CONTRADICTION_CHECKS = (
    check_nav_entry_claim_is_contradicted,
    check_narrow_rendering_claim_is_contradicted,
    check_fit_measurement_claim_is_contradicted,
)


def self_test() -> list[str]:
    """Prove each detector matches the revision that carried the claim."""
    notes: list[str] = []
    for claim in STALE_CLAIMS:
        assert claim.patterns, claim.claim_id
        assert claim.historical, claim.claim_id
        for rev, path in claim.historical:
            try:
                blob = subprocess.run(
                    ["git", "show", f"{rev}:{path}"],
                    cwd=ROOT,
                    check=True,
                    stdout=subprocess.PIPE,
                    text=True,
                ).stdout
            except subprocess.CalledProcessError:
                notes.append(f"{claim.claim_id}: skipped ({rev} absent from this checkout)")
                continue
            text = flat(blob)
            hit = [pattern for pattern in claim.patterns if re.search(pattern, text, re.IGNORECASE)]
            assert hit, f"{claim.claim_id}: no detector matched {rev}:{path}"
            notes.append(f"{claim.claim_id}: {len(hit)} detector(s) matched {rev}:{path}")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--list-files", action="store_true")
    args = parser.parse_args()

    files = versioned_text_files()
    if args.list_files:
        print(f"{len(files)} versioned text files scanned")
        return 0

    violations = scan_versioned_files(files)
    for rel, claim_id, matched in violations:
        print(f"stale claim re-affirmed: {rel}: {claim_id} ({matched})")
    if violations:
        return 1

    for check in CONTRADICTION_CHECKS:
        check()

    if args.self_test:
        for note in self_test():
            print(f"self-test {note}")

    print(
        f"issue-394 stale claims guard: PASS "
        f"({len(files)} versioned text files scanned, {len(STALE_CLAIMS)} claims)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
