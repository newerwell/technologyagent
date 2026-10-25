"""P00-T05/P01-T06：verify_stage manifest 与退出码分类，防止无测试伪通过。"""

from __future__ import annotations

import shutil

from scripts.verify_stage import Check, MANIFESTS, NPM, PYTHON, classify_exit, run_check


def test_p00_offline_manifest_is_real_and_complete():
    checks = MANIFESTS["P00"]["offline"]
    names = [check.name for check in checks]
    assert names == [
        "db_init",
        "compatibility",
        "integration_tests",
        "frontend_typecheck",
        "frontend_tests",
        "frontend_build",
    ]
    assert len(set(names)) == len(names)
    for check in checks:
        assert check.argv
        assert check.cwd.is_dir()
        assert check.timeout_seconds > 0
        assert check.required is True
    assert "tests/unit" not in " ".join(" ".join(check.argv) for check in checks)


def test_p01_offline_manifest_adds_seed_unit_integration_and_contract():
    checks = MANIFESTS["P01"]["offline"]
    names = [check.name for check in checks]
    assert names == [
        "db_init",
        "compatibility",
        "seed",
        "unit_tests",
        "integration_tests",
        "frontend_typecheck",
        "frontend_tests",
        "frontend_build",
        "contract_check",
    ]
    seed_check = next(check for check in checks if check.name == "seed")
    assert dict(seed_check.env)["MONGODB_DATABASE"] == "technologyagent_test_p01_verify"
    assert "tests/unit" in " ".join(
        " ".join(check.argv) for check in checks if check.name == "unit_tests"
    )
    assert any(check.name == "contract_check" for check in checks)


def test_pytest_exit_5_is_failure_not_success():
    status, detail = classify_exit(
        5, (PYTHON, "-m", "pytest", "tests/unit", "-q")
    )
    assert status == "failed"
    assert "no tests collected" in detail


def test_zero_is_passed_and_nonzero_is_failed():
    assert classify_exit(0, (PYTHON, "-m", "pytest", "tests/integration"))[0] == "passed"
    assert classify_exit(1, (PYTHON, "-m", "pytest", "tests/integration"))[0] == "failed"
    assert classify_exit(0, (NPM, "--prefix", "frontend", "run", "build"))[0] == "passed"


def test_live_check_with_all_skipped_is_never_passed(monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, stdout="9 skipped in 0.02s", stderr=""))
    result = run_check(Check("live_p03_three_by_three", (PYTHON, "-m", "pytest", "fake")))
    assert result["status"] == "failed"


def test_manifest_executables_exist():
    assert PYTHON and shutil.which(PYTHON)
    assert NPM and (shutil.which(NPM) or NPM.endswith(".cmd"))
    for stage in ("P00", "P01"):
        for mode in ("offline", "live", "browser"):
            assert mode in MANIFESTS[stage]
