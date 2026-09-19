#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from tools import repro_container
from tools import repro_environment_identity as identity


def clone_sources(destination: Path) -> Path:
    for relative in (
        ".python-version",
        ".node-version",
        "requirements.lock.txt",
        "package-lock.json",
        "package.json",
        "reproducibility/environment.lock.json",
        "reproducibility/os-base.lock.json",
        "reproducibility/container-base.lock.json",
        "reproducibility/system-packages.apt.txt",
        "reproducibility/Dockerfile.science",
    ):
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


def edit_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class ContainerReproTests(unittest.TestCase):
    def test_repository_contract_and_manifest_are_stable(self) -> None:
        first = repro_container.materialize_manifest(ROOT)
        second = repro_container.materialize_manifest(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(
            first["manifest_sha256"],
            repro_container.manifest_sha256(first),
        )
        self.assertEqual("linux/amd64", first["base_image"]["platform"])
        self.assertTrue(
            first["base_image"]["manifest_digest"].startswith("sha256:")
        )
        self.assertFalse(first["system_packages"]["fully_pinned"])

    def test_digest_is_required_and_tag_only_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = clone_sources(Path(tmp))
            edit_json(
                root / "reproducibility/container-base.lock.json",
                lambda x: x["image"].pop("manifest_digest"),
            )
            with self.assertRaisesRegex(
                repro_container.ContainerContractError,
                "digest is required",
            ):
                repro_container.materialize_manifest(root)

    def test_wrong_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = clone_sources(Path(tmp))

            def mutate(data: dict) -> None:
                data["image"]["manifest_digest"] = "sha256:" + "0" * 64

            edit_json(
                root / "reproducibility/container-base.lock.json",
                mutate,
            )
            with self.assertRaisesRegex(
                repro_container.ContainerContractError,
                "verified manifest digest",
            ):
                repro_container.materialize_manifest(root)

    def test_architecture_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = clone_sources(Path(tmp))
            edit_json(
                root / "reproducibility/container-base.lock.json",
                lambda x: x["image"].update({"platform": "linux/arm64"}),
            )
            with self.assertRaisesRegex(
                repro_container.ContainerContractError,
                "linux/amd64",
            ):
                repro_container.materialize_manifest(root)

    def test_container_definition_change_changes_manifest_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = clone_sources(Path(tmp))
            before_manifest = repro_container.materialize_manifest(root)
            before_identity = identity.materialize_identity(root)

            dockerfile = root / "reproducibility/Dockerfile.science"
            dockerfile.write_text(
                dockerfile.read_text(encoding="utf-8")
                + "\n# synthetic definition change\n",
                encoding="utf-8",
            )

            after_manifest = repro_container.materialize_manifest(root)
            after_identity = identity.materialize_identity(root)

            self.assertNotEqual(
                before_manifest["definition"]["sha256"],
                after_manifest["definition"]["sha256"],
            )
            self.assertNotEqual(
                before_manifest["manifest_sha256"],
                after_manifest["manifest_sha256"],
            )
            self.assertNotEqual(
                before_identity["identity_sha256"],
                after_identity["identity_sha256"],
            )

    def test_container_lock_change_changes_manifest_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = clone_sources(Path(tmp))
            before_manifest = repro_container.materialize_manifest(root)
            before_identity = identity.materialize_identity(root)

            edit_json(
                root / "reproducibility/container-base.lock.json",
                lambda x: x["verification"].update(
                    {"note": "synthetic provenance metadata"}
                ),
            )

            after_manifest = repro_container.materialize_manifest(root)
            after_identity = identity.materialize_identity(root)

            self.assertNotEqual(
                before_manifest["locks"]["container_base_lock_sha256"],
                after_manifest["locks"]["container_base_lock_sha256"],
            )
            self.assertNotEqual(
                before_manifest["manifest_sha256"],
                after_manifest["manifest_sha256"],
            )
            self.assertNotEqual(
                before_identity["identity_sha256"],
                after_identity["identity_sha256"],
            )

    def test_missing_verification_provenance_never_infers_a_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = clone_sources(Path(tmp))
            edit_json(
                root / "reproducibility/container-base.lock.json",
                lambda x: x.pop("verification"),
            )
            with self.assertRaisesRegex(
                repro_container.ContainerContractError,
                "verification provenance",
            ):
                repro_container.materialize_manifest(root)

    def test_system_package_contract_is_explicitly_not_fully_pinned(self) -> None:
        manifest = repro_container.materialize_manifest(ROOT)
        self.assertTrue(manifest["hermeticity"]["base_image_pinned"])
        self.assertFalse(
            manifest["hermeticity"]["system_packages_fully_pinned"]
        )
        self.assertIsNone(manifest["hermeticity"]["apt_snapshot"])

    def test_grandfathered_historical_run_policy_is_unchanged(self) -> None:
        historical = {"schema": "historical-run/v1"}
        self.assertTrue(
            identity.validate_run_manifest(
                historical,
                ROOT,
                grandfather_historical=False,
            )
        )
        self.assertEqual(
            [],
            identity.validate_run_manifest(
                historical,
                ROOT,
                grandfather_historical=True,
            ),
        )


if __name__ == "__main__":
    unittest.main()
