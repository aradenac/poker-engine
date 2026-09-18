#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.training.audit_hero_preflop_coverage import coverage_group,matrix_key,support_tier

def row(family,history,actor="BTN"):
    return {"family":family,"history":history,"actor_position":actor}

assert coverage_group(row("VS_RFI",[]))=="VS_RFI"
assert coverage_group(row("VS_RFI_CALLERS",[]))=="RFI_CALLERS_SQUEEZE"
assert coverage_group(row("VS_LIMPERS",[]))=="VS_LIMPERS_ISO"
assert coverage_group(row("VS_ISO",[]))=="VS_LIMPERS_ISO"
assert coverage_group(row("OPENER_OR_ISO_VS_3BET",[]))=="VS_3BET"
assert coverage_group(row("AGGRESSOR_VS_4BET",[]))=="VS_4BET_OR_JAM"
assert coverage_group(row("VS_5BET",[]))=="VS_4BET_OR_JAM"

r=row("VS_RFI_CALLERS",[
    {"position":"LJ","action":"RAISE"},
    {"position":"HJ","action":"CALL"},
    {"position":"CO","action":"CALL"},
],actor="BTN")
k=matrix_key(r)
assert k[0]=="RFI_CALLERS_SQUEEZE"
assert k[1]=="BTN"
assert k[2]=="LJ"
assert k[3]==2
assert k[4]==0
assert k[5]=="LJ"
assert k[6] is False

jam=row("VS_RFI",[{"position":"CO","action":"JAM"}],actor="BTN")
assert matrix_key(jam)[6] is True
assert support_tier(1000)=="VERY_HIGH"
assert support_tier(999)=="HIGH"
assert support_tier(250)=="HIGH"
assert support_tier(50)=="MEDIUM"
assert support_tier(20)=="LOW"
assert support_tier(19)=="SPARSE"
print("Hero preflop TRAIN coverage audit unit contract: PASS")
