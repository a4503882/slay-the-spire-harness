from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonical import sha256_document


class ProbeFailure(RuntimeError):
    pass


def _dictionary(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _commands(document: dict[str, Any]) -> set[str]:
    value = document.get("available_commands")
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value}


def _game(document: dict[str, Any]) -> dict[str, Any]:
    return _dictionary(document.get("game_state"))


def _combat(document: dict[str, Any]) -> dict[str, Any]:
    return _dictionary(_game(document).get("combat_state"))


def _turn(document: dict[str, Any]) -> int | None:
    value = _combat(document).get("turn")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _hand_uuids(document: dict[str, Any]) -> set[str]:
    return {
        str(row["uuid"])
        for row in _rows(_combat(document).get("hand"))
        if isinstance(row.get("uuid"), str)
    }


@dataclass(frozen=True)
class PendingCommand:
    kind: str
    command: str
    before_hash: str
    before_turn: int | None = None
    card_uuid: str | None = None


class M1ProbePolicy:
    """Small deterministic policy used only for the native M-1 compatibility probe."""

    def __init__(self, seed: str) -> None:
        normalized_seed = seed.strip().upper()
        if not normalized_seed or not normalized_seed.isalnum():
            raise ValueError("M-1 seed must contain only ASCII letters and digits")
        self.seed = normalized_seed
        self.pending: PendingCommand | None = None
        self.commands_sent = 0
        self.states_seen = 0
        self.complete = False
        self.evidence: dict[str, bool] = {
            "start_verified": False,
            "non_combat_choice_verified": False,
            "card_play_verified": False,
            "end_turn_verified": False,
        }
        self.verifications: list[dict[str, Any]] = []

    def _verify_pending(self, document: dict[str, Any]) -> None:
        pending = self.pending
        if pending is None:
            return
        after_hash = sha256_document(document)
        game = _game(document)
        in_game = document.get("in_game") is True
        verified = False
        detail = ""

        if pending.kind == "start":
            verified = in_game and bool(game)
            detail = "bridge entered a dungeon run"
            if verified:
                self.evidence["start_verified"] = True
        elif pending.kind == "non_combat_choice":
            verified = after_hash != pending.before_hash
            detail = "stable exported state changed after a non-combat choice"
            if verified:
                self.evidence["non_combat_choice_verified"] = True
        elif pending.kind == "play_card":
            hand_uuids = _hand_uuids(document)
            verified = (
                pending.card_uuid is not None
                and (pending.card_uuid not in hand_uuids or not _combat(document))
            )
            detail = "selected card left the stable hand or combat ended"
            if verified:
                self.evidence["card_play_verified"] = True
        elif pending.kind == "end_turn":
            next_turn = _turn(document)
            verified = (
                not _combat(document)
                or (
                    pending.before_turn is not None
                    and next_turn is not None
                    and next_turn > pending.before_turn
                )
            )
            detail = "combat turn advanced or combat ended"
            if verified:
                self.evidence["end_turn_verified"] = True
        else:
            raise ProbeFailure(f"unknown pending M-1 command kind: {pending.kind}")

        self.verifications.append(
            {
                "kind": pending.kind,
                "command": pending.command,
                "before_hash": pending.before_hash,
                "after_hash": after_hash,
                "verified": verified,
                "detail": detail,
            }
        )
        self.pending = None
        if not verified:
            raise ProbeFailure(f"post-state did not verify {pending.kind}: {detail}")

    def _queue(
        self,
        *,
        kind: str,
        command: str,
        document: dict[str, Any],
        card_uuid: str | None = None,
    ) -> str:
        self.pending = PendingCommand(
            kind=kind,
            command=command,
            before_hash=sha256_document(document),
            before_turn=_turn(document),
            card_uuid=card_uuid,
        )
        self.commands_sent += 1
        return command

    def next_command(self, document: dict[str, Any]) -> str | None:
        if self.complete:
            return None
        self.states_seen += 1

        error = document.get("error")
        if isinstance(error, str) and error.strip():
            raise ProbeFailure(f"bridge returned an error: {error.strip()}")
        if document.get("ready_for_command") is not True:
            raise ProbeFailure("bridge emitted a state that is not ready for command")

        self._verify_pending(document)
        if all(self.evidence.values()):
            self.complete = True
            return None

        commands = _commands(document)
        game = _game(document)

        if not self.evidence["start_verified"]:
            if "start" not in commands or document.get("in_game") is True:
                raise ProbeFailure("expected the main-menu start command")
            return self._queue(
                kind="start",
                command=f"start ironclad 0 {self.seed}",
                document=document,
            )

        if not self.evidence["non_combat_choice_verified"] and "choose" in commands:
            choice_list = game.get("choice_list")
            if not isinstance(choice_list, list) or not choice_list:
                raise ProbeFailure("choose is available without a non-empty choice_list")
            return self._queue(
                kind="non_combat_choice",
                command="choose 0",
                document=document,
            )

        combat = _combat(document)
        if combat:
            if not self.evidence["card_play_verified"]:
                hand = _rows(combat.get("hand"))
                monsters = _rows(combat.get("monsters"))
                target_index = next(
                    (
                        index
                        for index, monster in enumerate(monsters)
                        if monster.get("is_gone") is not True
                        and isinstance(monster.get("current_hp"), int)
                        and monster["current_hp"] > 0
                    ),
                    None,
                )
                for index, card in enumerate(hand, start=1):
                    if card.get("is_playable") is not True:
                        continue
                    card_uuid = card.get("uuid")
                    if not isinstance(card_uuid, str) or not card_uuid:
                        continue
                    if card.get("has_target") is True:
                        if target_index is None:
                            continue
                        command = f"play {index} {target_index}"
                    else:
                        command = f"play {index}"
                    return self._queue(
                        kind="play_card",
                        command=command,
                        document=document,
                        card_uuid=card_uuid,
                    )
                raise ProbeFailure("combat state has no probe-safe playable card")

            if not self.evidence["end_turn_verified"]:
                if "end" not in commands:
                    raise ProbeFailure("end command is unavailable after verified card play")
                return self._queue(kind="end_turn", command="end", document=document)

        if "choose" in commands:
            return self._queue(
                kind="non_combat_choice",
                command="choose 0",
                document=document,
            )

        if "proceed" in commands or "confirm" in commands:
            return self._queue(
                kind="non_combat_choice",
                command="proceed",
                document=document,
            )

        raise ProbeFailure(
            "M-1 reached a stable state without a safe command for the remaining evidence"
        )

