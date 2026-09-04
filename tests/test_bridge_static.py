from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "vendor" / "CommunicationMod"


def test_bridge_uses_strict_environment_worker_contract() -> None:
    source = (BRIDGE / "src/main/java/communicationmod/CommunicationMod.java").read_text(
        encoding="utf-8"
    )
    assert '"STS_HARNESS_PYTHON"' in source
    assert '"STS_HARNESS_WORKER"' in source
    assert '"STS_HARNESS_AUTOSTART"' in source
    assert '!"ready".equalsIgnoreCase(message.trim())' in source


def test_bridge_streams_use_explicit_utf8_and_eof_terminates() -> None:
    reader = (BRIDGE / "src/main/java/communicationmod/DataReader.java").read_text(
        encoding="utf-8"
    )
    writer = (BRIDGE / "src/main/java/communicationmod/DataWriter.java").read_text(
        encoding="utf-8"
    )
    assert "StandardCharsets.UTF_8" in reader
    assert "message == null" in reader
    assert "StandardCharsets.UTF_8" in writer


def test_bridge_build_is_pinned_and_has_no_fixed_post_package_copy() -> None:
    pom = (BRIDGE / "pom.xml").read_text(encoding="utf-8")
    assert "1.2.1-sts-harness.2" in pom
    assert "maven-shade-plugin" in pom
    assert "<version>3.6.2</version>" in pom
    assert "<createDependencyReducedPom>false</createDependencyReducedPom>" in pom
    assert "maven-antrun-plugin" not in pom
    assert "../_ModTheSpire/mods" not in pom


def test_bridge_filters_completed_combat_rewards_from_state_and_choices() -> None:
    converter = (BRIDGE / "src/main/java/communicationmod/GameStateConverter.java").read_text(
        encoding="utf-8"
    )
    choices = (BRIDGE / "src/main/java/communicationmod/ChoiceScreenUtils.java").read_text(
        encoding="utf-8"
    )
    assert "ChoiceScreenUtils.isHarnessRewardAvailable(reward)" in converter
    assert "isHarnessRewardAvailable(reward)" in choices
    assert "harnessConsumedRewards.add(reward)" in choices
    assert "availableRewards.get(choice)" in choices


def test_bridge_waits_for_persistent_effects_and_boss_relic_equip() -> None:
    listener = (BRIDGE / "src/main/java/communicationmod/GameStateListener.java").read_text(
        encoding="utf-8"
    )
    choices = (BRIDGE / "src/main/java/communicationmod/ChoiceScreenUtils.java").read_text(
        encoding="utf-8"
    )
    assert "effect instanceof ShowCardAndObtainEffect" in listener
    assert "effect instanceof FastCardObtainEffect" in listener
    assert "hasPendingCardObtainEffect()" in listener
    assert "monster.intent == AbstractMonster.Intent.DEBUG" in listener
    boss_method = choices.split("public static void makeBossRewardChoice", 1)[1].split("}", 1)[0]
    assert "GameStateListener.blockStateUpdate();" in boss_method


def test_isolated_harness_disables_stock_steam_integration() -> None:
    patch = (
        BRIDGE
        / "src/main/java/communicationmod/patches/HarnessDisableSteamIntegrationPatch.java"
    ).read_text(encoding="utf-8")
    assert "clz = SteamIntegration.class" in patch
    assert "method = SpirePatch.CONSTRUCTOR" in patch
    assert 'System.getenv("STS_HARNESS_EPISODE_ID")' in patch
    assert "SteamAPI.loadLibraries();" in patch
    assert "SpireReturn.Return(null)" in patch
    assert "SpireReturn.Continue()" in patch
