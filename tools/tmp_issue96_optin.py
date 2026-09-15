#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'tools/training/increment_decisions.py'
text = P.read_text(encoding='utf-8')

def repl(old, new):
    global text
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f'expected one occurrence, found {n}: {old[:120]!r}')
    text = text.replace(old, new, 1)

repl('def decision_rows(h):', 'def decision_rows(h, *, include_preflop_context_v1=False):')

repl(
'''    last_full_raise_increment = 1.0
    stack_by_pos = {norm_pos(p["pos"], n): p["chips"] / bb for p in h["players"]}
''',
'''    last_full_raise_increment = 1.0
    stack_by_pos = ({norm_pos(p["pos"], n): p["chips"] / bb for p in h["players"]}
                    if include_preflop_context_v1 else None)
''')

old = '''        pot_before_bb = max(0, (a["pot_after"] - a["raw"]) / bb)
        contribution_by_pos = {}
        for name in inhand | allin:
            if name in by:
                contribution_by_pos[norm_pos(by[name]["pos"], n)] = pf_paid[name]
        preflop_context = build_context(
            table_size=n, actor_position=actor, live_positions=live, all_in_positions=ais,
            history=hist, raise_level=rl, contribution_bb_by_position=contribution_by_pos,
            stack_bb_by_position=stack_by_pos, pot_before_bb=pot_before_bb,
            current_price_bb=pf_price, min_raise_to_bb=pf_price + last_full_raise_increment,
        )
        target_total_bb = actor_paid + a["raw"] / bb if act in ("RAISE", "JAM") else None
        row = {
'''
new = '''        pot_before_bb = max(0, (a["pot_after"] - a["raw"]) / bb)
        row = {
'''
repl(old, new)

repl(
'''            "pot_before_bb": pot_before_bb, "to_call_bb": tocall, "current_price_bb": pf_price,
            "action_add_bb": a["raw"] / bb, "actor_start_stack_bb": by[a["player"]]["chips"] / bb,
            "preflop_context_v1": preflop_context,
            "action_sizing_v1": {"incremental_cost_bb": a["raw"] / bb, "target_total_bb": target_total_bb},
            "actor_remaining_bb_before": max(0, by[a["player"]]["chips"] / bb - actor_paid),
''',
'''            "pot_before_bb": pot_before_bb, "to_call_bb": tocall, "current_price_bb": pf_price,
            "action_add_bb": a["raw"] / bb, "actor_start_stack_bb": by[a["player"]]["chips"] / bb,
            "actor_remaining_bb_before": max(0, by[a["player"]]["chips"] / bb - actor_paid),
''')

anchor = '''        }
        rows.append(row)
        if act == "FOLD": inhand.discard(a["player"]); allin.discard(a["player"])
'''
replacement = '''        }
        if include_preflop_context_v1:
            contribution_by_pos = {}
            for name in inhand | allin:
                if name in by:
                    contribution_by_pos[norm_pos(by[name]["pos"], n)] = pf_paid[name]
            preflop_context = build_context(
                table_size=n, actor_position=actor, live_positions=live, all_in_positions=ais,
                history=hist, raise_level=rl, contribution_bb_by_position=contribution_by_pos,
                stack_bb_by_position=stack_by_pos, pot_before_bb=pot_before_bb,
                current_price_bb=pf_price, min_raise_to_bb=pf_price + last_full_raise_increment,
            )
            target_total_bb = actor_paid + a["raw"] / bb if act in ("RAISE", "JAM") else None
            row["preflop_context_v1"] = preflop_context
            row["action_sizing_v1"] = {
                "incremental_cost_bb": a["raw"] / bb,
                "target_total_bb": target_total_bb,
            }
        rows.append(row)
        if act == "FOLD": inhand.discard(a["player"]); allin.discard(a["player"])
'''
repl(anchor, replacement)

repl('def build(source: Path, out: Path, summary_path: Path):',
     'def build(source: Path, out: Path, summary_path: Path, *, include_preflop_context_v1=False):')
repl('        for r in decision_rows(h):',
     '        for r in decision_rows(h, include_preflop_context_v1=include_preflop_context_v1):')
repl(
'''    p.add_argument("--summary", required=True, type=Path, help="build/provenance summary JSON")
    return p.parse_args()
''',
'''    p.add_argument("--summary", required=True, type=Path, help="build/provenance summary JSON")
    p.add_argument(
        "--preflop-contract-v1", action="store_true",
        help="attach poker-preflop-context/v1 and explicit action sizing to preflop rows; default stays byte-compatible with closed historical runs",
    )
    return p.parse_args()
''')
repl('    args = parse_args(); build(args.source, args.out, args.summary)',
     '    args = parse_args(); build(args.source, args.out, args.summary, include_preflop_context_v1=args.preflop_contract_v1)')
P.write_text(text, encoding='utf-8')

# Opt-in integration test.
T = ROOT / 'tests/preflop/test_increment_decisions_contract.py'
t = T.read_text(encoding='utf-8')
old = '    return [r for r in decision_rows(hand) if r["street"] == "preflop"]'
new = '    return [r for r in decision_rows(hand, include_preflop_context_v1=True) if r["street"] == "preflop"]'
if t.count(old) != 1:
    raise RuntimeError('test call anchor mismatch')
T.write_text(t.replace(old, new, 1), encoding='utf-8')

# Add a direct legacy-output contract: default rows contain no v1 additions.
with T.open('a', encoding='utf-8') as f:
    f.write('''\n\ndef test_default_extractor_stays_legacy_for_closed_runs():\n    hand = parse_hand(HH, "contract-fixture.txt")\n    assert hand is not None\n    rows = [r for r in decision_rows(hand) if r["street"] == "preflop"]\n    assert rows\n    assert all("preflop_context_v1" not in r for r in rows)\n    assert all("action_sizing_v1" not in r for r in rows)\n''')

# One-shot files must not survive the durable commit.
for rel in ('tools/tmp_issue96_optin.py', '.github/workflows/issue96-optin.yml'):
    q = ROOT / rel
    if q.exists():
        q.unlink()
print('issue #96 opt-in compatibility patch applied')
