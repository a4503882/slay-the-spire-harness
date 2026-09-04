from __future__ import annotations

import hmac
import os
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .action_verify import verify_action_effect
from .canonical import append_jsonl, atomic_write_json, sha256_document
from .legal_actions import (
    ActionValidationFailure,
    LegalActionSnapshot,
    NativeAction,
    build_legal_actions,
    resolve_planned_action,
    validate_action_submission,
)
from .observation import FAIRNESS_PROFILE, StateNormalizer
from .metrics import EpisodeMetrics
from .rpc_protocol import RpcFailure
from .transition import StateSnapshot, build_transition, make_snapshot, raw_export_hash


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeFailure(RuntimeError):
    pass


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _combat_completed_between(
    before_observation: dict[str, Any],
    after_observation: dict[str, Any],
) -> bool:
    return before_observation.get("combat") is not None and (
        after_observation.get("combat") is None
        or after_observation.get("decision_kind") in {"game_over", "victory"}
    )


class H1Runtime:
    READ_METHODS = {
        "ping",
        "capabilities",
        "bridge.status",
        "observe",
        "env.observe",
        "get_legal_actions",
        "env.replay",
    }
    MUTATING_METHODS = {"env.reset", "env.step", "submit_action", "env.close", "quit"}

    def __init__(
        self,
        *,
        run_dir: Path,
        episode_id: str,
        native_session_id: str,
        environment_fingerprint_id: str,
        controller_nonce: str,
        command_sink: Callable[[str], None],
        state_timeout_seconds: float = 30.0,
    ) -> None:
        self.run_dir = run_dir.resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.episode_id = episode_id
        self.native_session_id = native_session_id
        self.environment_fingerprint_id = environment_fingerprint_id
        self._controller_nonce = controller_nonce
        self._command_sink = command_sink
        self._state_timeout_seconds = state_timeout_seconds
        self._normalizer = StateNormalizer(episode_id, native_session_id)
        self._condition = threading.Condition(threading.RLock())
        self._mutation_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._snapshot: StateSnapshot | None = None
        self._legal_snapshot: LegalActionSnapshot | None = None
        self._latest_transition: dict[str, Any] | None = None
        self._transition_index = 0
        self._raw_receive_count = 0
        self._duplicate_state_count = 0
        self._bridge_error_count = 0
        self._bridge_error_generation = 0
        self._latest_bridge_error: str | None = None
        self._fatal_error: str | None = None
        self._reset_called = False
        self._closed = False
        self._abort_requested = False
        self._close_response_sent = False
        self._close_wakeup_after_receive_count: int | None = None
        self._started_at = utc_now()
        self._episode_started_monotonic: float | None = None
        self._max_episode_decisions = 10_000
        self._max_episode_seconds = 14_400
        self._actions_attempted = 0
        self._actions_accepted = 0
        self._actions_unverified = 0
        self._actions_rejected = 0
        self._actions_skipped = 0
        self._partial_batch_count = 0
        self._unsupported_screen_count = 0
        self._metrics = EpisodeMetrics()

    @property
    def close_requested(self) -> bool:
        with self._condition:
            return self._closed

    @property
    def close_wakeup_observed(self) -> bool:
        with self._condition:
            threshold = self._close_wakeup_after_receive_count
            return threshold is not None and self._raw_receive_count > threshold

    @property
    def abort_requested(self) -> bool:
        with self._condition:
            return self._abort_requested

    def _event(self, event: str, **details: Any) -> None:
        append_jsonl(
            self.run_dir / "bridge-events.jsonl",
            {
                "schema_version": "sts-bridge-event.v1",
                "recorded_at": utc_now(),
                "event": event,
                **details,
            },
        )

    def ingest_bridge_document(self, document: dict[str, Any]) -> None:
        with self._condition:
            self._raw_receive_count += 1
            receive_index = self._raw_receive_count
            if not isinstance(document, dict):
                self._fatal_error = "bridge document is not an object"
                self._condition.notify_all()
                return
            if isinstance(document.get("error"), str):
                self._bridge_error_count += 1
                self._bridge_error_generation += 1
                self._latest_bridge_error = document["error"]
                self._event(
                    "native_command_error",
                    receive_index=receive_index,
                    error=document["error"],
                    ready_for_command=document.get("ready_for_command"),
                )
                self._condition.notify_all()
                return
            try:
                candidate_raw_hash = raw_export_hash(document)
                if self._snapshot is not None and candidate_raw_hash == self._snapshot.raw_export_hash:
                    self._duplicate_state_count += 1
                    self._event(
                        "duplicate_stable_state",
                        receive_index=receive_index,
                        state_seq=self._snapshot.state_seq,
                        raw_export_hash=candidate_raw_hash,
                    )
                    self._condition.notify_all()
                    return
                state_seq = 1 if self._snapshot is None else self._snapshot.state_seq + 1
                observation = self._normalizer.normalize(document, state_seq)
                legal_snapshot = build_legal_actions(document, observation)
                snapshot = make_snapshot(
                    state_seq=state_seq,
                    raw=document,
                    observation=observation,
                    legal_actions=legal_snapshot.document,
                )
                append_jsonl(
                    self.run_dir / "raw-states.jsonl",
                    {
                        "schema_version": "sts-raw-state-record.v1",
                        "received_at": utc_now(),
                        "receive_index": receive_index,
                        "state_seq": state_seq,
                        "raw_export_hash": snapshot.raw_export_hash,
                        "raw": document,
                        "non_benchmark": True,
                    },
                )
                self._snapshot = snapshot
                self._legal_snapshot = legal_snapshot
                if self._reset_called:
                    self._metrics.observe_snapshot(snapshot)
                self._latest_bridge_error = None
                if observation.get("decision_kind") == "unsupported":
                    self._unsupported_screen_count += 1
                    self._event(
                        "unsupported_screen",
                        receive_index=receive_index,
                        state_seq=state_seq,
                        native_screen_type=_dict(observation.get("screen")).get(
                            "native_screen_type"
                        ),
                    )
                self._event(
                    "stable_state",
                    receive_index=receive_index,
                    state_seq=state_seq,
                    decision_kind=observation.get("decision_kind"),
                    observation_hash=observation["observation_hash"],
                )
            except Exception as exc:
                self._fatal_error = f"{type(exc).__name__}: {exc}"
                self._event("normalization_failure", receive_index=receive_index, error=self._fatal_error)
            self._condition.notify_all()

    def _wait_for_snapshot(self, *, after_state_seq: int | None = None) -> StateSnapshot:
        deadline = time.monotonic() + self._state_timeout_seconds
        starting_error_generation = self._bridge_error_generation
        with self._condition:
            while True:
                if self._fatal_error is not None:
                    raise RuntimeFailure(self._fatal_error)
                if self._bridge_error_generation > starting_error_generation:
                    raise RuntimeFailure(f"native bridge rejected command: {self._latest_bridge_error}")
                if self._snapshot is not None and (
                    after_state_seq is None or self._snapshot.state_seq > after_state_seq
                ):
                    return self._snapshot
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeFailure("timed out waiting for a distinct stable bridge state")
                self._condition.wait(remaining)

    def _write_command(self, command: str) -> None:
        with self._command_lock:
            self._command_sink(command)

    def _command_and_wait(self, command: str, before: StateSnapshot) -> StateSnapshot:
        starting_error_generation = self._bridge_error_generation
        self._event(
            "native_command_sent",
            state_seq=before.state_seq,
            command_type=command.split(" ", 1)[0],
        )
        self._write_command(command)
        deadline = time.monotonic() + self._state_timeout_seconds
        with self._condition:
            while True:
                if self._fatal_error is not None:
                    raise RuntimeFailure(self._fatal_error)
                if self._bridge_error_generation > starting_error_generation:
                    raise RuntimeFailure(f"native bridge rejected command: {self._latest_bridge_error}")
                if self._snapshot is not None and self._snapshot.state_seq > before.state_seq:
                    return self._snapshot
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeFailure("timed out waiting for action post-state")
                self._condition.wait(remaining)

    def _verify_action_with_settle(
        self,
        native: NativeAction,
        before: StateSnapshot,
        first_after: StateSnapshot,
    ) -> tuple[StateSnapshot, bool, dict[str, Any]]:
        """Allow a bounded later native state to complete an action proof.

        The bridge normally exposes only stable states, but native reward and
        relic animations can publish one intermediate screen transition before
        their persistent effect becomes observable. The success criterion is
        unchanged: a later distinct state must satisfy the same independent
        action verifier. No failed proof is promoted merely because time passed.
        """
        latest = first_after
        verified, proof = verify_action_effect(native, before, latest)
        attempts = 1
        deadline = time.monotonic() + min(5.0, self._state_timeout_seconds)
        while not verified:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                settled_proof = deepcopy(proof)
                settled_proof["verification_attempts"] = attempts
                settled_proof["initial_post_state_seq"] = first_after.state_seq
                settled_proof["settled_post_state_seq"] = latest.state_seq
                return latest, False, settled_proof
            # Give a naturally published final state a brief opportunity first.
            # If none arrives, request a read-only bridge snapshot. Duplicate
            # snapshots advance receive_count but do not mint a fake state_seq.
            time.sleep(min(0.25, remaining))
            with self._condition:
                if self._fatal_error is not None:
                    raise RuntimeFailure(self._fatal_error)
                if self._snapshot is not None and self._snapshot.state_seq > latest.state_seq:
                    latest = self._snapshot
                    attempts += 1
                    verified, proof = verify_action_effect(native, before, latest)
                    continue
                receive_count = self._raw_receive_count
                error_generation = self._bridge_error_generation
            self._event(
                "action_settle_state_probe",
                action_type=native.action_type,
                pre_state_seq=before.state_seq,
                latest_state_seq=latest.state_seq,
                attempt=attempts + 1,
            )
            self._write_command("state")
            with self._condition:
                while self._raw_receive_count <= receive_count:
                    if self._fatal_error is not None:
                        raise RuntimeFailure(self._fatal_error)
                    if self._bridge_error_generation > error_generation:
                        raise RuntimeFailure(
                            f"native bridge rejected settle probe: {self._latest_bridge_error}"
                        )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        settled_proof = deepcopy(proof)
                        settled_proof["verification_attempts"] = attempts
                        settled_proof["initial_post_state_seq"] = first_after.state_seq
                        settled_proof["settled_post_state_seq"] = latest.state_seq
                        return latest, False, settled_proof
                    self._condition.wait(remaining)
                if self._snapshot is not None:
                    latest = self._snapshot
            attempts += 1
            verified, proof = verify_action_effect(native, before, latest)
        settled_proof = deepcopy(proof)
        if attempts > 1:
            settled_proof["verification_attempts"] = attempts
            settled_proof["initial_post_state_seq"] = first_after.state_seq
            settled_proof["settled_post_state_seq"] = latest.state_seq
        return latest, True, settled_proof

    @staticmethod
    def _exact_params(params: dict[str, Any], allowed: set[str], required: set[str]) -> None:
        unknown = set(params) - allowed
        missing = required - set(params)
        if unknown:
            raise RpcFailure(-32602, "Invalid params", {"unknown_fields": sorted(unknown)})
        if missing:
            raise RpcFailure(-32602, "Invalid params", {"missing_fields": sorted(missing)})

    def _check_identity(self, params: dict[str, Any], snapshot: StateSnapshot) -> None:
        expected = {
            "episode_id": self.episode_id,
            "native_session_id": self.native_session_id,
            "run_id": snapshot.observation.get("run_id"),
            "expected_decision_id": snapshot.observation.get("decision_id"),
            "expected_observation_hash": snapshot.observation.get("observation_hash"),
            "expected_legal_actions_hash": snapshot.legal_actions.get("legal_actions_hash"),
        }
        mismatches = {
            key: {"expected": value, "received": params.get(key)}
            for key, value in expected.items()
            if params.get(key) != value
        }
        if mismatches:
            raise RpcFailure(-32011, "STALE_OR_FOREIGN_DECISION", mismatches)

    def _record_transition(
        self,
        *,
        previous: StateSnapshot | None,
        current: StateSnapshot,
        submitted_batch: dict[str, Any] | None,
        action_results: list[dict[str, Any]],
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        prior_chain = (
            self._latest_transition["hashes"]["chain_hash"]
            if self._latest_transition is not None
            else None
        )
        decision_kind = current.observation.get("decision_kind")
        transition_events = deepcopy(events or [])
        terminal = decision_kind in {"game_over", "victory"}
        truncated = decision_kind == "unsupported"
        run = current.observation.get("run")
        outcome = run.get("outcome") if isinstance(run, dict) else None
        if truncated:
            outcome = "FAILED_UNSUPPORTED_SCREEN"
            transition_events.append(
                {
                    "type": "UNSUPPORTED_SCREEN",
                    "native_screen_type": _dict(current.observation.get("screen")).get(
                        "native_screen_type"
                    ),
                }
            )
        transition = build_transition(
            episode_id=self.episode_id,
            transition_index=self._transition_index,
            environment_fingerprint_id=self.environment_fingerprint_id,
            previous=previous,
            current=current,
            previous_chain_hash=prior_chain,
            submitted_batch=submitted_batch,
            action_results=action_results,
            events=transition_events,
            terminal=terminal,
            truncated=truncated,
            outcome=outcome,
            metrics={
                "raw_receive_count": self._raw_receive_count,
                "duplicate_state_count": self._duplicate_state_count,
                "actions_attempted": self._actions_attempted,
                "actions_accepted": self._actions_accepted,
                "actions_unverified": self._actions_unverified,
                "actions_rejected": self._actions_rejected,
                "actions_skipped": self._actions_skipped,
                "partial_batch_count": self._partial_batch_count,
                "unsupported_screen_count": self._unsupported_screen_count,
            },
        )
        append_jsonl(self.run_dir / "transitions.jsonl", transition)
        self._latest_transition = transition
        self._transition_index += 1
        return deepcopy(transition)

    def reset(self, params: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "character_id",
            "ascension",
            "seed",
            "fairness_profile",
            "policy_mode",
            "max_episode_decisions",
            "max_episode_seconds",
        }
        self._exact_params(params, allowed, allowed)
        if params.get("character_id") != "IRONCLAD" or params.get("ascension") != 0:
            raise RpcFailure(-32602, "H1-A supports only IRONCLAD ascension 0")
        seed = params.get("seed")
        if not isinstance(seed, str) or re.fullmatch(r"[A-Za-z0-9]+", seed) is None:
            raise RpcFailure(-32602, "seed must match ^[A-Za-z0-9]+$")
        if params.get("fairness_profile") != FAIRNESS_PROFILE:
            raise RpcFailure(-32602, "unsupported fairness profile")
        if params.get("policy_mode") not in {"scripted", "scripted_greedy", "scripted_replay"}:
            raise RpcFailure(-32602, "unsupported scripted policy mode")
        max_decisions = params.get("max_episode_decisions")
        max_seconds = params.get("max_episode_seconds")
        if not isinstance(max_decisions, int) or isinstance(max_decisions, bool) or not 1 <= max_decisions <= 10_000:
            raise RpcFailure(-32602, "max_episode_decisions must be an integer in [1, 10000]")
        if not isinstance(max_seconds, int) or isinstance(max_seconds, bool) or not 1 <= max_seconds <= 14_400:
            raise RpcFailure(-32602, "max_episode_seconds must be an integer in [1, 14400]")

        with self._mutation_lock:
            if self._reset_called:
                raise RpcFailure(-32010, "RESET_ALREADY_USED")
            if self._closed:
                raise RpcFailure(-32012, "EPISODE_CLOSED")
            menu = self._wait_for_snapshot()
            if menu.observation.get("decision_kind") != "main_menu":
                raise RpcFailure(-32013, "RESET_REQUIRES_MAIN_MENU")
            legal = self._legal_snapshot
            if legal is None or not legal.document.get("templates"):
                raise RpcFailure(-32014, "START_RUN_NOT_AVAILABLE")
            self._reset_called = True
            self._max_episode_decisions = max_decisions
            self._max_episode_seconds = max_seconds
            self._episode_started_monotonic = time.monotonic()
            self._metrics.configure(seed=seed.upper(), policy_mode=str(params["policy_mode"]))
            try:
                current = self._command_and_wait(f"start ironclad 0 {seed.upper()}", menu)
            except Exception:
                self._reset_called = False
                raise
            run = current.observation.get("run")
            if not isinstance(run, dict) or run.get("character_id") != "IRONCLAD" or run.get("ascension") != 0:
                raise RpcFailure(-32015, "START_RUN_UNVERIFIED")
            return self._record_transition(
                previous=None,
                current=current,
                submitted_batch=None,
                action_results=[],
                events=[{"type": "episode_reset", "seed": seed.upper()}],
            )

    def step(self, params: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "episode_id",
            "native_session_id",
            "run_id",
            "expected_decision_id",
            "expected_observation_hash",
            "expected_legal_actions_hash",
            "actions",
            "request_id",
            "stop_on_failure",
        }
        required = allowed - {"request_id", "stop_on_failure"}
        self._exact_params(params, allowed, required)
        with self._mutation_lock:
            if not self._reset_called:
                raise RpcFailure(-32016, "EPISODE_NOT_RESET")
            if self._closed:
                raise RpcFailure(-32012, "EPISODE_CLOSED")
            before = self._wait_for_snapshot()
            self._check_identity(params, before)
            if before.observation.get("decision_kind") == "unsupported":
                raise RpcFailure(-32022, "UNSUPPORTED_SCREEN")
            if before.observation.get("decision_kind") in {"game_over", "victory"}:
                raise RpcFailure(-32023, "EPISODE_TERMINAL")
            actions = params.get("actions")
            if not isinstance(actions, list) or not 1 <= len(actions) <= 12:
                raise RpcFailure(-32602, "action batch size must be in [1, 12]")
            if params.get("stop_on_failure", True) is not True:
                raise RpcFailure(-32602, "stop_on_failure must be true in v1")
            if self._actions_attempted >= self._max_episode_decisions:
                raise RpcFailure(-32017, "TRUNCATED_DECISION_LIMIT")
            if self._episode_started_monotonic is not None and (
                time.monotonic() - self._episode_started_monotonic > self._max_episode_seconds
            ):
                raise RpcFailure(-32018, "TRUNCATED_TIME_LIMIT")
            batch = {
                "schema_version": "sts-action-batch.v1",
                "batch_id": f"batch_{self._transition_index:06d}",
                "request_id": params.get("request_id"),
                "stop_on_failure": True,
                "actions": deepcopy(actions),
            }
            current = before
            results: list[dict[str, Any]] = []
            events: list[dict[str, Any]] = []
            stop_reason: str | None = None
            for action_index, submission in enumerate(actions):
                if self._actions_attempted >= self._max_episode_decisions:
                    stop_reason = "TRUNCATED_DECISION_LIMIT"
                    break
                legal_snapshot = self._legal_snapshot
                if legal_snapshot is None:
                    stop_reason = "NO_LEGAL_ACTION_SNAPSHOT"
                    break
                self._actions_attempted += 1
                try:
                    native: NativeAction = (
                        validate_action_submission(submission, legal_snapshot)
                        if action_index == 0
                        else resolve_planned_action(submission, legal_snapshot)
                    )
                except ActionValidationFailure as exc:
                    self._actions_rejected += 1
                    rejection = {
                        "schema_version": "sts-action-result.v1",
                        "requested_action_id": submission.get("action_id") if isinstance(submission, dict) else None,
                        "resolved_action_id": None,
                        "type": submission.get("type") if isinstance(submission, dict) else None,
                        "status": "rejected",
                        "code": "ACTION_NOT_LEGAL",
                        "native_accepted": False,
                        "verified": False,
                        "reason": str(exc),
                        "pre_state_seq": current.state_seq,
                    }
                    append_jsonl(
                        self.run_dir / "actions.jsonl",
                        {
                            "schema_version": "sts-action-audit.v1",
                            "recorded_at": utc_now(),
                            "batch_id": batch["batch_id"],
                            "action_index": action_index,
                            "state_seq": current.state_seq,
                            "decision_id": current.observation.get("decision_id"),
                            "status": "rejected",
                            "reason": "ACTION_NOT_LEGAL",
                            "detail": str(exc),
                            "submission": submission,
                            "result": rejection,
                        },
                    )
                    if not results:
                        raise RpcFailure(-32020, "ACTION_NOT_LEGAL", {"detail": str(exc)}) from exc
                    results.append(rejection)
                    stop_reason = "ACTION_NOT_LEGAL"
                    break

                action_before = current
                try:
                    after = self._command_and_wait(native.command, action_before)
                except Exception as exc:
                    failure = {
                        "schema_version": "sts-action-result.v1",
                        "requested_action_id": submission.get("action_id") if isinstance(submission, dict) else None,
                        "resolved_action_id": native.action_id,
                        "type": native.action_type,
                        "selector": deepcopy(native.selector),
                        "status": "native_failed",
                        "code": "NATIVE_ACTION_FAILED",
                        "native_accepted": False,
                        "verified": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "pre_state_seq": action_before.state_seq,
                    }
                    append_jsonl(
                        self.run_dir / "actions.jsonl",
                        {
                            "schema_version": "sts-action-audit.v1",
                            "recorded_at": utc_now(),
                            "batch_id": batch["batch_id"],
                            "action_index": action_index,
                            "state_seq": action_before.state_seq,
                            "decision_id": action_before.observation.get("decision_id"),
                            "status": "native_failed",
                            "submission": submission,
                            "native_command": native.command,
                            "result": failure,
                        },
                    )
                    if not results:
                        raise RpcFailure(-32021, "NATIVE_ACTION_FAILED", {"detail": str(exc)}) from exc
                    results.append(failure)
                    stop_reason = "NATIVE_ACTION_FAILED"
                    break

                after, verified, proof = self._verify_action_with_settle(
                    native,
                    action_before,
                    after,
                )
                if verified:
                    self._actions_accepted += 1
                    status = "accepted"
                    code = "ACTION_VERIFIED"
                else:
                    self._actions_unverified += 1
                    status = "unverified"
                    code = "ACTION_UNVERIFIED"
                action_result = {
                    "schema_version": "sts-action-result.v1",
                    "requested_action_id": submission.get("action_id"),
                    "resolved_action_id": native.action_id,
                    "action_id": native.action_id,
                    "type": native.action_type,
                    "selector": deepcopy(native.selector),
                    "status": status,
                    "code": code,
                    "native_accepted": True,
                    "native_command_hash": sha256_document(
                        {
                            "schema_version": "sts-native-command-hash.v1",
                            "command": native.command,
                        }
                    ),
                    "verified": verified,
                    "proof": proof,
                }
                results.append(action_result)
                append_jsonl(
                    self.run_dir / "actions.jsonl",
                    {
                        "schema_version": "sts-action-audit.v1",
                        "recorded_at": utc_now(),
                        "batch_id": batch["batch_id"],
                        "action_index": action_index,
                        "state_seq": action_before.state_seq,
                        "decision_id": action_before.observation.get("decision_id"),
                        "status": status,
                        "submission": submission,
                        "resolved_action_id": native.action_id,
                        "selector": deepcopy(native.selector),
                        "native_command": native.command,
                        "result": action_result,
                        "post_state_seq": after.state_seq,
                    },
                )
                current = after
                if _combat_completed_between(
                    action_before.observation,
                    after.observation,
                ):
                    events.append({"type": "combat_completed", "combat_id": action_before.observation.get("combat_id")})
                if not verified:
                    stop_reason = "ACTION_UNVERIFIED"
                    break
                if after.observation.get("decision_kind") in {"game_over", "victory"}:
                    stop_reason = "EPISODE_TERMINAL"
                    break
                if after.observation.get("decision_kind") == "unsupported":
                    stop_reason = "UNSUPPORTED_SCREEN"
                    break
                if after.observation.get("room_id") != action_before.observation.get("room_id"):
                    stop_reason = "ROOM_CHANGED"
                    break

            attempted_or_resolved = len(results)
            if attempted_or_resolved < len(actions):
                reason = stop_reason or "BATCH_STOPPED"
                for skipped_index in range(attempted_or_resolved, len(actions)):
                    submission = actions[skipped_index]
                    self._actions_skipped += 1
                    results.append(
                        {
                            "schema_version": "sts-action-result.v1",
                            "requested_action_id": submission.get("action_id") if isinstance(submission, dict) else None,
                            "resolved_action_id": None,
                            "type": submission.get("type") if isinstance(submission, dict) else None,
                            "status": "skipped",
                            "code": "ACTION_SKIPPED",
                            "native_accepted": False,
                            "verified": False,
                            "reason": reason,
                        }
                    )
            if len(actions) > 1 and any(result.get("status") != "accepted" for result in results):
                self._partial_batch_count += 1
                events.append({"type": "ACTION_PARTIAL_SUCCESS", "reason": stop_reason})
            for result in results:
                self._metrics.observe_action_result(result)
            self._metrics.observe_events(events)
            return self._record_transition(
                previous=before,
                current=current,
                submitted_batch=batch,
                action_results=results,
                events=events,
            )

    def observe(self) -> dict[str, Any]:
        with self._condition:
            if self._latest_transition is None:
                raise RpcFailure(-32016, "EPISODE_NOT_RESET")
            return deepcopy(self._latest_transition)

    def legal_actions(self) -> dict[str, Any]:
        with self._condition:
            if not self._reset_called or self._legal_snapshot is None:
                raise RpcFailure(-32016, "EPISODE_NOT_RESET")
            return deepcopy(self._legal_snapshot.document)

    def close(self, params: dict[str, Any]) -> dict[str, Any]:
        allowed = {"episode_id", "native_session_id", "run_id"}
        self._exact_params(params, allowed, {"episode_id", "native_session_id"})
        if params.get("episode_id") != self.episode_id or params.get("native_session_id") != self.native_session_id:
            raise RpcFailure(-32011, "STALE_OR_FOREIGN_EPISODE")
        with self._condition:
            if self._closed:
                return {"episode_id": self.episode_id, "close_requested": True, "idempotent": True}
            if self._snapshot is not None and params.get("run_id") != self._snapshot.observation.get("run_id"):
                raise RpcFailure(-32011, "STALE_OR_FOREIGN_EPISODE")
            self._closed = True
            self._condition.notify_all()
        return {"episode_id": self.episode_id, "close_requested": True, "idempotent": False}

    def abort(self, params: dict[str, Any]) -> dict[str, Any]:
        """Authenticated lifecycle stop for failures before a run identity exists."""
        self._exact_params(params, set(), set())
        with self._condition:
            idempotent = self._closed
            self._closed = True
            self._abort_requested = True
            self._condition.notify_all()
        return {
            "episode_id": self.episode_id,
            "close_requested": True,
            "idempotent": idempotent,
            "aborted": True,
        }

    def mark_close_response_sent(self) -> None:
        with self._condition:
            if not self._closed or self._close_response_sent:
                return
            self._close_response_sent = True
            self._close_wakeup_after_receive_count = self._raw_receive_count
            aborted = self._abort_requested
        if aborted:
            return
        self._write_command("state")

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method not in self.READ_METHODS | self.MUTATING_METHODS:
            raise RpcFailure(-32601, "Method not found")
        call_params = dict(params)
        if method in self.MUTATING_METHODS:
            nonce = call_params.pop("controller_nonce", None)
            if not isinstance(nonce, str) or not hmac.compare_digest(nonce, self._controller_nonce):
                raise RpcFailure(-32001, "CONTROLLER_AUTH_FAILED")
        elif "controller_nonce" in call_params:
            raise RpcFailure(-32602, "controller_nonce is not accepted by read-only methods")

        if method == "ping":
            self._exact_params(call_params, set(), set())
            return {"ok": True}
        if method == "capabilities":
            self._exact_params(call_params, set(), set())
            return {
                "schema_version": "sts-h1-capabilities.v1",
                "protocol": "framed-jsonrpc-2.0",
                "fairness_profiles": [FAIRNESS_PROFILE],
                "max_frame_bytes": 4 * 1024 * 1024,
                "max_actions_per_step": 12,
                "raw_command_submission": False,
                "methods": sorted(self.READ_METHODS | self.MUTATING_METHODS),
            }
        if method == "bridge.status":
            self._exact_params(call_params, set(), set())
            with self._condition:
                return {
                    "episode_id": self.episode_id,
                    "native_session_id": self.native_session_id,
                    "state_seq": self._snapshot.state_seq if self._snapshot else None,
                    "ready": self._snapshot is not None and self._fatal_error is None,
                    "reset_called": self._reset_called,
                    "close_requested": self._closed,
                    "bridge_error_count": self._bridge_error_count,
                    "fatal_error": self._fatal_error,
                    "bridge": (
                        deepcopy(self._snapshot.observation.get("bridge"))
                        if self._snapshot is not None
                        else None
                    ),
                    "environment_fingerprint_id": self.environment_fingerprint_id,
                }
        if method in {"observe", "env.observe"}:
            self._exact_params(call_params, set(), set())
            return self.observe()
        if method == "get_legal_actions":
            self._exact_params(call_params, set(), set())
            return self.legal_actions()
        if method == "env.replay":
            self._exact_params(call_params, set(), set())
            with self._condition:
                return {
                    "episode_id": self.episode_id,
                    "transition_count": self._transition_index,
                    "final_chain_hash": (
                        self._latest_transition["hashes"]["chain_hash"]
                        if self._latest_transition is not None
                        else None
                    ),
                }
        if method == "env.reset":
            return self.reset(call_params)
        if method in {"env.step", "submit_action"}:
            return self.step(call_params)
        if method == "env.close":
            return self.close(call_params)
        if method == "quit":
            return self.abort(call_params)
        raise RpcFailure(-32601, "Method not found")

    def summary(self, *, status: str, error: str | None = None) -> dict[str, Any]:
        with self._condition:
            observation = self._snapshot.observation if self._snapshot is not None else {}
            run = observation.get("run") if isinstance(observation.get("run"), dict) else {}
            final_chain = (
                self._latest_transition["hashes"]["chain_hash"]
                if self._latest_transition is not None
                else None
            )
            return {
                "schema_version": "sts-h1-worker-summary.v1",
                "status": status,
                "started_at": self._started_at,
                "finished_at": utc_now(),
                "pid": os.getpid(),
                "episode_id": self.episode_id,
                "native_session_id": self.native_session_id,
                "run_id": observation.get("run_id"),
                "final_decision_kind": observation.get("decision_kind"),
                "final_floor": run.get("floor"),
                "final_hp": run.get("current_hp"),
                "raw_receive_count": self._raw_receive_count,
                "distinct_state_count": self._snapshot.state_seq if self._snapshot else 0,
                "duplicate_state_count": self._duplicate_state_count,
                "bridge_error_count": self._bridge_error_count,
                "transition_count": self._transition_index,
                "actions_attempted": self._actions_attempted,
                "actions_accepted": self._actions_accepted,
                "actions_unverified": self._actions_unverified,
                "actions_rejected": self._actions_rejected,
                "actions_skipped": self._actions_skipped,
                "partial_batch_count": self._partial_batch_count,
                "unsupported_screen_count": self._unsupported_screen_count,
                "final_chain_hash": final_chain,
                "close_requested": self._closed,
                "abort_requested": self._abort_requested,
                "error": error or self._fatal_error,
                "metrics": self._metrics.document(
                    state_count=self._snapshot.state_seq if self._snapshot else 0,
                    decision_count=self._transition_index,
                    duplicate_state_count=self._duplicate_state_count,
                    process_wall_ms=(
                        int((time.monotonic() - self._episode_started_monotonic) * 1000)
                        if self._episode_started_monotonic is not None
                        else None
                    ),
                ),
            }

    def write_summary(self, *, status: str, error: str | None = None) -> dict[str, Any]:
        result = self.summary(status=status, error=error)
        atomic_write_json(self.run_dir / "worker-summary.json", result)
        atomic_write_json(self.run_dir / "metrics.json", result["metrics"])
        return result
