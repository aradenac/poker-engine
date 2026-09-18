#!/usr/bin/env python3
"""Verify the canonical live application for a #113 PROMOTE handoff.

Read-only verifier:
- checks the exact served RELEASE.json bytes and deployment metadata;
- verifies every functional file declared by the served release using Git blob
  identity, not only HTTP status;
- exercises the live replayer with a synthetic PokerStars hand;
- opens the live trainer and waits for its promoted A/B/Hero assets to load.

The resulting JSON is shaped for RELEASE_HANDOFF_CONTRACT.json.  Failed probes
are persisted in the output and the command returns non-zero, so they cannot be
mistaken for VERIFIED_LIVE evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_release_handoff import is_production_url  # noqa: E402

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
META_FIELD = re.compile(r"^([a-z_]+):\s*(.*?)\s*$", re.MULTILINE)
REQUIRED_PROBES = (
    "release_identity",
    "index",
    "replayer",
    "trainer",
    "hero_ranges",
    "required_assets",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_blob_sha_bytes(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def parse_deployment_metadata(css: str) -> dict[str, str]:
    fields = {key: value for key, value in META_FIELD.findall(css)}
    commit = fields.get("commit", "")
    if not HEX40.fullmatch(commit):
        raise ValueError("deployment metadata has no valid 40-character commit")
    if not fields.get("build_id"):
        raise ValueError("deployment metadata has no build_id")
    return fields


def join_url(base: str, rel: str) -> str:
    base = base.rstrip("/") + "/"
    return urllib.parse.urljoin(base, rel.lstrip("/"))


def http_get(url: str, timeout: float) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "poker-engine-release-verifier/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        if status < 200 or status >= 300:
            raise ValueError(f"{url}: HTTP {status}")
        return response.read(), str(response.headers.get("content-type") or "")


def functional_assets(release: dict[str, Any]) -> dict[str, str]:
    files = (
        release.get("identity", {})
        .get("assembled_site", {})
        .get("functional_files", {})
    )
    if not isinstance(files, dict) or not files:
        raise ValueError("served release has no assembled_site.functional_files")
    out: dict[str, str] = {}
    for path, descriptor in files.items():
        expected = descriptor.get("git_blob_sha") if isinstance(descriptor, dict) else None
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise ValueError(f"functional asset has invalid git blob identity: {path}")
        rel = str(path)
        if rel.startswith("site/"):
            rel = rel[5:]
        out[rel] = expected
    return out


def probe_row(probe_id: str, ok: bool, **details: Any) -> dict[str, Any]:
    return {
        "id": probe_id,
        "status": "PASS" if ok else "FAIL",
        **details,
    }


LIVE_HAND = """PokerStars Hand #999999999999: Hold'em No Limit (0.50/1.00) - 2026/09/18 20:00:00 CET
Table 'Live Release Smoke' 6-max Seat #4 is the button
Seat 1: Player1 (100 in chips)
Seat 2: Player2 (100 in chips)
Seat 3: Player3 (100 in chips)
Seat 4: Hero (100 in chips)
Seat 5: Player5 (100 in chips)
Seat 6: Player6 (100 in chips)
Player5: posts small blind 0.50
Player6: posts big blind 1.00
*** HOLE CARDS ***
Dealt to Hero [As Ah]
Player1: folds
Player2: folds
Player3: folds
Hero: raises 2.00 to 3.00
Player5: folds
Player6: folds
Uncalled bet (2.00) returned to Hero
Hero collected 2.50 from pot
*** SUMMARY ***
Total pot 2.50 | Rake 0
Seat 4: Hero (button) collected (2.50)
"""


async def browser_probes(base_url: str, timeout_ms: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - CI installs Playwright
        raise RuntimeError("playwright is required for live browser probes") from exc

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            console_errors: list[str] = []
            page.on("pageerror", lambda exc: console_errors.append(str(exc)))
            await page.goto(base_url, wait_until="networkidle", timeout=timeout_ms)

            replayer_info = await page.evaluate(
                """(txt)=>{
                  if(typeof parsePokerStarsHand!=='function')throw new Error('parsePokerStarsHand missing');
                  const h=parsePokerStarsHand(txt,'live-release-smoke');
                  if(!h||h.heroName!=='Hero')throw new Error('synthetic hand did not resolve Hero');
                  state.hhMode=true;state.hhHands=[h];state.selectedHand=h;
                  state.replaySteps=[];state.replayIndex=0;
                  loadReplayForSelectedHand(true);renderVisualReplay();
                  const el=document.getElementById('hhVisualReplay');
                  return {
                    handId:String(h.id||''),
                    hero:h.heroName,
                    steps:Number(state.replaySteps?.length||0),
                    rendered:!!el&&!el.classList.contains('mode-hidden')&&el.textContent.length>0
                  };
                }""",
                LIVE_HAND,
            )
            replayer_ok = (
                replayer_info.get("hero") == "Hero"
                and int(replayer_info.get("steps") or 0) > 0
                and bool(replayer_info.get("rendered"))
            )
            replayer = probe_row(
                "replayer",
                replayer_ok,
                evidence=replayer_info,
                page_errors=list(console_errors),
            )

            await page.click("#trainerOpenBtn")
            await page.wait_for_function(
                """()=>typeof trainerState!=='undefined' &&
                    trainerState.open===true &&
                    trainerState.loading===false &&
                    (trainerState.ready===true || !!trainerState.error)""",
                timeout=timeout_ms,
            )
            trainer_info = await page.evaluate(
                """()=>({
                  open:trainerState.open,
                  ready:trainerState.ready,
                  error:String(trainerState.error||''),
                  populationId:trainerState.populationId,
                  hasHand:!!trainerState.hand,
                  pageVisible:!document.getElementById('trainerPage')?.classList.contains('mode-hidden'),
                  status:document.getElementById('trainerStatus')?.textContent||''
                })"""
            )
            if trainer_info.get("ready") and not trainer_info.get("hasHand"):
                await page.wait_for_function("()=>!!trainerState.hand || !!trainerState.error", timeout=timeout_ms)
                trainer_info = await page.evaluate(
                    """()=>({
                      open:trainerState.open,
                      ready:trainerState.ready,
                      error:String(trainerState.error||''),
                      populationId:trainerState.populationId,
                      hasHand:!!trainerState.hand,
                      pageVisible:!document.getElementById('trainerPage')?.classList.contains('mode-hidden'),
                      status:document.getElementById('trainerStatus')?.textContent||''
                    })"""
                )
            trainer_ok = (
                bool(trainer_info.get("open"))
                and bool(trainer_info.get("ready"))
                and bool(trainer_info.get("hasHand"))
                and bool(trainer_info.get("pageVisible"))
                and not trainer_info.get("error")
            )
            trainer = probe_row(
                "trainer",
                trainer_ok,
                evidence=trainer_info,
                page_errors=list(console_errors),
            )
            return replayer, trainer
        finally:
            await browser.close()


async def verify_live(
    *,
    production_url: str,
    expected_commit_sha: str,
    expected_site_release_sha256: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not is_production_url(production_url):
        raise ValueError("production_url is not a canonical production URL")
    expected_commit_sha = expected_commit_sha.lower()
    expected_site_release_sha256 = expected_site_release_sha256.lower()
    if not HEX40.fullmatch(expected_commit_sha):
        raise ValueError("expected_commit_sha must be 40 lowercase hexadecimal characters")
    if not HEX64.fullmatch(expected_site_release_sha256):
        raise ValueError("expected_site_release_sha256 must be 64 lowercase hexadecimal characters")

    probes: dict[str, dict[str, Any]] = {}
    observed_commit = ""
    provider_build_id = ""

    try:
        release_raw, release_type = http_get(join_url(production_url, "RELEASE.json"), timeout_seconds)
        release = json.loads(release_raw.decode("utf-8"))
        observed_release_sha = sha256_bytes(release_raw)
        ok = (
            release.get("schema") == "poker-site-release/v3"
            and observed_release_sha == expected_site_release_sha256
        )
        probes["release_identity"] = probe_row(
            "release_identity",
            ok,
            observed_sha256=observed_release_sha,
            expected_sha256=expected_site_release_sha256,
            schema=release.get("schema"),
            content_type=release_type,
        )
    except Exception as exc:
        release = {}
        observed_release_sha = ""
        probes["release_identity"] = probe_row("release_identity", False, error=str(exc))

    try:
        meta_raw, _ = http_get(join_url(production_url, "deployment-meta.css"), timeout_seconds)
        meta = parse_deployment_metadata(meta_raw.decode("utf-8", errors="replace"))
        observed_commit = meta["commit"]
        provider_build_id = meta["build_id"]
        if observed_commit != expected_commit_sha:
            raise ValueError(f"served commit {observed_commit} != expected {expected_commit_sha}")
    except Exception as exc:
        probes.setdefault("release_identity", probe_row("release_identity", False))
        probes["release_identity"]["status"] = "FAIL"
        probes["release_identity"]["deployment_metadata_error"] = str(exc)

    try:
        index_raw, index_type = http_get(production_url.rstrip("/") + "/", timeout_seconds)
        index_text = index_raw.decode("utf-8", errors="replace")
        probes["index"] = probe_row(
            "index",
            "Poker Range Equity" in index_text and "trainerOpenBtn" in index_text and "hhVisualReplay" in index_text,
            bytes=len(index_raw),
            content_type=index_type,
        )
    except Exception as exc:
        probes["index"] = probe_row("index", False, error=str(exc))

    try:
        hero_html, _ = http_get(join_url(production_url, "hero-ranges.html"), timeout_seconds)
        hero_js, _ = http_get(join_url(production_url, "hero-ranges.js"), timeout_seconds)
        probes["hero_ranges"] = probe_row(
            "hero_ranges",
            b"hero" in hero_html.lower() and b"poker-hero-range-repository" in hero_js,
            html_bytes=len(hero_html),
            js_bytes=len(hero_js),
        )
    except Exception as exc:
        probes["hero_ranges"] = probe_row("hero_ranges", False, error=str(exc))

    try:
        assets = functional_assets(release)
        mismatches: list[dict[str, str]] = []
        for rel, expected_blob in sorted(assets.items()):
            payload, _ = http_get(join_url(production_url, rel), timeout_seconds)
            actual_blob = git_blob_sha_bytes(payload)
            if actual_blob != expected_blob:
                mismatches.append({"path": rel, "expected_git_blob": expected_blob, "actual_git_blob": actual_blob})
        probes["required_assets"] = probe_row(
            "required_assets",
            not mismatches,
            checked=len(assets),
            mismatches=mismatches,
        )
    except Exception as exc:
        probes["required_assets"] = probe_row("required_assets", False, error=str(exc))

    try:
        replayer, trainer = await browser_probes(production_url, int(timeout_seconds * 1000))
        probes["replayer"] = replayer
        probes["trainer"] = trainer
    except Exception as exc:
        probes["replayer"] = probe_row("replayer", False, error=str(exc))
        probes["trainer"] = probe_row("trainer", False, error=str(exc))

    rows = [probes.get(probe_id, probe_row(probe_id, False, error="probe not produced")) for probe_id in REQUIRED_PROBES]
    ok = all(row["status"] == "PASS" for row in rows)
    return {
        "schema": "poker-live-release-verification/v1",
        "status": "PASS" if ok else "FAIL",
        "production_url": production_url,
        "expected_commit_sha": expected_commit_sha,
        "observed_commit_sha": observed_commit,
        "expected_site_release_sha256": expected_site_release_sha256,
        "observed_site_release_sha256": observed_release_sha,
        "provider_build_id": provider_build_id,
        "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "probes": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-url", required=True)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument("--expected-site-release-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(
        verify_live(
            production_url=args.production_url,
            expected_commit_sha=args.expected_commit_sha,
            expected_site_release_sha256=args.expected_site_release_sha256,
            timeout_seconds=args.timeout_seconds,
        )
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
