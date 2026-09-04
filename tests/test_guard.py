from pathlib import Path

from sts_harness.guard import compare_snapshots, snapshot_roots


def test_guard_detects_content_change(tmp_path: Path) -> None:
    target = tmp_path / "normal"
    target.mkdir()
    file_path = target / "save.dat"
    file_path.write_text("before", encoding="utf-8")
    before = snapshot_roots([("normal", target)])
    file_path.write_text("after", encoding="utf-8")
    after = snapshot_roots([("normal", target)])
    result = compare_snapshots(before, after)
    assert result["unchanged"] is False
    assert result["changes"][0]["name"] == "normal"


def test_guard_treats_missing_root_as_stable(tmp_path: Path) -> None:
    target = tmp_path / "missing"
    before = snapshot_roots([("missing", target)])
    after = snapshot_roots([("missing", target)])
    assert compare_snapshots(before, after)["unchanged"] is True

