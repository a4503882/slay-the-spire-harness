from __future__ import annotations

from sts_harness.canonical import sha256_document
from sts_harness.environment import seal_environment


def test_sealed_environment_hashes_the_document_without_its_own_id() -> None:
    basis = {"schema_version": "sts-environment.v1", "game_sha256": "ABC"}
    sealed = seal_environment(basis)
    assert sealed["environment_fingerprint_id"] == sha256_document(basis)
    assert "environment_fingerprint_id" not in basis
