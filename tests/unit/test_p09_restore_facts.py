import pytest

from scripts.p09_restore_facts import ISOLATED_URI, validate_target


@pytest.mark.parametrize("database,uri", [
    ("technologyagent_dev", ISOLATED_URI),
    ("technologyagent_test_p09_browser", ISOLATED_URI),
    ("technologyagent_test_p09_clean_", ISOLATED_URI),
    ("technologyagent_test_p09_clean_20261109", ISOLATED_URI.replace("27028", "27027")),
])
def test_restore_fingerprint_guard_rejects_daily_or_ambiguous_targets(database, uri):
    with pytest.raises(ValueError):
        validate_target(database, uri)


def test_restore_fingerprint_accepts_only_named_isolated_targets():
    validate_target("technologyagent_test_p09_clean_20261109_123456", ISOLATED_URI)
    validate_target("technologyagent_test_p09_restored_20261109_123456", ISOLATED_URI)
