from sts_harness.m1_policy import M1ProbePolicy, ProbeFailure


def menu_state() -> dict:
    return {
        "protocol_version": "communicationmod-harness.v1",
        "bridge_version": "1.2.1-sts-harness.1",
        "available_commands": ["start", "state"],
        "ready_for_command": True,
        "in_game": False,
    }


def run_state(*, screen_type: str, choices: list[str] | None = None) -> dict:
    state = {
        "protocol_version": "communicationmod-harness.v1",
        "bridge_version": "1.2.1-sts-harness.1",
        "available_commands": ["choose", "state"],
        "ready_for_command": True,
        "in_game": True,
        "game_state": {
            "screen_type": screen_type,
            "room_phase": "EVENT",
            "floor": 0,
            "choice_list": choices or ["first"],
        },
    }
    return state


def combat_state(*, turn: int, hand: list[dict]) -> dict:
    return {
        "protocol_version": "communicationmod-harness.v1",
        "bridge_version": "1.2.1-sts-harness.1",
        "available_commands": ["play", "end", "state"],
        "ready_for_command": True,
        "in_game": True,
        "game_state": {
            "screen_type": "NONE",
            "room_phase": "COMBAT",
            "floor": 1,
            "combat_state": {
                "turn": turn,
                "hand": hand,
                "monsters": [
                    {"id": "JawWorm", "current_hp": 40, "is_gone": False}
                ],
            },
        },
    }


def test_probe_policy_reaches_all_m1_evidence() -> None:
    policy = M1ProbePolicy("AMIYA20260904")
    assert policy.next_command(menu_state()) == "start ironclad 0 AMIYA20260904"

    neow = run_state(screen_type="EVENT", choices=["one", "two"])
    assert policy.next_command(neow) == "choose 0"

    map_state = run_state(screen_type="MAP", choices=["x=1,y=0"])
    assert policy.next_command(map_state) == "choose 0"

    hand = [
        {
            "id": "Strike_R",
            "uuid": "card-1",
            "is_playable": True,
            "has_target": True,
        }
    ]
    combat = combat_state(turn=1, hand=hand)
    assert policy.next_command(combat) == "play 1 0"

    after_play = combat_state(turn=1, hand=[])
    assert policy.next_command(after_play) == "end"

    next_turn = combat_state(turn=2, hand=[])
    assert policy.next_command(next_turn) is None
    assert policy.complete is True
    assert all(policy.evidence.values())


def test_probe_policy_rejects_bridge_error() -> None:
    policy = M1ProbePolicy("AMIYA20260904")
    state = menu_state()
    state["error"] = "bad command"
    try:
        policy.next_command(state)
    except ProbeFailure as exc:
        assert "bad command" in str(exc)
    else:
        raise AssertionError("expected ProbeFailure")

