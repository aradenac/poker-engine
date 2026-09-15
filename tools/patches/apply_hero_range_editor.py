#!/usr/bin/env python3
"""Expose the standalone Hero range editor from the main static application."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "site" / "index.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = INDEX.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '  <a href="#rangesSection">Ranges</a>\n',
        '  <a href="#rangesSection">Ranges</a>\n  <a href="./hero-ranges.html">Ranges Hero</a>\n',
        "quick navigation Hero ranges link",
    )
    text = replace_once(
        text,
        '  <div class="actions" style="margin:-10px 0 14px"><button id="trainerOpenBtn" type="button" class="primary">Training 6-max</button></div>\n',
        '  <div class="actions" style="margin:-10px 0 14px"><button id="trainerOpenBtn" type="button" class="primary">Training 6-max</button><a id="heroRangesOpenBtn" href="./hero-ranges.html" class="filelabel" style="width:auto;text-decoration:none">Ranges Hero</a></div>\n',
        "main Hero ranges link",
    )
    INDEX.write_text(text, encoding="utf-8")
    print("Hero range editor links integrated")


if __name__ == "__main__":
    main()
