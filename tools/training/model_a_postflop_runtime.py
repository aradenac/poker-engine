#!/usr/bin/env python3
"""Python parity port of Model A postflop combo conditioning in site/index.html.

This module exists for scientific refit/audit only.  It does not select or
promote production artifacts.  Formulas intentionally mirror the browser
runtime so hidden-hand posteriors can be conditioned on *earlier* postflop
actions without using the target action or future cards.
"""
from __future__ import annotations

import functools
import math
from typing import Sequence

from tools.simulation.model_b_runtime import cid
from tools.training.refit_postflop_response_models import runtime_prediction

POSTFLOP_CAT_SCALE = 759375
POSTFLOP_MAX_SCORE = 8 * 759375 + 12 * 50625 + 12 * 3375 + 12 * 225 + 12 * 15 + 12


def _card_ids(cards: Sequence[int | str]) -> list[int]:
    return [int(c) if isinstance(c, int) else cid(c) for c in cards]


def straight_high(mask: int) -> int:
    for hi in range(12, 3, -1):
        if all(mask & (1 << (hi - d)) for d in range(5)):
            return hi
    if all(mask & (1 << r) for r in (12, 0, 1, 2, 3)):
        return 3
    return -1


def encode_score(category: int, values: Sequence[int]) -> int:
    score = int(category)
    for i in range(5):
        score = score * 15 + (int(values[i]) if i < len(values) else 0)
    return score


def hand_score(cards: Sequence[int | str]) -> int:
    ids = _card_ids(cards)
    rank_count = [0] * 13
    suit_count = [0] * 4
    suit_mask = [0] * 4
    rank_mask = 0
    for card in ids:
        rank, suit = card % 13, card // 13
        rank_count[rank] += 1
        suit_count[suit] += 1
        rank_mask |= 1 << rank
        suit_mask[suit] |= 1 << rank
    for suit in range(4):
        if suit_count[suit] >= 5:
            sh = straight_high(suit_mask[suit])
            if sh >= 0:
                return encode_score(8, [sh])
    for rank in range(12, -1, -1):
        if rank_count[rank] == 4:
            kicker = 12
            while kicker >= 0 and (kicker == rank or rank_count[kicker] == 0):
                kicker -= 1
            return encode_score(7, [rank, kicker])
    trips = [r for r in range(12, -1, -1) if rank_count[r] >= 3]
    pairs = [r for r in range(12, -1, -1) if rank_count[r] >= 2]
    if trips:
        pair = next((r for r in pairs if r != trips[0]), None)
        if pair is not None:
            return encode_score(6, [trips[0], pair])
    for suit in range(4):
        if suit_count[suit] >= 5:
            vals = [r for r in range(12, -1, -1) if suit_mask[suit] & (1 << r)][:5]
            return encode_score(5, vals)
    sh = straight_high(rank_mask)
    if sh >= 0:
        return encode_score(4, [sh])
    if trips:
        kickers = [r for r in range(12, -1, -1) if r != trips[0] and rank_count[r]][:2]
        return encode_score(3, [trips[0], *kickers])
    if len(pairs) >= 2:
        p1, p2 = pairs[:2]
        kicker = 12
        while kicker >= 0 and (kicker in {p1, p2} or rank_count[kicker] == 0):
            kicker -= 1
        return encode_score(2, [p1, p2, kicker])
    if len(pairs) == 1:
        pair = pairs[0]
        kickers = [r for r in range(12, -1, -1) if r != pair and rank_count[r]][:3]
        return encode_score(1, [pair, *kickers])
    return encode_score(0, [r for r in range(12, -1, -1) if rank_count[r]][:5])


