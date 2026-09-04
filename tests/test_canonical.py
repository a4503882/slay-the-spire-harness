import math

import pytest

from sts_harness.canonical import DuplicateJsonKey, canonical_json_bytes, strict_json_loads


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(DuplicateJsonKey, match="duplicate JSON key"):
        strict_json_loads('{"a":1,"a":2}')


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_strict_json_rejects_non_finite_numbers(token: str) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        strict_json_loads('{"value":' + token + "}")


def test_canonical_json_has_stable_order_and_utf8() -> None:
    assert canonical_json_bytes({"z": 1, "a": "尖塔"}) == '{"a":"尖塔","z":1}'.encode()


def test_canonical_json_rejects_python_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": math.nan})

