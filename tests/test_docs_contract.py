from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_observation_hash_is_documented_as_run_local_not_cross_run_parity() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    spec = (PROJECT_ROOT / "SPEC.md").read_text(encoding="utf-8")
    acceptance = (PROJECT_ROOT / "docs" / "H1A_ACCEPTANCE.md").read_text(
        encoding="utf-8"
    )

    assert "`observation_hash` is intentionally valid only inside one run" in readme
    assert "never as an H1-B cross-run replay checkpoint" in readme
    assert "`observation_hash` is deliberately **run-local**" in spec
    assert "Live replay MUST NOT compare `observation_hash` directly" in spec
    assert "separately versioned replay-checkpoint projection" in spec
    assert "It is not evidence of\ncross-run parity" in acceptance
