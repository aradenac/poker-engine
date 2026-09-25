#!/usr/bin/env python3
"""#395 T7 guard for the Review-inbox large-list browser smoke.

The browser smoke (`tests/trainer/smoke_review_inbox_large_list.py`) only runs
in the frozen `browser-smoke` job of `.github/workflows/trainer-smoke.yml`. This
module is what can be checked everywhere, so it links the smoke to the *served
bytes* and to the *served contract*:

1. the fixture is a real PokerStars export of `>= 30` hands and the committed
   bytes are exactly what the committed builder produces (no hand-edited drift);
2. the expectations the smoke asserts (temporal / gain / loss / EV-loss orders,
   per-hand real result, net in BB, position, deep link step) are *replayed
   through the served application*:
   `tests/trainer/fixtures/review_inbox_large_list_probe.js` extracts the real
   shell parser out of `site/index.html`, runs the real `poker-review-inbox/v1`
   modules and prints what it measured, and this module compares that
   measurement with the smoke's own arithmetic. A smoke that drifted from the
   served contract fails here instead of in CI;
3. the fixture is *load-bearing*: two mutations are replayed. Swapping two
   authored EV losses must change the expected EV order (the expectation is data
   driven, not constant), and flipping the winner of one hand in the fixture
   bytes must change the net the probe measures (the probe really reads the
   committed hands, it does not re-derive them from the expectation);
4. the smoke keeps driving the real surface of the served shell: every `#id` it
   clicks exists in `site/index.html`, and the bounded-list / pagination /
   deep-link / reload calls are present;
5. the smoke is registered for the frozen trainer-smoke CI: it is listed in
   `DRIVER_SMOKES` of `tests/trainer/smoke_trainer.py`, launched by
   `run_driver_smokes()`, and `.github/workflows/trainer-smoke.yml` still runs
   the single `python3 tests/trainer/smoke_trainer.py` entrypoint without a
   dedicated step (its digest is protected by
   `tests/ci/test_repro_workflow_batch2.py`).
6. the pager *polarity* is locked against the regression T1 fixed: the two
   served declarations decide the sign
   (`if(hhPagePrev)hhPagePrev.disabled=page<=0;` /
   `if(hhPageNext)hhPageNext.disabled=page>=pages-1;`), the smoke asserts the
   same sign (« Précédent désactivé sur la première page », « Suivant actif »)
   and never the reversed `not first_page["prevDisabled"]`, and `_walk_pages`
   really walks back while `prevDisabled` is false. A mutation reinstating the
   inverted assertion in an in-memory copy of the smoke must fail the check.
7. the *measured lower bound* of the painted page is pinned (T5b): the smoke
   reads the served `reviewInboxFitCount()` / `reviewInboxRowPitch()` / the
   constrained height back, consigns them in its audit per sort
   (`page_size_reference` for page 1) and fails when a paginated list paints
   fewer than `REVIEW_INBOX_PAGE_SIZE_MIN` rows although the measured height
   holds them. Under the target it demands the measured capacity *and* the
   overflow of a target-sized page. Three in-memory mutations (a removed call,
   a weakened capacity bound, a widened served target) must all be rejected.
8. the *paint read* is causal and the *view / paint waits* carry named budgets
   (T2): every read of the `#hhHands .hh-hand` counter happens inside a
   `wait_for_function` whose predicate is that very counter (`_wait_paint()`),
   so no bare counter taken after a fixed delay can come back, and the two
   budgets (`VIEW_READY_TIMEOUT_MS`, `PAINT_TIMEOUT_MS`) are pinned above the
   20 s floor the pre-fix smoke died on. Seven in-memory mutations (a 20 s paint
   budget, a 20 s view literal, a delay-carried paint, a non-causal paint wait,
   a reintroduced bare counter, a delay inserted in front of the causal read and
   a split inject/read) must all be rejected, and the causal read helper itself
   is replayed against a stub page (`_wait_paint()` polled to the first non-zero
   painted count on the named budget, with no fixed delay in reach).

Static + node only: no browser, no server, no network, and no file of the
repository is written (mutations live in memory or in a temporary directory).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "tests/trainer/smoke_review_inbox_large_list.py"
SMOKE_SOURCE = SMOKE.read_text(encoding="utf-8")
SMOKE_TRAINER = (ROOT / "tests/trainer/smoke_trainer.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/trainer-smoke.yml").read_text(encoding="utf-8")
SERVED_INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
FIXTURE_DIR = ROOT / "tests/trainer/fixtures"
FIXTURE = FIXTURE_DIR / "review_inbox_large_list.hand.txt"
BUILDER = FIXTURE_DIR / "review_inbox_large_list_builder.py"
PROBE = FIXTURE_DIR / "review_inbox_large_list_probe.js"

SMOKE_NAME = SMOKE.name
MIN_HANDS = 30
PAGE_SIZE_MAX = 15
# #395 T5b — la cible basse épinglée par le smoke et par la coque servie.
PAGE_SIZE_MIN = 10
SORT_CODES = ("recent_desc", "recent_asc", "ev_loss_desc", "gain_desc", "loss_desc")
# `reviewActualResult` (the row's secondary column) for each authored real result.
RESULT_TEXT = {"WIN": "win", "LOSS": "loss", "EVEN": "even", "UNKNOWN": "unavailable"}
CONTRACT_MODES = {
    "recent_desc": "TIMESTAMP_DESC",
    "recent_asc": "TIMESTAMP_ASC",
    "ev_loss_desc": "EV_LOSS_DESC",
    "gain_desc": "RESULT_GAIN_DESC",
    "loss_desc": "RESULT_LOSS_DESC",
}
# The ids the smoke drives (the bounded inbox, its pager, the two first-level
# tools, the replayer return and the local-persistence status).
SERVED_TARGETS = (
    "#hhHands",
    "#hhListPager",
    "#hhPagePrev",
    "#hhPageNext",
    "#hhPageInfo",
    "#hhSortSelect",
    "#reviewResultFilter",
    "#reviewInboxTab",
    "#reviewImportTab",
    "#historiesSection",
    "#handSelectionSection",
    "#hhFileInput",
    "#replayerBackBtn",
    "#replayerExportStatus",
    "#localPersistenceStatus",
)
# #395 T2 — the two served declarations that decide the prev/next sign, plus the
# smoke assertions (and their labels) that must carry the same sign. The reverse
# form is the exact defect T1 fixed, so it is forbidden here.
SERVED_PAGER_DISABLED_TOKENS = (
    "if(hhPagePrev)hhPagePrev.disabled=page<=0;",
    "if(hhPageNext)hhPageNext.disabled=page>=pages-1;",
)
PREV_DISABLED_ASSERTION = 'assert first_page["prevDisabled"]'
NEXT_ENABLED_ASSERTION = 'assert not first_page["nextDisabled"]'
INVERTED_PREV_ASSERTION = 'assert not first_page["prevDisabled"]'
PREV_DISABLED_MESSAGE = "Précédent désactivé sur la première page"
NEXT_ENABLED_MESSAGE = "Suivant actif sur la première page"
WALK_PREV_WINDOW = 'while not pages[0]["prevDisabled"]:'
WALK_NEXT_WINDOW = 'while not pages[-1]["nextDisabled"]:'
# #395 T5b — le smoke lit la mesure de la coque (`reviewInboxFitCount` /
# `reviewInboxRowPitch`, écrites par `site/index.html`) et l'épingle : la page
# peinte ne peut pas descendre sous la cible portée par la hauteur mesurée. Ces
# jetons sont ceux de l'instrument mesuré ; les deux déclarations qui portent la
# borne basse sont rejouées à l'envers (non-vacuité) plus bas.
SERVED_PAGE_SIZE_MIN_DECLARATION = "const REVIEW_INBOX_PAGE_SIZE_MIN=10;"
SERVED_FIT_SOURCES = ("function reviewInboxFitCount(){", "function reviewInboxRowPitch(){")
SMOKE_PAGE_SIZE_MIN_DECLARATION = "PAGE_SIZE_MIN = 10"
SMOKE_TARGET_HELPER = "def assert_page_size_target("
SMOKE_TARGET_CALLS = (
    'assert_page_size_target(first_page, "page 1")',
    "assert_page_size_target(\n                            painted_page,",
)
SMOKE_MEASUREMENT_CALLS = (
    'fitCount:(typeof reviewInboxFitCount===\'function\')?reviewInboxFitCount():-1,',
    "rowPitch:(typeof reviewInboxRowPitch==='function')?reviewInboxRowPitch():-1,",
    'audit["page_size_reference"]',
    '"fit_count": pages[0]["fitCount"],',
    '"row_pitch": pages[0]["rowPitch"],',
    '"list_client_height": pages[0]["listClientHeight"],',
    '"list_row_gap": pages[0]["listRowGap"],',
)
# The two load-bearing declarations of the lower bound: the page may not be
# smaller than the measured capacity, and a page below the target is only
# admitted when the measured heights prove the target would overflow.
SMOKE_CAPACITY_BOUND = "assert size >= min(total, PAGE_SIZE_MIN, fit), ("
SMOKE_TARGET_JUSTIFICATION = "assert PAGE_SIZE_MIN * pitch - gap > client + 1, ("
# #395 T2 — causalité des lectures de peinture et budget minimal des attentes de
# vue/peinture. Le smoke pré-fix mourait sur un budget de 20 s ; le plancher du
# garde est donc *au-dessus* de ces 20 s, aligné sur le budget que le settle de
# l'import accorde déjà (30 s). Les deux budgets de la smoke sont *nommés* : un
# littéral sur une attente de vue ou de peinture est refusé, et donc un retour
# au `timeout=20_000` du défaut T1 aussi.
DEFECT_TIMEOUT_MS = 20_000
MIN_VIEW_PAINT_TIMEOUT_MS = 30_000
VIEW_WAIT_CONSTANT = "VIEW_READY_TIMEOUT_MS"
PAINT_WAIT_CONSTANT = "PAINT_TIMEOUT_MS"
PAINT_SELECTOR = "#hhHands .hh-hand"
PAINT_COUNT_EXPRESSION = f"document.querySelectorAll('{PAINT_SELECTOR}').length"
PAINT_WAIT_PREDICATE = f"() => {PAINT_COUNT_EXPRESSION}"
PAINT_READ_HELPER = "async def _wait_paint(page) -> int:"
PAINT_HELPER_CALLS = (
    "painted_by_click = await _wait_paint(page)",
    "restored_painted_by_click = await _wait_paint(page)",
)
PAINT_COUNT_ASSERTS = ("assert painted_by_click > 0, (", "assert restored_painted_by_click > 0, (")
# La lecture *échantillonnée* du reste du fichier : injecter les scores
# déterministes (ce qui repeint), puis lire la page peinte, dans le même
# `page.evaluate` — jamais deux tours séparés par un délai.
ATOMIC_READ_ASSIGNMENT = "return await page.evaluate(INJECT_AND_READ_JS, payload)"
ATOMIC_READ_INJECT = "window.__reviewInboxSmoke.inject(payload);"
ATOMIC_READ_DOM = "return window.__reviewInboxSmoke.read();"
# La forme causale livrée : l'attente *est* la lecture du compteur de peinture.
PAINT_WAIT_BODY = (
    "    handle = await page.wait_for_function(\n"
    f'        "{PAINT_WAIT_PREDICATE}",\n'
    "        timeout=PAINT_TIMEOUT_MS,\n"
    "    )\n"
    "    return int(await handle.json_value())"
)
VIEW_SWITCH_TOKENS = (
    "document.body.dataset.appView==='review'",
    "document.body.dataset.appView==='replayer'",
)
# Les sections du corps de `run()` (`# --- ... ---`) : la causalité se vérifie
# « dans la même section », jamais sur le fichier entier.
SECTION_MARKER_RE = re.compile(r"(?m)^[ \t]*# --- ")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_probe(fixture: Path, payload: dict) -> dict:
    node = shutil.which("node")
    assert node is not None, "node runtime is required for the large-list smoke guard"
    completed = subprocess.run(
        [node, str(PROBE), str(fixture), json.dumps(payload)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def check_fixture(builder) -> list[dict]:
    assert BUILDER.is_file() and PROBE.is_file() and FIXTURE.is_file(), FIXTURE
    assert builder.HAND_TOTAL >= MIN_HANDS, builder.HAND_TOTAL
    text = FIXTURE.read_text(encoding="utf-8")
    assert text == builder.build_fixture(), "la fixture committée a dérivé de son builder déterministe"
    specs = builder.hand_specs()
    assert len(specs) == builder.HAND_TOTAL >= MIN_HANDS, len(specs)
    ids = [spec["hand_id"] for spec in specs]
    assert len(set(ids)) == len(ids), "les identifiants de main doivent être uniques"
    assert text.count("PokerStars Hand #") == len(specs), text.count("PokerStars Hand #")
    assert text.count("*** SUMMARY ***") == len(specs), "chaque main doit porter son SUMMARY"
    # The real settlement is authored: wins, losses, ties, unknown settlements and
    # hands without any decision (no deep link) are all present.
    assert {spec["result"] for spec in specs} == {"WIN", "LOSS", "EVEN", "UNKNOWN"}, specs
    assert sum(1 for spec in specs if spec["decision_step_index"] is None) >= 1
    assert {spec["position"] for spec in specs} >= {"BB", "CO"}
    # EV losses are distinct for every hand owning a decision, so the EV order is
    # strict and cannot pass through ties alone.
    losses = [spec["ev_loss_bb"] for spec in specs if spec["decision_step_index"] is not None]
    assert len(set(losses)) == len(losses), losses
    assert min(losses) > 0, losses
    return specs


def check_expectations_against_contract(smoke, specs: list[dict]) -> dict:
    payload = {
        "hands": {spec["hand_id"]: {"loss_bb": spec["ev_loss_bb"]} for spec in specs},
    }
    probe = run_probe(FIXTURE, payload)
    assert probe["schema"] == "poker-review-inbox-large-list-probe/v1", probe.get("schema")
    assert probe["block_count"] == len(specs), probe["block_count"]
    assert probe["warnings"] == [], probe["warnings"]

    measured = {row["hand_id"]: row for row in probe["hands"]}
    items = {row["hand_id"]: row for row in probe["items"]}
    assert set(measured) == {spec["hand_id"] for spec in specs}, "mains parsées != fixture"
    assert set(items) == set(measured), "l'inbox doit construire un item par main"

    for spec in specs:
        hand = measured[spec["hand_id"]]
        item = items[spec["hand_id"]]
        # The served parser (net settlement, big blind, button/position mapping)
        # and the review adapter (deep-link step) agree with the authored table.
        assert hand["hero_position"] == spec["position"], (spec, hand)
        assert hand["replay_step_index"] == spec["decision_step_index"], (spec, hand)
        assert item["position"] == spec["position"], (spec, item)
        assert item["deep_link_step"] == spec["decision_step_index"], (spec, item)
        assert item["total_loss_bb"] == spec["ev_loss_bb"], (spec, item)
        assert item["result"] == spec["result"], (spec, item)
        assert hand["result_text"] == RESULT_TEXT[spec["result"]], (spec, hand)
        if spec["net_bb"] is None:
            assert hand["net_bb"] is None and item["net_bb"] is None, (spec, hand, item)
            assert hand["big_blind"] is None, (spec, hand)
            assert item["decision_id"] is None if spec["decision_step_index"] is None else True
        else:
            assert abs(hand["net_bb"] - spec["net_bb"]) < 1e-9, (spec, hand)
            assert abs(item["net_bb"] - spec["net_bb"]) < 1e-9, (spec, item)
        if spec["decision_step_index"] is None:
            assert item["decision_id"] is None and item["deep_link_step"] is None, item
            assert item["status"] == "INCOMPLETE_ANALYSIS", item
            assert hand["replay_step"] is None, hand
        else:
            assert item["decision_id"] == (
                f"review:{spec['hand_id']}:{spec['decision_step_index']}"
            ), item
            # The deep link must be resolvable *and* point at the Hero's own
            # decision: the served replay really carries that step, it is the
            # Hero who acts there, and the action is the authored shove.
            assert hand["replay_step_count"] > spec["decision_step_index"], hand
            step = hand["replay_step"]
            assert step["actor"] == "Hero", (spec, step)
            assert step["action_type"] == "raise", (spec, step)
            assert step["street"] == "Préflop", (spec, step)

    # The five first-level orders the smoke asserts, recomputed from the authored
    # table and compared with the served contract, page by page for the whole list.
    expected = {code: smoke.expected_order(specs, code) for code in SORT_CODES}
    assert list(expected) == list(SORT_CODES), list(expected)
    for code, mode in CONTRACT_MODES.items():
        assert expected[code] == probe["orders"][mode], (code, probe["orders"][mode])
    for state in ("WIN", "LOSS", "EVEN", "UNKNOWN"):
        wanted = smoke.expected_ids_for_result(specs, state)
        assert sorted(probe["orders"][f"RESULT_{state}"]) == wanted, state
        assert probe["orders"][f"RESULT_{state}"] == [
            hand_id for hand_id in probe["orders"]["TIMESTAMP_DESC"] if hand_id in set(wanted)
        ], state
    # Non-vacuity: five requested orders that were not pairwise different would
    # let a sort that stopped sorting pass the smoke.
    assert len({tuple(order) for order in expected.values()}) == len(SORT_CODES), expected
    return {"probe": probe, "expected": expected}


def check_non_vacuity(smoke, builder, specs: list[dict]) -> None:
    codes = SORT_CODES
    # (a) A swapped EV loss must move the EV order: the expectation is data driven.
    swapped = copy.deepcopy(specs)
    with_decision = [row for row in swapped if row["decision_step_index"] is not None]
    first, last = min(with_decision, key=lambda row: row["index"]), max(
        with_decision, key=lambda row: row["index"]
    )
    first["ev_loss_bb"], last["ev_loss_bb"] = last["ev_loss_bb"], first["ev_loss_bb"]
    assert smoke.expected_order(swapped, "ev_loss_desc") != smoke.expected_order(specs, "ev_loss_desc"), (
        "l'ordre EV attendu doit dépendre des pertes EV de la fixture"
    )
    # ...while the temporal order (which ignores EV) stays identical.
    assert smoke.expected_order(swapped, "recent_desc") == smoke.expected_order(specs, "recent_desc")
    assert len({tuple(smoke.expected_order(specs, code)) for code in codes}) == len(codes)

    # (b) The probe really reads the committed bytes: flipping the winner of one
    # hand changes the measured net settlement of that hand.
    text = FIXTURE.read_text(encoding="utf-8")
    target = specs[0]
    marker = f"Hero collected {2 * builder.effective_stack(target['index'], target['variant']) + builder.BLIND_SB} from pot"
    assert text.count(marker) >= 1, marker
    mutated = text.replace("Hero collected", "HJ collected", 1)
    assert mutated != text
    with tempfile.TemporaryDirectory() as tmp:
        mutated_path = Path(tmp) / FIXTURE.name
        mutated_path.write_text(mutated, encoding="utf-8")
        payload = {"hands": {spec["hand_id"]: {"loss_bb": spec["ev_loss_bb"]} for spec in specs}}
        probe = run_probe(mutated_path, payload)
    flipped = next(row for row in probe["hands"] if row["hand_id"] == target["hand_id"])
    assert flipped["net_bb"] is not None and flipped["net_bb"] < 0, (
        "retourner le gagnant d'une main doit changer le net mesuré par le probe", flipped
    )
    assert abs(flipped["net_bb"] - target["net_bb"]) > 1e-9, flipped
    # The smoke itself never mutates the fixture it imports.
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == hashlib.sha256(
        builder.build_fixture().encode("utf-8")
    ).hexdigest()


def check_pagination_polarity(smoke_source: str, served_index: str = SERVED_INDEX) -> None:
    """#395 T2 — the smoke and the served pager agree on the prev/next sign.

    T1 fixed a smoke whose first-page assertion was *reversed*: it required
    `prevDisabled` to be false on page 1 while the served shell disables
    « Précédent » (`page<=0`) and leaves « Suivant » enabled (`page<pages-1`).
    Pinning both signs together is what keeps the fix from being undone.
    """
    # (1) the two served declarations that decide the sign of the pager.
    for token in SERVED_PAGER_DISABLED_TOKENS:
        assert token in served_index, token
    # (2) the smoke asserts the positive « Précédent » sign and the negative
    # « Suivant » sign (labels included), and never the reversed form T1 fixed.
    assert PREV_DISABLED_ASSERTION in smoke_source, PREV_DISABLED_ASSERTION
    assert PREV_DISABLED_MESSAGE in smoke_source, PREV_DISABLED_MESSAGE
    assert NEXT_ENABLED_ASSERTION in smoke_source, NEXT_ENABLED_ASSERTION
    assert NEXT_ENABLED_MESSAGE in smoke_source, NEXT_ENABLED_MESSAGE
    assert INVERTED_PREV_ASSERTION not in smoke_source, (
        "l'assertion inversée de page 1 (défaut corrigé en T1) ne doit jamais "
        f"revenir: {INVERTED_PREV_ASSERTION}"
    )
    # (3) `_walk_pages` really walks back while `prevDisabled` is false (it
    # reaches page 0 by clicking `#hhPagePrev`), and forward while `nextDisabled`
    # is false — the walk itself encodes the polarity the smoke asserts.
    assert WALK_PREV_WINDOW in smoke_source, WALK_PREV_WINDOW
    assert WALK_NEXT_WINDOW in smoke_source, WALK_NEXT_WINDOW


def _assert_polarity_contract_rejects(mutated_smoke: str, label: str, served_index: str) -> None:
    """The non-vacuity harness: a mutated source must fail the polarity check."""
    try:
        check_pagination_polarity(mutated_smoke, served_index)
    except AssertionError:
        return
    raise AssertionError(f"le contrat de polarité doit rejeter: {label}")


def check_pagination_polarity_non_vacuity() -> None:
    """Two in-memory mutations must fail the polarity contract.

    (a) Reinstating the inverted first-page assertion in a copy of the smoke
    bytes — the exact regression T1 repaired — must be rejected; (b) dropping
    the served `page<=0` declaration must be rejected too, so the check really
    reads `site/index.html` and is not a constant that always passes. Neither
    mutation is written to disk.
    """
    mutated_smoke = SMOKE_SOURCE.replace(
        PREV_DISABLED_ASSERTION, INVERTED_PREV_ASSERTION, 1
    )
    assert mutated_smoke != SMOKE_SOURCE, (
        "la mutation doit modifier la copie en mémoire du smoke "
        f"(assertion introuvable: {PREV_DISABLED_ASSERTION})"
    )
    _assert_polarity_contract_rejects(
        mutated_smoke, "assertion de page 1 ré-inversée", SERVED_INDEX
    )
    mutated_served = SERVED_INDEX.replace(
        SERVED_PAGER_DISABLED_TOKENS[0], "if(hhPagePrev)hhPagePrev.disabled=page<0;", 1
    )
    assert mutated_served != SERVED_INDEX, "la mutation du pager servi doit modifier la copie"
    _assert_polarity_contract_rejects(
        SMOKE_SOURCE, "déclaration servie `page<=0` remplacée", mutated_served
    )
    # The delivered smoke really carries the positive form: nothing was written.
    assert SMOKE.read_text(encoding="utf-8") == SMOKE_SOURCE


def _check_page_size_target_instrument(smoke_source: str, served_index: str) -> None:
    """#395 T5b — le smoke épingle la borne basse **mesurée** de la page peinte.

    Le smoke peut peindre moins de `REVIEW_INBOX_PAGE_SIZE_MIN` lignes seulement
    quand les hauteurs qu'il a mesurées prouvent que la cible déborderait ;
    sinon, il échoue. Les deux côtés sont relus dans les octets livrés : la
    déclaration servie de la cible, les deux fonctions de mesure servies que le
    smoke rappelle, la mesure consignée dans son audit et les deux assertions
    portantes du helper.
    """
    assert SERVED_PAGE_SIZE_MIN_DECLARATION in served_index, SERVED_PAGE_SIZE_MIN_DECLARATION
    for source in SERVED_FIT_SOURCES:
        assert source in served_index, (
            f"la mesure de la coque doit rester lue sur les octets servis: {source}",
        )
    for token in (
        SMOKE_PAGE_SIZE_MIN_DECLARATION,
        SMOKE_TARGET_HELPER,
        SMOKE_CAPACITY_BOUND,
        SMOKE_TARGET_JUSTIFICATION,
    ):
        assert token in smoke_source, token
    for token in SMOKE_TARGET_CALLS + SMOKE_MEASUREMENT_CALLS:
        assert token in smoke_source, token
    helper = smoke_source[smoke_source.index(SMOKE_TARGET_HELPER):]
    helper = helper[: helper.index("\n\ndef ")]
    # The helper measures, it never assumes: the capacity comes from the served
    # functions, and the justification branch is the only way below the target.
    for token in ('page_state["fitCount"]', 'page_state["rowPitch"]', 'page_state["total"]'):
        assert token in helper, token
    assert "assert fit >= 1 and pitch > 0" in helper, helper
    assert helper.index("assert size >= min(total, PAGE_SIZE_MIN, fit)") < helper.index(
        "if total > size and size < PAGE_SIZE_MIN:"
    ), helper


def _assert_page_size_target_rejects(mutated_smoke: str, label: str, served_index: str) -> None:
    try:
        _check_page_size_target_instrument(mutated_smoke, served_index)
    except AssertionError:
        return
    raise AssertionError(f"le contrat de borne basse doit rejeter: {label}")


def check_page_size_target_logic(smoke) -> None:
    """The lower-bound helper really discriminates, replayed offline.

    The smoke only runs in the frozen `browser-smoke` job, so its arithmetic is
    replayed here on *measured page states*: the reference measurement of
    `tests/trainer/test_review_inbox_pagination_contract.py` at 1500x1000
    (`fitCount` 11, page 11, pitch 56), the same shell unable to hold the target
    (`fitCount` 8, page 8, pitch 68 — the 1500x1000 measurement recorded before
    #395 T5b), and three cases that must be refused: a page below the target
    while the measured height holds it, a page below the target without the
    overflow that would justify it, and a widened served target.
    """
    reference = {
        "pageSizeMin": PAGE_SIZE_MIN,
        "pageSizeMax": PAGE_SIZE_MAX,
        "fitCount": 11,
        "rowPitch": 56.0,
        "listClientHeight": 627.55,
        "listRowGap": 6.0,
        "total": 32,
        "pageSize": PAGE_SIZE_MIN + 1,
    }
    smoke.assert_page_size_target(dict(reference), "replay référence")
    constrained = {
        **reference,
        "fitCount": 8,
        "pageSize": 8,
        "rowPitch": 68.0,
        "listClientHeight": 586.45,
    }
    smoke.assert_page_size_target(dict(constrained), "replay hauteur contrainte")
    for label, broken in (
        ("page sous la cible portée par la hauteur", {**reference, "fitCount": 11, "pageSize": 9}),
        (
            "page sous la cible sans débordement",
            {**constrained, "fitCount": PAGE_SIZE_MIN, "pageSize": PAGE_SIZE_MIN - 2},
        ),
        ("cible servie élargie", {**reference, "pageSizeMin": 9}),
    ):
        try:
            smoke.assert_page_size_target(dict(broken), label)
        except AssertionError:
            continue
        raise AssertionError(f"la borne basse mesurée doit refuser: {label}")


def check_page_size_target_non_vacuity() -> None:
    """#395 T5b — trois mutations en mémoire doivent être refusées.

    (a) retirer l'appel de la borne basse sur la première page ; (b) affaiblir
    l'assertion de capacité en `assert size >= 0` ; (c) élargir la cible servie
    (`REVIEW_INBOX_PAGE_SIZE_MIN=9`) pour que le smoke puisse peindre moins de
    lignes sans être vu. Aucune mutation n'est écrite sur disque.
    """
    mutations = (
        (
            "appel de la borne basse retiré",
            SMOKE_SOURCE.replace(SMOKE_TARGET_CALLS[0] + "\n                ", "", 1),
            SERVED_INDEX,
        ),
        (
            "assertion de capacité affaiblie",
            SMOKE_SOURCE.replace(SMOKE_CAPACITY_BOUND, "assert size >= 0, (", 1),
            SERVED_INDEX,
        ),
        (
            "cible servie élargie",
            SMOKE_SOURCE,
            SERVED_INDEX.replace(
                SERVED_PAGE_SIZE_MIN_DECLARATION,
                "const REVIEW_INBOX_PAGE_SIZE_MIN=9;",
                1,
            ),
        ),
    )
    for label, mutated_smoke, mutated_served in mutations:
        assert mutated_smoke != SMOKE_SOURCE or mutated_served != SERVED_INDEX, label
        _assert_page_size_target_rejects(mutated_smoke, label, mutated_served)
    # The delivered smoke and the served bytes still carry the pinned pair.
    assert SMOKE.read_text(encoding="utf-8") == SMOKE_SOURCE
    assert (ROOT / "site" / "index.html").read_text(encoding="utf-8") == SERVED_INDEX


def _mask_comments(source: str) -> str:
    """`source` with its Python comments blanked out, *same length*.

    Offsets are preserved, so a call span found on the masked text lines up with
    the real source; a commented-out wait or a commented-out paint read can
    never satisfy (nor break) the contract.
    """
    starts: list[int] = []
    offset = 0
    for line in source.splitlines(keepends=True):
        starts.append(offset)
        offset += len(line)
    masked = list(source)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        base = starts[token.start[0] - 1] + token.start[1]
        for index in range(base, base + len(token.string)):
            if masked[index] != "\n":
                masked[index] = " "
    return "".join(masked)


def _skip_string(source: str, start: int) -> int:
    """Index just past the Python string literal starting at `start`."""
    quote = source[start]
    if source.startswith(quote * 3, start):
        end = source.find(quote * 3, start + 3)
        return len(source) if end < 0 else end + 3
    index = start + 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char == "\n":
            return index
        index += 1
    return index


def _match_paren(source: str, open_index: int) -> int:
    """Index just past the `)` closing the `(` at `open_index` (strings skipped)."""
    depth = 0
    index = open_index
    while index < len(source):
        char = source[index]
        if char in "'\"":
            index = _skip_string(source, index)
            continue
        if char == "#":
            newline = source.find("\n", index)
            index = len(source) if newline < 0 else newline + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise AssertionError(f"appel non fermé à l'offset {open_index}")


def _iter_calls(source: str, name: str) -> list[tuple[int, int, str]]:
    """Every `<name>(...)` call of `source` as `(start, end, arguments)` spans.

    The scan is parenthesis-balanced and string-aware, so a call whose arguments
    carry brackets, braces or nested calls is returned whole, and the same name
    quoted inside a string literal is not a call.
    """
    calls: list[tuple[int, int, str]] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char in "'\"":
            index = _skip_string(source, index)
            continue
        if char == "#":
            newline = source.find("\n", index)
            index = len(source) if newline < 0 else newline + 1
            continue
        previous = source[index - 1] if index else ""
        if source.startswith(name, index) and not (previous.isalnum() or previous == "_"):
            after = index + len(name)
            while after < len(source) and source[after] in " \t\r\n":
                after += 1
            if after < len(source) and source[after] == "(":
                end = _match_paren(source, after)
                calls.append((index, end, source[after + 1 : end - 1]))
                index = end
                continue
        index += 1
    return calls


def _named_int_constant(source: str, name: str) -> int:
    """The pinned integer value of a module-level `NAME = <int>` declaration."""
    match = re.search(rf"(?m)^{name}\s*=\s*([0-9][0-9_]*)\s*$", source)
    assert match is not None, (
        f"la smoke doit déclarer le budget nommé `{name} = <entier>` (aucun littéral "
        "sur une attente de vue/peinture)"
    )
    return int(match.group(1).replace("_", ""))


def _section_spans(source: str) -> list[tuple[int, int]]:
    """Spans of the `# --- ... ---` sections of the smoke's `run()` body."""
    marks = [match.start() for match in SECTION_MARKER_RE.finditer(source)]
    assert len(marks) >= 5, marks
    bounds = marks + [len(source)]
    return [(bounds[index], bounds[index + 1]) for index in range(len(marks))]


def check_paint_causality_and_budget(smoke_source: str) -> dict:
    """#395 T2 — causalité des lectures de peinture et budget des attentes.

    Deux récidives sont interdites, statiquement, sur la source de la smoke :

    * une lecture de la peinture `#hhHands .hh-hand` qui ne serait pas portée par
      l'attente causale *de la même expression* — c'est-à-dire une peinture
      garantie par un délai fixe (`wait_for_timeout`) suivie d'un compteur nu,
      la forme condamnée en T1. La lecture livrée *est* l'attente
      (`_wait_paint()` → `wait_for_function` sur le compteur de lignes peintes),
      donc aucun compteur nu ne peut revenir sans faire échouer ce contrôle ;
    * une attente de *vue* (`dataset.appView`) ou de *peinture* dont le budget
      serait un littéral, ou descendrait sous le plancher
      `MIN_VIEW_PAINT_TIMEOUT_MS` : le `timeout=20_000` du défaut T1 est refusé
      par construction, que ce soit sur la vue ou sur la peinture.
    """
    assert MIN_VIEW_PAINT_TIMEOUT_MS > DEFECT_TIMEOUT_MS, (
        MIN_VIEW_PAINT_TIMEOUT_MS,
        DEFECT_TIMEOUT_MS,
    )
    code = _mask_comments(smoke_source)
    budgets = {
        name: _named_int_constant(code, name)
        for name in (VIEW_WAIT_CONSTANT, PAINT_WAIT_CONSTANT)
    }
    for name, value in budgets.items():
        assert value >= MIN_VIEW_PAINT_TIMEOUT_MS, (
            f"le budget `{name}` de la smoke est sous le plancher T2 "
            f"({value} < {MIN_VIEW_PAINT_TIMEOUT_MS})",
            budgets,
        )

    waits = _iter_calls(code, "wait_for_function")
    paint_waits = [call for call in waits if PAINT_COUNT_EXPRESSION in call[2]]
    view_waits = [call for call in waits if any(token in call[2] for token in VIEW_SWITCH_TOKENS)]
    # Non-vacuité du contrôle lui-même : la smoke doit porter les deux familles.
    assert len(paint_waits) >= 1, (
        "la smoke doit lire sa peinture par une attente causale portant le compteur "
        f"`{PAINT_COUNT_EXPRESSION}`"
    )
    for token in VIEW_SWITCH_TOKENS:
        assert any(token in call[2] for call in view_waits), (
            f"la smoke doit attendre la vue servie ({token}) par une attente nommée",
        )
    for start, end, arguments in paint_waits:
        timeout = re.search(r"\btimeout\s*=\s*([A-Za-z_][A-Za-z0-9_]*|\d[\d_]*)", arguments)
        assert timeout is not None, (start, end, arguments)
        assert timeout.group(1) == PAINT_WAIT_CONSTANT, (
            "une attente de peinture ne porte jamais de littéral : elle doit passer "
            f"`timeout={PAINT_WAIT_CONSTANT}` (trouvé {timeout.group(1)!r})",
            smoke_source[start:end],
        )
    for start, end, arguments in view_waits:
        timeout = re.search(r"\btimeout\s*=\s*([A-Za-z_][A-Za-z0-9_]*|\d[\d_]*)", arguments)
        assert timeout is not None, (start, end, arguments)
        assert timeout.group(1) == VIEW_WAIT_CONSTANT, (
            "une attente de vue ne porte jamais de littéral : elle doit passer "
            f"`timeout={VIEW_WAIT_CONSTANT}` (trouvé {timeout.group(1)!r})",
            smoke_source[start:end],
        )

    # (1) Toute lecture du compteur de peinture doit être *dans* l'attente causale
    # de la même expression : un compteur nu (`page.evaluate(...)`) est refusé.
    spans = [(start, end) for start, end, _ in paint_waits]
    reads = [match.start() for match in re.finditer(re.escape(PAINT_COUNT_EXPRESSION), code)]
    assert reads, PAINT_COUNT_EXPRESSION
    for offset in reads:
        assert any(start <= offset < end for start, end in spans), (
            "chaque lecture de la peinture doit être portée par l'attente causale "
            f"`wait_for_function` de la même expression (`{PAINT_COUNT_EXPRESSION}`)",
            smoke_source[offset - 200 : offset + 200],
        )
    # (2) La lecture causale est un helper, appelé dans les deux sections qui
    # peignent (première visite, reload), et le compteur mesuré est asserté.
    assert PAINT_READ_HELPER in code, PAINT_READ_HELPER
    tail = code[code.index(PAINT_READ_HELPER) :]
    ends = [
        tail.index(marker)
        for marker in ("\n\n\nasync def ", "\n\n\ndef ", "\n\n\nclass ")
        if marker in tail
    ]
    helper = tail[: min(ends)]
    assert PAINT_WAIT_BODY in helper, helper
    assert "wait_for_timeout" not in helper, (
        "la lecture de la peinture ne peut pas être garantie par un délai fixe", helper
    )
    for call in PAINT_HELPER_CALLS:
        assert call in code, call
    for assertion in PAINT_COUNT_ASSERTS:
        assert assertion in code, assertion
    # (3) Un délai fixe ne peut pas préparer une lecture de peinture : aucune
    # section qui lit la peinture ne porte de `wait_for_timeout` avant elle.
    call_sites = re.compile("|".join(re.escape(call) for call in PAINT_HELPER_CALLS))
    located = [match.start() for match in call_sites.finditer(code)]
    assert len(located) >= len(PAINT_HELPER_CALLS), located
    for index, call in enumerate(located):
        section = next(
            (span for span in _section_spans(smoke_source) if span[0] <= call < span[1]), None
        )
        assert section is not None, (index, call, code[call : call + 60])
        prefix = code[section[0] : call]
        assert "wait_for_timeout" not in prefix, (
            "un délai fixe ne peut pas porter une lecture de peinture "
            "(section, offset)",
            index,
            call,
        )
    # The delivered smoke really carries the pinned pair: nothing was mutated.
    assert SMOKE.read_text(encoding="utf-8") == SMOKE_SOURCE
    # (4) Les lectures échantillonnées du reste du fichier (`_read` /
    # `_inject_and_read`) lisent une peinture *causée dans le même tour* :
    # l'injection, qui repeint (`renderHistoryHands()` dans le helper installé),
    # et la lecture DOM sont dans un seul `page.evaluate`, jamais séparées.
    for token in (ATOMIC_READ_ASSIGNMENT, ATOMIC_READ_INJECT, ATOMIC_READ_DOM):
        assert token in code, token
    assert code.index(ATOMIC_READ_INJECT) < code.index(ATOMIC_READ_DOM), (
        "la lecture échantillonnée doit injecter (donc repeindre) avant de lire",
    )
    return {
        "budgets": budgets,
        "paint_waits": len(paint_waits),
        "view_waits": len(view_waits),
        "paint_reads": len(reads),
    }


def _assert_paint_wait_rejects(mutated_smoke: str, label: str) -> str:
    """The non-vacuity harness: a mutated source must fail the T2 contract.

    Returns the reason the mutated source was refused, so the executed
    demonstration is *consigned* in the suite output instead of staying implicit.
    """
    assert mutated_smoke != SMOKE_SOURCE, f"la mutation doit modifier la copie du smoke: {label}"
    try:
        check_paint_causality_and_budget(mutated_smoke)
    except AssertionError as error:
        return str(error).splitlines()[0]
    raise AssertionError(f"le contrat de causalité/budget de peinture doit rejeter: {label}")


def check_paint_wait_non_vacuity() -> list[tuple[str, str]]:
    """#395 T2 — sept mutations en mémoire doivent être refusées.

    (a) le budget nommé de peinture ramené à 20 s ; (b) une attente de vue
    laissée à un littéral de 20 s (le budget sur lequel la smoke pré-fix
    mourait) ; (c) la peinture garantie par un délai fixe suivi d'un compteur nu
    ; (d) une attente de peinture dont le prédicat ne porte plus l'expression
    causale ; (e) le compteur nu réintroduit au clic d'onglet ; (f) un délai
    fixe ajouté *devant* la lecture causale, la peinture « prise en garantie »
    par le délai ; (g) la lecture échantillonnée coupée en deux tours (injecter
    puis lire hors du même `page.evaluate`). Aucune mutation n'est écrite sur
    disque.
    """
    fixed_delay = (
        f"    await page.wait_for_timeout({PAINT_WAIT_CONSTANT})\n"
        f'    value = await page.evaluate("() => {PAINT_COUNT_EXPRESSION}")\n'
        "    return int(value)"
    )
    non_causal_wait = (
        '    handle = await page.wait_for_function(\n'
        '        "() => Array.isArray(state.hhHands)",\n'
        f"        timeout={PAINT_WAIT_CONSTANT},\n"
        "    )\n"
        f'    value = await page.evaluate("() => {PAINT_COUNT_EXPRESSION}")\n'
        "    return int(value)"
    )
    bare_count = (
        "painted_by_click = await page.evaluate(\n"
        f'                    "() => {PAINT_COUNT_EXPRESSION}"\n'
        "                )"
    )
    delay_before_read = SMOKE_SOURCE.replace(
        f"                {PAINT_HELPER_CALLS[0]}",
        f"                await page.wait_for_timeout(500)\n"
        f"                {PAINT_HELPER_CALLS[0]}",
        1,
    )
    split_read = SMOKE_SOURCE.replace(
        f"    {ATOMIC_READ_ASSIGNMENT}",
        "    await page.evaluate(INJECT_REVIEW_SCORES_FN, payload)\n"
        '    return await page.evaluate("() => window.__reviewInboxSmoke.read()")',
        1,
    )
    mutations = (
        (
            "budget de peinture ramené à 20 s",
            SMOKE_SOURCE.replace(
                f"{PAINT_WAIT_CONSTANT} = 30_000", f"{PAINT_WAIT_CONSTANT} = 20_000", 1
            ),
        ),
        (
            "attente de vue laissée à un littéral de 20 s",
            SMOKE_SOURCE.replace(
                f"timeout={VIEW_WAIT_CONSTANT}", f"timeout={DEFECT_TIMEOUT_MS}", 1
            ),
        ),
        (
            "peinture garantie par un délai fixe",
            SMOKE_SOURCE.replace(PAINT_WAIT_BODY, fixed_delay, 1),
        ),
        (
            "attente de peinture sans expression causale",
            SMOKE_SOURCE.replace(PAINT_WAIT_BODY, non_causal_wait, 1),
        ),
        (
            "compteur nu réintroduit au clic d'onglet",
            SMOKE_SOURCE.replace(PAINT_HELPER_CALLS[0], bare_count, 1),
        ),
        ("délai fixe ajouté devant la lecture causale", delay_before_read),
        ("lecture échantillonnée coupée en deux tours", split_read),
    )
    rejected: list[tuple[str, str]] = []
    for label, mutated in mutations:
        rejected.append((label, _assert_paint_wait_rejects(mutated, label)))
    # The delivered smoke still carries the pinned form: nothing was written.
    assert SMOKE.read_text(encoding="utf-8") == SMOKE_SOURCE
    return rejected


class _FakeCountHandle:
    """The handle `wait_for_function` resolves to, holding the painted count."""

    def __init__(self, value: int):
        self.value = value

    async def json_value(self) -> int:
        return self.value


class _FakePaintPage:
    """A page that only answers the causal paint wait, and records it.

    It implements exactly Playwright's `wait_for_function` contract (resolve on
    the first *truthy* value) and nothing else: a `_wait_paint` that reached for
    `wait_for_timeout` / `evaluate` instead of the causal wait would raise
    `AttributeError` here, and a predicate that did not carry the painted-counter
    expression would fail the recorded assertion.
    """

    def __init__(self, counts: list[int]):
        self.counts = list(counts)
        self.waits: list[tuple[str, object]] = []
        self.polls = 0

    async def wait_for_function(self, expression: str, *, timeout=None):
        self.waits.append((expression, timeout))
        assert PAINT_SELECTOR in expression, expression
        value = 0
        while not value:
            self.polls += 1
            value = self.counts.pop(0)
        return _FakeCountHandle(value)


def check_paint_read_helper(smoke) -> dict:
    """#395 T2 — `_wait_paint()` rejoué hors navigateur sur une page factice.

    La lecture causale n'est pas qu'un jeton de texte : le helper est *exécuté*
    et doit lire le compteur peint par l'attente causale — les sondages à 0 sont
    des attentes, la première valeur non nulle est la peinture mesurée — sur le
    budget nommé, sans jamais toucher à un délai fixe.
    """
    page = _FakePaintPage([0, 0, 7])
    painted = asyncio.run(smoke._wait_paint(page))
    assert painted == 7, painted
    # Playwright sonde le prédicat lui-même : un seul `wait_for_function`, trois
    # sondages dont le dernier a peint 7 lignes.
    assert len(page.waits) == 1 and page.polls == 3, (page.waits, page.polls)
    for expression, timeout in page.waits:
        assert PAINT_WAIT_PREDICATE in expression, expression
        assert timeout == smoke.PAINT_TIMEOUT_MS, (expression, timeout)
        assert timeout >= MIN_VIEW_PAINT_TIMEOUT_MS, (expression, timeout)
    # ...et la même expression est bien celle des deux lectures livrées.
    assert PAINT_COUNT_EXPRESSION in page.waits[0][0], page.waits[0]
    return {"polls": page.polls, "painted": painted}


def check_smoke_shape(smoke) -> None:
    assert smoke.HAND_TOTAL >= MIN_HANDS, smoke.HAND_TOTAL
    assert smoke.PAGE_SIZE_MAX == PAGE_SIZE_MAX, smoke.PAGE_SIZE_MAX
    assert smoke.PAGE_SIZE_MIN == PAGE_SIZE_MIN, smoke.PAGE_SIZE_MIN
    assert smoke.SORT_CODES == SORT_CODES, smoke.SORT_CODES
    assert smoke.VIEWPORT == (1500, 1000), smoke.VIEWPORT
    assert smoke.FIXTURE.is_file(), smoke.FIXTURE
    # #395 T5b — la borne basse mesurée : la cible servie, les deux fonctions
    # servies que le smoke relit, la mesure consignée dans l'audit et l'assertion
    # qui échoue si la page repasse sous la cible sans que la hauteur le justifie.
    _check_page_size_target_instrument(SMOKE_SOURCE, SERVED_INDEX)
    # The smoke drives the served nodes, never a JS shortcut: every id it reaches
    # for exists in the served bytes.
    for selector in SERVED_TARGETS:
        assert f"id=\"{selector[1:]}\"" in SERVED_INDEX, selector
        assert selector in SMOKE_SOURCE or selector[1:] in SMOKE_SOURCE, selector
    # The row surface the smoke reads is the one `paintReviewInboxRows` writes:
    # the hand id, the deep-link descriptor and the selection class.
    for painted in (
        'row.className="hh-hand review-inbox-row"+(state.selectedHand?.id===h.id?" selected":"");',
        "row.dataset.handId=String(h.id);",
        "if(item.deep_link?.decision_id)row.dataset.decisionId=String(item.deep_link.decision_id);",
        "if(item.deep_link?.step_index!=null)row.dataset.stepIndex=String(item.deep_link.step_index);",
        'open.className="review-inbox-open";',
        "open.onclick=()=>openReviewInboxItem(item);",
    ):
        assert painted in SERVED_INDEX, painted
    # The painted page is the *sorted query order*, sliced by the measured page
    # window — the chain the smoke asserts in the DOM, pinned here on the served
    # bytes (the window maths itself is owned by
    # test_review_inbox_pagination_contract.py):
    for token in (
        "const hands=visibleHistoryHands(),view=state.reviewInboxView,items=view?.items||[];",
        "renderReviewInboxPage(hands,byId);",
        "return items.map(item=>byId.get(String(item.hand_id))).filter(Boolean);",
        "paintReviewInboxRows(hands.slice(pageWindow.start,pageWindow.end),byId);",
        "updateReviewInboxPager({page:pageWindow.page,pages:pageWindow.pages,total:hands.length,first:pageWindow.start,last:pageWindow.end});",
    ):
        assert token in SERVED_INDEX, token
    for call in (
        "#hhFileInput",
        "set_input_files",
        "page.select_option(SORT_SELECTOR",
        "page.select_option(RESULT_FILTER_SELECTOR",
        "page.click(\"#hhPageNext\")",
        "page.click(\"#hhPagePrev\")",
        "page.click(\"#replayerBackBtn\")",
        "page.reload(",
        "schedulePersistPrefs(0)",
    ):
        assert call in SMOKE_SOURCE, call
    # ...and it asserts the *measured* contracts of #395 T5/T4 rather than
    # re-deriving them: bounded rendering without a list scroll, the page caption
    # shape, the frozen review batch and the injected review-score shape.
    for token in (
        "def assert_bounded(",
        "listScrollHeight",
        "listClientHeight",
        "docScrollHeight",
        "def parse_page_info(",
        r"Page (\d+) / (\d+) · mains (\d+)–(\d+) sur (\d+)",
        "cancelObsoleteReviewComputation",
        "reviewBatchBusy",
        "reviewBatchPreparing",
        "PokerReviewLeakAdapter",
        "parseStoredHandHistories",
        "reviewContextSignature",
        "row.dataset.decisionId",
        "row.dataset.stepIndex",
        "Analyse incomplète",
    ):
        assert token in SMOKE_SOURCE, token
    # The smoke must not fall back to a synthetic state: the inbox is reached by
    # a real import, a real click, and the list is walked with the real pager.
    for forbidden in ("state.hhHands=", "hhHandsEl.innerHTML=", "parsePokerStarsHand("):
        assert forbidden not in SMOKE_SOURCE, (
            f"le smoke ne doit pas court-circuiter l'import réel: {forbidden}"
        )
    # A regression that stopped asserting one of the acceptance dimensions would
    # remove the audit bucket that carries it.
    for bucket in ('audit["sorts"]', 'audit["deep_link"]', 'audit["selection"]', 'audit["reload"]', 'audit["imported"]'):
        assert bucket in SMOKE_SOURCE, bucket
    # Every embedded snippet is valid JavaScript (`node --check`): the browser
    # smoke only runs in the frozen job, so a JS typo would otherwise be found
    # there and nowhere else. The snippets are read back from the module itself,
    # composed ones included — the readout, the freeze, the injection, the
    # post-injection probe, the installation of the three helpers and the
    # atomic inject+read, plus the deep-link readout.
    snippet_names = sorted(name for name in dir(smoke) if name.endswith(("_JS", "_FN")))
    assert len(snippet_names) >= 6, snippet_names
    node = shutil.which("node")
    assert node is not None, "node runtime is required for the large-list smoke guard"
    with tempfile.TemporaryDirectory() as tmp:
        for name in snippet_names:
            body = getattr(smoke, name)
            assert isinstance(body, str) and body.strip(), name
            snippet_path = Path(tmp) / f"{name}.js"
            snippet_path.write_text("(" + body + "\n)", encoding="utf-8")
            completed = subprocess.run(
                [node, "--check", str(snippet_path)], capture_output=True, text=True
            )
            assert completed.returncode == 0, (name, completed.stdout + completed.stderr)
        # The composed installation really defines the three helpers: a missing
        # comma or a truncated body would otherwise only surface in the browser.
        install_path = Path(tmp) / "install_helpers.js"
        runner_path = Path(tmp) / "run_install_helpers.js"
        install_path.write_text(
            "module.exports=(window)=>(" + smoke.INSTALL_REVIEW_SMOKE_JS + ")();\n",
            encoding="utf-8",
        )
        runner_path.write_text(
            "const install=require('./install_helpers.js');const w={};const keys=install(w);\n"
            "const helpers=w.__reviewInboxSmoke||{};\n"
            "process.stdout.write(JSON.stringify({keys,types:Object.keys(helpers).map(k=>typeof helpers[k])}));\n",
            encoding="utf-8",
        )
        installed = subprocess.run([node, str(runner_path)], capture_output=True, text=True)
        assert installed.returncode == 0, installed.stdout + installed.stderr
        composition = json.loads(installed.stdout)
    assert sorted(composition["keys"]) == ["inject", "read", "verify"], composition
    assert composition["types"] == ["function", "function", "function"], composition


def check_ci_registration() -> None:
    driver_block = SMOKE_TRAINER.split("DRIVER_SMOKES = (", 1)[1].split("\n)", 1)[0]
    assert SMOKE_NAME in driver_block, (
        f"{SMOKE_NAME} doit être enregistré dans DRIVER_SMOKES de tests/trainer/smoke_trainer.py"
    )
    assert "def run_driver_smokes() -> None:" in SMOKE_TRAINER
    assert "subprocess.run([sys.executable, str(script)], check=True)" in SMOKE_TRAINER
    main_block = SMOKE_TRAINER.split('if __name__ == "__main__":', 1)[1]
    assert "run_driver_smokes()" in main_block, (
        "les driver smokes doivent être lancés depuis le point d'entrée"
    )
    # The frozen workflow keeps its single entrypoint: no dedicated step for this
    # smoke (the file digest is protected by tests/ci/test_repro_workflow_batch2.py).
    assert "run: python3 tests/trainer/smoke_trainer.py" in WORKFLOW
    assert SMOKE_NAME not in WORKFLOW, (
        "le workflow trainer-smoke reste gelé: le smoke passe par l'entrée unique smoke_trainer.py"
    )


def main() -> None:
    smoke = load_module(SMOKE, "review_inbox_large_list_smoke")
    builder = load_module(BUILDER, "review_inbox_large_list_builder")
    specs = check_fixture(builder)
    contract = check_expectations_against_contract(smoke, specs)
    check_non_vacuity(smoke, builder, specs)
    check_pagination_polarity(SMOKE_SOURCE)
    check_pagination_polarity_non_vacuity()
    check_page_size_target_logic(smoke)
    check_page_size_target_non_vacuity()
    paint = check_paint_causality_and_budget(SMOKE_SOURCE)
    paint_rejections = check_paint_wait_non_vacuity()
    paint_helper = check_paint_read_helper(smoke)
    check_smoke_shape(smoke)
    check_ci_registration()
    # La démonstration est consignée dans la sortie : chaque mutation rejouée en
    # mémoire, et la raison exacte pour laquelle le garde la refuse.
    for label, reason in paint_rejections:
        print(f"  refusé (T2): {label} → {reason[:150]}")
    print(
        "review inbox large list smoke contract checks: OK "
        f"({len(specs)} mains · {len(SORT_CODES)} tris rejoués par le contrat servi · "
        f"taille de page bornée ≤{PAGE_SIZE_MAX} · "
        f"borne basse mesurée épinglée ({PAGE_SIZE_MIN}, justification par les hauteurs "
        "mesurées rejouée) · "
        "pagination Précédent/Suivant épinglée au pager servi "
        "(page 1: Précédent désactivé, Suivant actif · assertion inverse rejouée) · "
        f"peinture lue causalement ({paint['paint_reads']} lecture(s) "
        f"`{PAINT_COUNT_EXPRESSION}` dans l'attente · helper rejoué "
        f"{paint_helper['polls']} sondages → {paint_helper['painted']} lignes peintes) · "
        f"budgets vue/peinture nommés "
        f"{paint['budgets'][VIEW_WAIT_CONSTANT]} / {paint['budgets'][PAINT_WAIT_CONSTANT]} ms "
        f"(plancher {MIN_VIEW_PAINT_TIMEOUT_MS}, {DEFECT_TIMEOUT_MS} refusé · "
        "7 mutations rejouées) · "
        f"fixture={contract['probe']['fixture']})"
    )


if __name__ == "__main__":
    main()
