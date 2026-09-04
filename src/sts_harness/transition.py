from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .canonical import sha256_document
from .replay_checkpoint import build_replay_checkpoint


RAW_EXPORT_SCHEMA_VERSION = "sts-raw-export.v1"
REWARD_SCHEMA_VERSION = "sts-reward-vector.v1"
TRANSITION_SCHEMA_VERSION = "sts-transition.v1"
TRANSITION_HASH_SCHEMA_VERSION = "sts-transition-hash.v1"
CHAIN_HASH_SCHEMA_VERSION = "sts-transition-chain.v1"


class TransitionFailure(ValueError):
    pass


def _without_hash(document: dict[str, Any], field: str) -> dict[str, Any]:
    value = deepcopy(document)
    value.pop(field, None)
    return value


def recompute_document_hash(document: dict[str, Any], field: str) -> str:
    return sha256_document(_without_hash(document, field))


def _canonical_raw_value(value: Any, *, parent_key: str | None = None) -> Any:
    """Project a raw bridge export into the stable raw-export hash scope."""

    if isinstance(value, float):
        raise TransitionFailure("floating-point values are forbidden in raw hash state")
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TransitionFailure("raw export object keys must be strings")
            if key in {"uuid", "received_at", "transport_timestamp"}:
                continue
            result[key] = _canonical_raw_value(item, parent_key=key)
        return result
    if isinstance(value, list):
        result = [_canonical_raw_value(item, parent_key=parent_key) for item in value]
        if parent_key == "available_commands":
            if not all(isinstance(item, str) for item in result):
                raise TransitionFailure("available_commands must contain strings")
            return sorted(set(result))
        return result
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TransitionFailure(f"unsupported raw export value: {type(value).__name__}")


