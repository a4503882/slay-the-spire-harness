from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from sts_harness.canonical import append_jsonl, atomic_write_json, sha256_document
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.replay_verify import ReplayVerificationFailure, verify_offline_replay
from sts_harness.transition import build_transition, make_snapshot

from test_legal_actions import combat_raw


def _fixture_trace(run_dir: Path) -> None:
    environment = {
        "schema_version": "sts-environment.v1",
        "game_sha256": "sha256:game",
    }
    environment["environment_fingerprint_id"] = sha256_document(environment)
    atomic_write_json(run_dir / "environment.json", environment)

    raw = combat_raw()
    normalizer = StateNormalizer("ep_test", "native_test")
    observation = normalizer.normalize(raw, 1)
    legal = build_legal_actions(raw, observation)
    snapshot = make_snapshot(
        state_seq=1,
        raw=raw,
        observation=observation,
        legal_actions=legal.document,
    )
    append_jsonl(
        run_dir / "raw-states.jsonl",
        {
            "schema_version": "sts-raw-state-record.v1",
            "state_seq": 1,
            "raw_export_hash": snapshot.raw_export_hash,
            "raw": raw,
            "non_benchmark": True,
        },
    )
    append_jsonl(
        run_dir / "transitions.jsonl",
        build_transition(
            episode_id="ep_test",
            transition_index=0,
            environment_fingerprint_id=environment["environment_fingerprint_id"],
            previous=None,
            current=snapshot,
            previous_chain_hash=None,
            submitted_batch=None,
            action_results=[],
        ),
    )


def test_offline_replay_recomputes_full_trace(tmp_path: Path) -> None:
    _fixture_trace(tmp_path)
    result = verify_offline_replay(tmp_path)
    assert result["status"] == "REPLAY_VALID"
    assert result["transition_count"] == 1
    assert result["raw_state_count"] == 1


def test_offline_replay_rejects_modified_transition(tmp_path: Path) -> None:
    _fixture_trace(tmp_path)
    path = tmp_path / "transitions.jsonl"
    transition = __import__("json").loads(path.read_text(encoding="utf-8"))
    transition["action_results"] = [{"status": "forged"}]
    path.write_text(__import__("json").dumps(transition), encoding="utf-8")
    with pytest.raises(ReplayVerificationFailure, match="transition hash mismatch"):
        verify_offline_replay(tmp_path)


def test_offline_replay_rejects_reordered_raw_rows(tmp_path: Path) -> None:
    _fixture_trace(tmp_path)
    path = tmp_path / "raw-states.jsonl"
    row = __import__("json").loads(path.read_text(encoding="utf-8"))
    row["state_seq"] = 2
    path.write_text(__import__("json").dumps(row), encoding="utf-8")
    with pytest.raises(ReplayVerificationFailure, match="raw state sequence mismatch"):
        verify_offline_replay(tmp_path)
