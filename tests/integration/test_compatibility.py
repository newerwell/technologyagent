"""P00-T02：全部必需兼容探针真实执行通过。"""

from __future__ import annotations

from scripts.check_compatibility import REQUIRED_PROBES, run_compatibility


def test_all_required_compatibility_probes_pass():
    report = run_compatibility()
    failures = [item for item in report.outcomes if item.status != "ok"]
    assert not failures, failures
    assert {item.name for item in report.outcomes} == set(REQUIRED_PROBES)
    assert report.ok is True
    assert report.environment["python"].startswith(("3.11", "3.12", "3.13"))
