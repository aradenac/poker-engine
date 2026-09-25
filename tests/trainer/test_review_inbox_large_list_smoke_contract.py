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

Static + node only: no browser, no server, no network, and no file of the
repository is written (mutations live in memory or in a temporary directory).
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
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
    check_smoke_shape(smoke)
    check_ci_registration()
    print(
        "review inbox large list smoke contract checks: OK "
        f"({len(specs)} mains · {len(SORT_CODES)} tris rejoués par le contrat servi · "
        f"taille de page bornée ≤{PAGE_SIZE_MAX} · "
        f"borne basse mesurée épinglée ({PAGE_SIZE_MIN}, justification par les hauteurs "
        "mesurées rejouée) · "
        "pagination Précédent/Suivant épinglée au pager servi "
        "(page 1: Précédent désactivé, Suivant actif · assertion inverse rejouée) · "
        f"fixture={contract['probe']['fixture']})"
    )


if __name__ == "__main__":
    main()
