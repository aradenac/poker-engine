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
        '  <a id="trainerNavLink" href="#trainerPage" data-product-domain="training">Training</a>\n',
        '  <a id="trainerNavLink" href="#trainerPage" data-product-domain="training">Training</a>\n  <a href="./hero-ranges.html" data-product-domain="strategy">Strategy</a>\n',
        "quick navigation Strategy link",
    )
    text = replace_once(
        text,
        '    <button id="trainerOpenBtn" type="button" class="primary">Training</button>\n',
        '    <button id="trainerOpenBtn" type="button" class="primary">Training</button>\n    <a id="heroRangesOpenBtn" href="./hero-ranges.html" class="filelabel" style="width:auto;text-decoration:none">Strategy</a>\n',
        "main Strategy link",
    )
    INDEX.write_text(text, encoding="utf-8")
    print("Hero range editor links integrated")


if __name__ == "__main__":
    main()
