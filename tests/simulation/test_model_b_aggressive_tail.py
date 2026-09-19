#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from tools.simulation.model_b_aggressive_tail import (
    AggressiveTailModel,
    TAIL_CLASSES,
    artifact_sha256,
    build_artifact,
    tail_class,
)
from tools.simulation.model_b_price_response import HIERARCHY
from tools.simulation.model_b_support_aware_backoff import (
    SupportAwareBackoffModel,
    build_artifact as build_support_artifact,
)


def support_graph():
    return {
        "schema":"model-b-support-aware-backoff-graph/v1",
        "version":"2026-09-19.1",
        "source_split":"TRAIN",
        "frozen_before_validation":True,
        "action_support":{"min_observations":30,"min_distinct_hands":20},
        "sizing_support":{"min_raises":12,"min_distinct_hands":8},
        "levels":[{"index":i,"dimensions":list(x)} for i,x in enumerate(HIERARCHY)],
    }


def tail_graph():
    return {
        "schema":"model-b-aggressive-tail-backoff-graph/v1",
        "version":"2026-09-19.1",
        "source_split":"TRAIN",
        "frozen_before_validation":True,
        "tail_support":{"min_raises":12,"min_distinct_hands":8},
        "levels":[{"index":i,"dimensions":list(x)} for i,x in enumerate(HIERARCHY)],
    }


def row(i, *, action="RAISE", sizing=0.75, jam=False, sequence="BET", pos="IP"):
    r={
        "hand_id":f"h{i}",
        "source_split":"TRAIN",
        "profile":0,
        "street":"flop",
        "relative_position":pos,
        "pot_type":"SRP",
        "sequence":sequence,
        "facing_price_to_pot":0.5,
        "spr":3.0,
        "action":action,
        "is_jam":jam,
    }
    if action=="RAISE":
        r["raise_sizing_ratio"]=sizing
    return r


def training_rows():
    out=[]
    classes=[
        dict(sizing=2.0,jam=True),
        dict(sizing=0.8,jam=True),
        dict(sizing=2.0,jam=False),
        dict(sizing=1.2,jam=False),
        dict(sizing=0.75,jam=False),
    ]
    for i in range(50):
        out.append(row(i,**classes[i%len(classes)]))
    for i in range(50,80):
        out.append(row(i,action=("FOLD" if i%2 else "CALL")))
    return out


class TailClassTests(unittest.TestCase):
    def test_mutually_exclusive_tail_classes(self):
        self.assertEqual(tail_class(row(1,sizing=2.0,jam=True)),"JAM_OVERBET")
        self.assertEqual(tail_class(row(2,sizing=0.8,jam=True)),"JAM_NONOVERBET")
        self.assertEqual(tail_class(row(3,sizing=2.0,jam=False)),"LARGE_OVERBET_NONJAM")
        self.assertEqual(tail_class(row(4,sizing=1.2,jam=False)),"OVERBET_NONJAM")
        self.assertEqual(tail_class(row(5,sizing=0.8,jam=False)),"OTHER_RAISE")
        self.assertIsNone(tail_class(row(6,action="CALL")))


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.rows=training_rows()
        self.base=build_support_artifact(self.rows,graph=support_graph())

    def test_artifact_is_deterministic_train_only(self):
        a=build_artifact(self.rows,graph=tail_graph(),base_action_artifact=self.base)
        b=build_artifact(copy.deepcopy(self.rows),graph=tail_graph(),base_action_artifact=self.base)
        self.assertEqual(artifact_sha256(a),artifact_sha256(b))
        self.assertFalse(a["test_consumed"])
        self.assertEqual(a["fit_split"],"TRAIN")
        self.assertEqual(tuple(a["tail_classes"]),TAIL_CLASSES)

    def test_non_train_input_is_rejected(self):
        bad=training_rows()
        bad[0]["source_split"]="VALIDATION"
        with self.assertRaisesRegex(ValueError,"TRAIN observations only"):
            build_artifact(bad,graph=tail_graph(),base_action_artifact=self.base)

    def test_base_identity_is_enforced(self):
        doc=build_artifact(self.rows,graph=tail_graph(),base_action_artifact=self.base)
        other=copy.deepcopy(self.base)
        other["model_version"]="different"
        with self.assertRaisesRegex(ValueError,"identity mismatch"):
            AggressiveTailModel(doc,other)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        rows=training_rows()
        self.base_doc=build_support_artifact(rows,graph=support_graph())
        self.base=SupportAwareBackoffModel(self.base_doc)
        self.tail_doc=build_artifact(rows,graph=tail_graph(),base_action_artifact=self.base_doc)
        self.model=AggressiveTailModel(self.tail_doc,self.base_doc)

    def test_probabilities_are_explicit_and_normalized(self):
        t=self.model.tail_probabilities(**row(999))
        self.assertAlmostEqual(sum(t["class_probabilities"].values()),1.0,places=12)
        self.assertEqual(t["selected_level"]["index"],0)
        self.assertGreaterEqual(t["effective_support"]["raise_observations"],12)
        self.assertGreaterEqual(t["effective_support"]["distinct_raise_hands"],8)
        self.assertGreater(t["jam_conditional_on_raise"],0)
        self.assertGreater(t["overbet_conditional_on_raise"],0)

    def test_action_and_sizing_are_identical_to_base_286(self):
        probe=row(999,action="CALL")
        pbase=self.base.predict(**probe)
        ptail=self.model.predict(**probe)
        self.assertEqual(ptail["probabilities"],pbase["probabilities"])
        self.assertEqual(self.model.sizing_values(**probe),self.base.sizing_values(**probe))
        self.assertEqual(ptail["sizing"],pbase["sizing"])

    def test_distinct_hand_support_forces_declared_backoff(self):
        rows=[]
        for i in range(20):
            rows.append(row(i%3,sequence="RARE",sizing=2.0,jam=(i%2==0)))
        for i in range(40):
            rows.append(row(100+i,sequence="COMMON",pos="OOP",sizing=0.75))
        base=build_support_artifact(rows,graph=support_graph())
        doc=build_artifact(rows,graph=tail_graph(),base_action_artifact=base)
        model=AggressiveTailModel(doc,base)
        t=model.tail_probabilities(**row(999,sequence="RARE"))
        self.assertGreater(t["selected_level"]["index"],0)
        self.assertTrue(any(x["reason"]=="INSUFFICIENT_TRAIN_TAIL_SUPPORT" for x in t["failed_finer_levels"]))

    def test_high_price_is_aggressive_tail_by_frozen_metric_definition(self):
        probe=row(999)
        probe["facing_price_to_pot"]=2.0
        t=self.model.tail_probabilities(**probe)
        self.assertEqual(t["aggressive_tail_conditional_on_raise"],1.0)
        self.assertTrue(t["high_price_tail_forced_by_metric_definition"])


if __name__=="__main__":
    unittest.main()
