from scripts.verify_stage import p09_offline_pytest_addopts


def test_p09_offline_basetemp_is_unique_to_sanitized_evidence_batch():
    assert p09_offline_pytest_addopts("L07-20261109-a1b2") == (
        "--basetemp=.runtime/pytest-p09-offline-L07-20261109-a1b2"
    )
    assert p09_offline_pytest_addopts("../../outside") == (
        "--basetemp=.runtime/pytest-p09-offline-outside"
    )