def canonical_raw_export(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TransitionFailure("raw export must be an object")
    return {
        "schema_version": RAW_EXPORT_SCHEMA_VERSION,
        "export": _canonical_raw_value(raw),
    }


def raw_export_hash(raw: dict[str, Any]) -> str:
    return sha256_document(canonical_raw_export(raw))


@dataclass(frozen=True)
class StateSnapshot:
    state_seq: int
    raw: dict[str, Any]
    raw_export_hash: str
    observation: dict[str, Any]
    legal_actions: dict[str, Any]

    @property
    def hashes(self) -> dict[str, str]:
        return {
            "raw_export_hash": self.raw_export_hash,
            "observation_hash": self.observation["observation_hash"],
            "legal_actions_hash": self.legal_actions["legal_actions_hash"],
        }


def make_snapshot(
    *,
    state_seq: int,
    raw: dict[str, Any],
    observation: dict[str, Any],
    legal_actions: dict[str, Any],
) -> StateSnapshot:
    if state_seq < 1:
        raise TransitionFailure("state_seq must be positive")
    if observation.get("state_seq") != state_seq or legal_actions.get("state_seq") != state_seq:
        raise TransitionFailure("snapshot state_seq fields do not agree")
    observation_hash = recompute_document_hash(observation, "observation_hash")
    if observation.get("observation_hash") != observation_hash:
        raise TransitionFailure("observation hash is invalid")
    legal_hash = recompute_document_hash(legal_actions, "legal_actions_hash")
    if legal_actions.get("legal_actions_hash") != legal_hash:
        raise TransitionFailure("legal-actions hash is invalid")
    if legal_actions.get("observation_hash") != observation_hash:
        raise TransitionFailure("legal actions reference a different observation")
    return StateSnapshot(
        state_seq=state_seq,
        raw=deepcopy(raw),
        raw_export_hash=raw_export_hash(raw),
        observation=deepcopy(observation),
        legal_actions=deepcopy(legal_actions),
    )


def _integer_at(observation: dict[str, Any], section: str, field: str) -> int | None:
    value = observation.get(section)
    if not isinstance(value, dict):
        return None
    item = value.get(field)
    return item if isinstance(item, int) and not isinstance(item, bool) else None


def reward_vector(
    previous: StateSnapshot | None,
    current: StateSnapshot,
    *,
    terminal: bool = False,
    outcome: str | None = None,
) -> dict[str, Any]:
    before = previous.observation if previous is not None else {}
    after = current.observation

    def delta(section: str, field: str) -> int:
        left = _integer_at(before, section, field)
        right = _integer_at(after, section, field)
        return 0 if left is None or right is None else right - left

    return {
        "schema_version": REWARD_SCHEMA_VERSION,
        "terminal": (
            1
            if terminal and isinstance(outcome, str) and outcome.startswith("VICTORY")
            else -1 if terminal and isinstance(outcome, str) and outcome.startswith("DEFEAT") else 0
        ),
        "floor_delta": delta("run", "floor"),
        "score_delta": None,
        "hp_delta": delta("run", "current_hp"),
        "max_hp_delta": delta("run", "max_hp"),
        "gold_delta": delta("run", "gold"),
    }


def transition_hash_basis(transition: dict[str, Any]) -> dict[str, Any]:
    if transition.get("schema_version") != TRANSITION_SCHEMA_VERSION:
        raise TransitionFailure("unexpected transition schema version")
    content = deepcopy(transition)
    hashes = content.pop("hashes", None)
    if not isinstance(hashes, dict):
        raise TransitionFailure("transition hashes object is missing")
    required_post_hashes = ("raw_export_hash", "observation_hash", "legal_actions_hash")
    if not all(isinstance(hashes.get(key), str) for key in required_post_hashes):
        raise TransitionFailure("transition post-state hashes are incomplete")
    content["post_hashes"] = {key: hashes[key] for key in required_post_hashes}
    content["hash_schema_version"] = TRANSITION_HASH_SCHEMA_VERSION
    return content


def compute_transition_hash(transition: dict[str, Any]) -> str:
    return sha256_document(transition_hash_basis(transition))


def compute_chain_hash(previous_chain_hash: str | None, transition_hash: str) -> str:
    return sha256_document(
        {
            "schema_version": CHAIN_HASH_SCHEMA_VERSION,
            "previous_chain_hash": previous_chain_hash,
            "transition_hash": transition_hash,
        }
    )


def build_transition(
    *,
    episode_id: str,
    transition_index: int,
    environment_fingerprint_id: str,
    previous: StateSnapshot | None,
    current: StateSnapshot,
    previous_chain_hash: str | None,
    submitted_batch: dict[str, Any] | None,
    action_results: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    terminal: bool = False,
    truncated: bool = False,
    outcome: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if transition_index < 0:
        raise TransitionFailure("transition_index cannot be negative")
    if current.observation.get("episode_id") != episode_id:
        raise TransitionFailure("current snapshot belongs to another episode")
    if previous is not None and previous.observation.get("episode_id") != episode_id:
        raise TransitionFailure("previous snapshot belongs to another episode")
    if terminal and truncated:
        raise TransitionFailure("a transition cannot be both terminal and truncated")

    transition: dict[str, Any] = {
        "schema_version": TRANSITION_SCHEMA_VERSION,
        "episode_id": episode_id,
        "environment_fingerprint_id": environment_fingerprint_id,
        "transition_index": transition_index,
        "state_seq": current.state_seq,
        "pre_hashes": previous.hashes if previous is not None else None,
        "observation": deepcopy(current.observation),
        "legal_actions": deepcopy(current.legal_actions),
        "replay_checkpoint": build_replay_checkpoint(
            current.observation,
            current.legal_actions,
        ),
        "events": deepcopy(events or []),
        "submitted_batch": deepcopy(submitted_batch),
        "action_results": deepcopy(action_results),
        "reward": reward_vector(previous, current, terminal=terminal, outcome=outcome),
        "terminal": terminal,
        "truncated": truncated,
        "outcome": outcome,
        "metrics": deepcopy(metrics or {}),
        "hashes": {
            **current.hashes,
            "replay_checkpoint_hash": None,
            "previous_chain_hash": previous_chain_hash,
            "transition_hash": None,
            "chain_hash": None,
        },
    }
    transition["hashes"]["replay_checkpoint_hash"] = transition[
        "replay_checkpoint"
    ]["replay_checkpoint_hash"]
    transition_hash = compute_transition_hash(transition)
    transition["hashes"]["transition_hash"] = transition_hash
    transition["hashes"]["chain_hash"] = compute_chain_hash(
        previous_chain_hash,
        transition_hash,
    )
    return transition
