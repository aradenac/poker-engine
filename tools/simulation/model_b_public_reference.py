#!/usr/bin/env python3
"""Load the public-only Model-B behavior reference retained by issue #104.

Issue #104 fitted a card-aware candidate and a public-only reference on the same
TRAIN decisions. VALIDATION rejected the card-aware candidate. This adapter makes
that scientific decision executable without promoting the rejected candidate or
silently substituting another Model-B artifact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from tools.simulation.model_b_card_aware_runtime import BEHAVIOR_SCHEMA, CardAwareModelBPolicy

RESULT_SCHEMA = "independent-model-b-card-aware-result/v1"
RETAIN_DECISION = "RETAIN_PUBLIC_ONLY_REFERENCE_FOR_BEHAVIOR_COMPONENT"
REFERENCE_ARTIFACT_NAME = "public_reference_behavior.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RetainedPublicModelBPolicy(CardAwareModelBPolicy):
    """#104 runtime constrained to the selected public-only hierarchy."""

    def __init__(
        self,
        behavior: Mapping[str, Any],
        *,
        artifact_sha256: str,
        result_metadata: Mapping[str, Any],
    ) -> None:
        self.artifact_sha256 = str(artifact_sha256)
        self.result_metadata = dict(result_metadata)
        super().__init__(behavior)
        self._validate_public_only_contract()
        self.population_id = str(self.behavior.get("population_id") or "")
        if not self.population_id:
            raise ValueError("retained Model B behavior must name its population_id")

    def _validate_public_only_contract(self) -> None:
        if self.behavior.get("schema") != BEHAVIOR_SCHEMA:
            raise ValueError(f"unsupported retained Model B schema: {self.behavior.get('schema')!r}")
        for section in ("action", "sizing"):
            levels = self.behavior.get(section, {}).get("levels", [])
            if not levels:
                raise ValueError(f"retained Model B {section} hierarchy is empty")
            offenders = [
                list(level.get("cols", []))
                for level in levels
                if "hand_bucket" in level.get("cols", [])
            ]
            if offenders:
                raise ValueError(
                    f"retained public-only Model B unexpectedly conditions {section} on hand_bucket: {offenders}"
                )

    def identity(self) -> dict[str, Any]:
        validation = self.result_metadata.get("validation", {})
        action = validation.get("actions", {})
        sizing = validation.get("sizing", {})
        return {
            "schema": "retained-public-model-b-identity/v1",
            "source_issue": 104,
            "selection_decision": self.result_metadata.get("decision"),
            "population_id": self.population_id,
            "artifact": REFERENCE_ARTIFACT_NAME,
            "artifact_sha256": self.artifact_sha256,
            "test_consumed_by_issue_104": bool(self.result_metadata.get("test_consumed")),
            "candidate_action_log_loss_delta": action.get("delta"),
            "candidate_sizing_absolute_log_error_delta": (
                None
                if sizing.get("candidate_mean_absolute_log_error") is None
                or sizing.get("reference_mean_absolute_log_error") is None
                else float(sizing["candidate_mean_absolute_log_error"])
                - float(sizing["reference_mean_absolute_log_error"])
            ),
        }

    @classmethod
    def from_paths(cls, behavior_path: Path, result_path: Path) -> "RetainedPublicModelBPolicy":
        behavior_path = Path(behavior_path)
        result_path = Path(result_path)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("schema") != RESULT_SCHEMA:
            raise ValueError(f"unexpected #104 result schema: {result.get('schema')!r}")
        if result.get("decision") != RETAIN_DECISION:
            raise ValueError(
                f"#104 did not retain the public-only reference: {result.get('decision')!r}"
            )
        if result.get("test_consumed") is not False:
            raise ValueError("#104 selection must not consume TEST")
        if result.get("production_model_b_effect") != "NONE" or result.get("hero_strategy_effect") != "NONE":
            raise ValueError("#104 result unexpectedly authorizes production/Hero mutation")

        artifact_meta = result.get("candidate_artifacts", {}).get(REFERENCE_ARTIFACT_NAME)
        if not isinstance(artifact_meta, Mapping) or not artifact_meta.get("sha256"):
            raise ValueError(f"#104 result does not identify {REFERENCE_ARTIFACT_NAME}")
        actual_sha = sha256_file(behavior_path)
        if actual_sha != str(artifact_meta["sha256"]):
            raise ValueError(
                f"retained Model B artifact hash mismatch: expected {artifact_meta['sha256']}, got {actual_sha}"
            )
        if artifact_meta.get("size_bytes") is not None and behavior_path.stat().st_size != int(artifact_meta["size_bytes"]):
            raise ValueError("retained Model B artifact size does not match #104 evidence")

        behavior = json.loads(behavior_path.read_text(encoding="utf-8"))
        return cls(behavior, artifact_sha256=actual_sha, result_metadata=result)
