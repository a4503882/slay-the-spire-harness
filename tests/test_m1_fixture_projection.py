from __future__ import annotations

from pathlib import Path

from sts_harness.canonical import strict_json_loads
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "m1-runs"
    / "m1-20260904-170257-0075eb79"
    / "bridge-states.jsonl"
)


def test_real_m1_fixture_normalizes_without_player_visible_leaks() -> None:
    rows = [strict_json_loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    normalizer = StateNormalizer("ep_fixture", "native_fixture")
    kinds: list[str] = []
    for state_seq, row in enumerate(rows, start=1):
        observation = normalizer.normalize(row["raw"], state_seq)
        legal = build_legal_actions(row["raw"], observation).document
        rendered = repr(observation)
        assert "available_commands" not in rendered
        assert "last_move_id" not in rendered
        assert "second_last_move_id" not in rendered
        assert legal["observation_hash"] == observation["observation_hash"]
        kinds.append(observation["decision_kind"])
    assert {"main_menu", "event", "map", "combat"}.issubset(kinds)