def combo_features(combo: Sequence[int], board: Sequence[int | str]) -> dict[str, float]:
    board_ids = _card_ids(board)
    combo = list(combo)
    cards = combo + board_ids
    category = max(0, min(8, hand_score(cards) // POSTFLOP_CAT_SCALE))
    hole_ranks = [c % 13 for c in combo]
    board_ranks = [c % 13 for c in board_ids]
    hole_suits = [c // 13 for c in combo]
    board_suits = [c // 13 for c in board_ids]
    strength = [0.10, 0.38, 0.66, 0.75, 0.83, 0.87, 0.94, 0.98, 1.0][category]
    if category == 1 and board_ranks:
        if hole_ranks[0] == hole_ranks[1]:
            strength = 0.57 if hole_ranks[0] > max(board_ranks) else 0.34
        else:
            paired = next((r for r in hole_ranks if r in board_ranks), None)
            if paired is not None:
                unique = sorted(set(board_ranks), reverse=True)
                idx = unique.index(paired)
                strength = 0.56 if idx == 0 else 0.44 if idx == 1 else 0.36
    suit_count = [0] * 4
    for suit in hole_suits + board_suits:
        suit_count[suit] += 1
    flush_draw = 0.0
    for suit in range(4):
        if suit_count[suit] == 4 and suit in hole_suits and category < 5:
            flush_draw = 1.0
    ranks = set(hole_ranks + board_ranks)
    max_hits = 0
    for lo in range(9):
        max_hits = max(max_hits, sum(1 for r in range(lo, lo + 5) if r in ranks))
    max_hits = max(max_hits, sum(1 for r in (12, 0, 1, 2, 3) if r in ranks))
    straight_draw = 1.0 if len(board_ids) < 5 and category < 4 and max_hits == 4 else 0.0
    backdoor = 1.0 if len(board_ids) == 3 and (max(suit_count) == 3 or max_hits == 3) else 0.0
    blocker = 0.0
    board_suit_count = [0] * 4
    for suit in board_suits:
        board_suit_count[suit] += 1
    target_suit = board_suit_count.index(max(board_suit_count)) if board_suits else 0
    if board_suits and max(board_suit_count) >= 2:
        for card in combo:
            if card // 13 == target_suit:
                rank = card % 13
                if rank == 12:
                    blocker = 1.0
                elif rank == 11:
                    blocker = max(blocker, 0.55)
    draw = 0.0 if len(board_ids) >= 5 else min(1.0, 0.65 * flush_draw + 0.55 * straight_draw + 0.18 * backdoor)
    overcards = sum(1 for r in hole_ranks if board_ranks and r > max(board_ranks)) / 2 if board_ranks else 0.0
    strong = max(0.0, min(1.0, (strength - 0.55) / 0.45))
    medium = max(0.0, 1.0 - abs(strength - 0.47) / 0.32)
    air = max(0.0, 1.0 - strength - 0.35 * draw)
    return {
        "strength": strength, "draw": draw, "blocker": blocker,
        "overcards": overcards, "strong": strong, "medium": medium,
        "air": air, "backdoor": backdoor,
    }


def learned_combo_feature_map(combo: Sequence[int], decision: dict) -> dict[str, float]:
    board = _card_ids(decision.get("board") or [])
    combo = list(combo)
    score = hand_score(combo + board)
    category = max(0, min(8, score // POSTFLOP_CAT_SCALE))
    hr, hs = [c % 13 for c in combo], [c // 13 for c in combo]
    br, bs = [c % 13 for c in board], [c // 13 for c in board]
    pair_top = pair_middle = pair_bottom = overpair = underpair = kicker = 0.0
    if category == 1 and br:
        unique = sorted(set(br), reverse=True)
        if hr[0] == hr[1] and hr[0] not in br:
            if hr[0] > max(br): overpair = 1.0
            else: underpair = 1.0
        else:
            matched = sorted(set(hr).intersection(br), reverse=True)
            if matched:
                pr = max(matched); idx = unique.index(pr)
                if idx == 0: pair_top = 1.0
                elif idx == len(unique) - 1: pair_bottom = 1.0
                else: pair_middle = 1.0
                ks = [r for r in hr if r != pr]
                kicker = max(ks) / 12 if ks else 0.0
    suit_total = [0] * 4; hole_suit = [0] * 4
    for suit in hs: suit_total[suit] += 1; hole_suit[suit] += 1
    for suit in bs: suit_total[suit] += 1
    flush_draw = nut_flush_draw = backdoor_flush = 0.0
    if category < 5 and decision.get("street") != "river":
        for suit in range(4):
            if not hole_suit[suit]: continue
            if suit_total[suit] == 4:
                flush_draw = 1.0
                if any(c % 13 == 12 and c // 13 == suit for c in combo): nut_flush_draw = 1.0
            elif decision.get("street") == "flop" and suit_total[suit] == 3:
                backdoor_flush = 1.0
    present, hole_ranks = set(hr + br), set(hr)
    windows = [[12, 0, 1, 2, 3]] + [[lo, lo + 1, lo + 2, lo + 3, lo + 4] for lo in range(9)]
    has_straight = any(all(r in present for r in window) for window in windows)
    backdoor_straight = False; missing = set()
    if not has_straight and decision.get("street") != "river":
        for window in windows:
            have = [r for r in window if r in present]
            if not any(r in hole_ranks for r in have): continue
            if len(have) == 4:
                missing.update(r for r in window if r not in present)
            elif decision.get("street") == "flop" and len(have) == 3:
                backdoor_straight = True
    oesd, gutshot = (1.0 if len(missing) >= 2 else 0.0), (1.0 if len(missing) == 1 else 0.0)
    if missing: backdoor_straight = False
    combo_draw = 1.0 if flush_draw and (oesd or gutshot) else 0.0
    overcards = sum(1 for r in hr if br and r > max(br)) / 2 if br else 0.0
    board_suit_count = [0] * 4
    for suit in bs: board_suit_count[suit] += 1
    target_suit, max_count = (bs[0], 0) if bs else (0, 0)
    for suit in bs:
        if board_suit_count[suit] > max_count:
            max_count, target_suit = board_suit_count[suit], suit
    ace_suit_blocker = 1.0 if max_count >= 2 and any(c % 13 == 12 and c // 13 == target_suit for c in combo) else 0.0
    score_norm, category_norm = score / POSTFLOP_MAX_SCORE, category / 8
    pfa = 1.0 if decision.get("preflop_role") == "PFA" else 0.0
    caller = 1.0 if decision.get("preflop_role") == "CALLER" else 0.0
    limper = 1.0 if decision.get("preflop_role") == "LIMPER" else 0.0
    ip = 1.0 if decision.get("relative_position") == "IP" else 0.0
    oop = 1.0 if decision.get("relative_position") == "OOP" else 0.0
    multiway = 1.0 if float(decision.get("active_players") or 0) > 2 else 0.0
    threebetpot = 1.0 if decision.get("pot_type") in {"3BP", "4BP_PLUS"} else 0.0
    srp = 1.0 if decision.get("pot_type") == "SRP" else 0.0
    draw = max(flush_draw, oesd, gutshot)
    return {
        "score_norm": score_norm, "category_norm": category_norm,
        "pair_top": pair_top, "pair_middle": pair_middle, "pair_bottom": pair_bottom,
        "overpair": overpair, "underpair": underpair, "kicker_norm": kicker,
        "flush_draw": flush_draw, "nut_flush_draw": nut_flush_draw, "oesd": oesd,
        "gutshot": gutshot, "combo_draw": combo_draw, "overcards": overcards,
        "backdoor_flush": backdoor_flush, "backdoor_straight": 1.0 if backdoor_straight else 0.0,
        "ace_suit_blocker": ace_suit_blocker, "pocket_pair": 1.0 if hr[0] == hr[1] else 0.0,
        "suited_hole": 1.0 if hs[0] == hs[1] else 0.0,
        "pfa": pfa, "caller": caller, "limper": limper, "ip": ip, "oop": oop,
        "multiway": multiway, "threebetpot": threebetpot, "srp": srp,
        "strength_x_pfa": score_norm * pfa, "strength_x_ip": score_norm * ip,
        "draw_x_ip": draw * ip, "strength_x_multiway": score_norm * multiway,
        "draw_x_multiway": draw * multiway, "blocker_x_ip": ace_suit_blocker * ip,
    }


def combo_policy_residual(combo: Sequence[int], decision: dict, action: str, model: dict) -> float:
    spec = (model.get("combo_policy_models") or {}).get(f"{decision.get('street')}_{decision.get('mode')}")
    if not spec:
        return 0.0
    scale = float(spec.get("data_scale") or 0.0)
    classes = list(spec.get("classes") or [])
    if not scale or action not in classes:
        return 0.0
    ci = classes.index(action)
    f = learned_combo_feature_map(combo, decision)
    features = list(spec.get("features") or [])
    mu, sd = list(spec.get("feature_mean") or []), list(spec.get("feature_std") or [])
    coef = list((spec.get("coef_std") or [[]])[ci] or [])
    z = 0.0
    for j, name in enumerate(features):
        x = float(f.get(name) or 0.0); m = float(mu[j] if j < len(mu) else 0.0)
        s = max(1e-9, float(sd[j] if j < len(sd) else 1.0)); c = float(coef[j] if j < len(coef) else 0.0)
        z += c * (x - m) / s
    return scale * z


@functools.lru_cache(maxsize=96)
def _board_strength_distribution(board_tuple: tuple[int, ...]) -> tuple[dict[int, float], int]:
    blocked = set(board_tuple); scores = []
    for a in range(52):
        if a in blocked: continue
        for b in range(a + 1, 52):
            if b in blocked: continue
            scores.append(hand_score([a, b, *board_tuple]))
    scores.sort(); pct = {}; i = 0
    while i < len(scores):
        j = i + 1
        while j < len(scores) and scores[j] == scores[i]: j += 1
        pct[scores[i]] = (i + j) / (2 * len(scores)); i = j
    return pct, len(scores)


def river_showdown_percentile(combo: Sequence[int], board: Sequence[int | str]) -> float:
    b = tuple(_card_ids(board)); pct, _ = _board_strength_distribution(b)
    return max(0.0, min(1.0, float(pct.get(hand_score([*combo, *b]), 0.0))))


def facing_size_pressure(decision: dict) -> float:
    raw = decision.get("facing_size_pot_original")
    if raw is None:
        raw = decision.get("facing_price_pot") or 0.0
    return math.log1p(max(0.0, min(60.0, float(raw))))


def continuation_quality(combo: Sequence[int], decision: dict, features: dict | None = None) -> float:
    f = features or combo_features(combo, decision.get("board") or [])
    if len(decision.get("board") or []) >= 5:
        return river_showdown_percentile(combo, decision.get("board") or [])
    return max(0.0, min(1.0, 0.72 * f["strength"] + 0.23 * f["draw"] + 0.05 * f["blocker"]))


def theory_action_base_log(combo: Sequence[int], decision: dict, action: str, model: dict) -> float:
    f = combo_features(combo, decision.get("board") or [])
    prior = model.get("hand_policy_prior") or {}; street = decision.get("street")
    active = float(decision.get("active_players") or 2)
    multi = float(prior.get("multiway_bluff_multiplier") or 0.62) if active > 2 else 1.0
    raise_bluff = float((prior.get("raise_bluff_scale") or {}).get(street) or 0.3) * multi
    bet_bluff = float((prior.get("bet_bluff_scale") or {}).get(street) or 0.5) * multi
    pfa = 1.0 if decision.get("preflop_role") == "PFA" else 0.0
    ip = 1.0 if decision.get("relative_position") == "IP" else 0.0
    bf = decision.get("board_features") or {}
    wet = float(bf.get("flushiness") or 0.0) + float(bf.get("connectivity") or 0.0) / 4
    own = max(0.0, float(decision.get("own_size_pot") or 0.0))
    polar = float(prior.get("large_size_polarization_strength") or 0.75) * max(-0.5, min(1.5, own - 0.45))
    if action == "FOLD": base = 0.4 + 4.5 * (1 - f["strength"]) * (1 - 0.65 * f["draw"]) - 0.4 * f["blocker"]
    elif action == "CALL": base = 0.5 + 2.7 * f["medium"] + 2.0 * f["strength"] + 1.8 * f["draw"] + 0.25 * f["overcards"] - 1.3 * f["strong"]
    elif action == "CHECK": base = 1.0 + 1.7 * f["medium"] + 1.35 * f["air"] + 0.45 * f["strong"] - 0.35 * f["draw"] - 0.20 * pfa - 0.12 * ip
    elif action == "BET": base = -0.35 + 4.1 * f["strong"] + 1.2 * f["strength"] + bet_bluff * (1.7 * f["draw"] + 0.75 * f["blocker"] + 0.55 * f["backdoor"] + 0.25 * f["air"]) + 0.25 * pfa + 0.18 * ip - 0.12 * wet + polar * (1.5 * f["strong"] + 0.45 * f["draw"] + 0.25 * f["blocker"] - 1.1 * f["medium"])
    elif action == "RAISE": base = -1.05 + 5.7 * f["strong"] + raise_bluff * (2.0 * f["draw"] + 0.85 * f["blocker"] + 0.35 * f["air"]) + polar * (1.7 * f["strong"] + 0.45 * f["draw"] + 0.25 * f["blocker"] - 0.9 * f["medium"])
    elif action == "JAM": base = -3.0 + 8.2 * f["strong"] + raise_bluff * (2.2 * f["draw"] + 0.75 * f["blocker"]) - 0.16 * math.log1p(max(0.0, float(decision.get("spr") or 0.0))) + polar * (1.4 * f["strong"] + 0.3 * f["draw"])
    else: base = 0.0
    if decision.get("mode") == "FACING" and action in {"FOLD", "CALL", "RAISE", "JAM"}:
        pressure = facing_size_pressure(decision); quality = continuation_quality(combo, decision, f)
        centered = 2 * quality - 1; scale = 3.8 if len(decision.get("board") or []) >= 5 else (1.25 + 0.55 * pressure)
        tilt = scale * pressure * centered
        base = base - tilt if action == "FOLD" else base + tilt
    return base


def action_base_log(combo: Sequence[int], decision: dict, action: str, model: dict) -> float:
    return theory_action_base_log(combo, decision, action, model) + combo_policy_residual(combo, decision, action, model)


def exact_postflop_node(model: dict, decision: dict) -> dict | None:
    key = decision.get("canonical_key")
    if key is None:
        return None
    matches = [n for n in model.get("nodes") or [] if (n.get("canonical_key") or n.get("id")) == key]
    if not matches:
        return None
    return max(matches, key=lambda n: int((n.get("coverage") or {}).get("population_decisions") or 0))


def target_frequencies(node: dict, decision: dict, model: dict) -> dict[str, float]:
    key = (node.get("population_model") or {}).get("response_model_key")
    spec = (model.get("response_models") or {}).get(key) if key else None
    if not spec:
        pm = node.get("population_model") or {}; freqs = pm.get("frequencies") or {}
        actions = list(pm.get("legal_actions") or freqs)
        vals = {a: max(0.0, float(freqs.get(a) or 0.0)) for a in actions if a in freqs}
        total = sum(vals.values())
        return {a: v / total for a, v in vals.items()} if total > 0 else {}
    return runtime_prediction(node, spec, decision)


def calibrated_action_matrix(combos: Sequence[tuple[int, int]], weights: Sequence[float], decision: dict, target: dict[str, float], model: dict) -> tuple[list[str], list[list[float]]]:
    actions = [a for a, v in (target or {}).items() if float(v) >= 0]
    if not actions or not combos or len(combos) != len(weights):
        raise ValueError("invalid combo/action matrix inputs")
    matrix = [[math.exp(max(-12.0, min(12.0, action_base_log(combo, decision, action, model)))) for action in actions] for combo in combos]
    clean_w = [max(0.0, float(w)) for w in weights]; total_w = sum(clean_w) or 1.0
    for _ in range(70):
        for row in matrix:
            z = sum(row) or 1.0
            for j in range(len(row)): row[j] /= z
        err = 0.0
        for j, action in enumerate(actions):
            marginal = sum(clean_w[i] * matrix[i][j] for i in range(len(matrix))) / total_w
            t, m = max(1e-10, float(target.get(action) or 0.0)), max(1e-10, marginal)
            err = max(err, abs(t - m)); scale = t / m
            for i in range(len(matrix)): matrix[i][j] *= scale
        if err < 1e-7: break
    for row in matrix:
        z = sum(row) or 1.0
        for j in range(len(row)): row[j] /= z
    return actions, matrix


def observed_action_probabilities(combos: Sequence[tuple[int, int]], weights: Sequence[float], decision: dict, model: dict) -> list[float]:
    node = exact_postflop_node(model, decision)
    if node is None:
        raise KeyError("missing exact postflop node")
    target = target_frequencies(node, decision, model)
    actions, matrix = calibrated_action_matrix(combos, weights, decision, target, model)
    action = decision.get("action")
    if action not in actions:
        raise KeyError(f"observed action {action!r} outside node support")
    ai = actions.index(action)
    return [row[ai] for row in matrix]
