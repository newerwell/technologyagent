from __future__ import annotations

from scripts.verify_stage import MANIFESTS


def test_p09_manifest_isolated_by_mode_and_requires_real_live_model():
    offline = MANIFESTS["P09"]["offline"]
    browser = MANIFESTS["P09"]["browser"]
    live = MANIFESTS["P09"]["live"]

    assert dict(offline[0].env)["MONGODB_DATABASE"] == "technologyagent_test_p09_verify"
    assert dict(offline[1].env)["MONGODB_DATABASE"] == "technologyagent_test_p09_verify"
    assert dict(browser[0].env)["MONGODB_DATABASE"] == "technologyagent_test_p09_browser"
    assert dict(browser[1].env)["MODEL_MODE"] == "fake"
    assert dict(live[0].env)["MONGODB_DATABASE"] == "technologyagent_test_p09_live"
    assert dict(live[0].env)["MODEL_MODE"] == "live"
    assert dict(live[0].env)["RUN_LIVE_MODEL"] == "1"
