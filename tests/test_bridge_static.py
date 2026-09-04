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
    assert "1.2.1-sts-harness.1" in pom
    assert "maven-shade-plugin" in pom
    assert "<version>3.6.2</version>" in pom
    assert "<createDependencyReducedPom>false</createDependencyReducedPom>" in pom
    assert "maven-antrun-plugin" not in pom
    assert "../_ModTheSpire/mods" not in pom

