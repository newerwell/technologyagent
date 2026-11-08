from pathlib import Path

import pytest

from scripts.check_mongo_kernel import is_mongodb_compatible_kernel


ROOT = Path(__file__).parents[2]


def test_p06_ci_pins_ubuntu_2204_and_rejects_incompatible_kernel_interval():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "runs-on: ubuntu-22.04" in workflow
    assert "uname -r" in workflow
    assert "python -m scripts.check_mongo_kernel" in workflow


@pytest.mark.parametrize("release", ["6.19.0-100", "6.20.4", "7.0.0-rc1", "7.0.13-azure"])
def test_known_incompatible_mongodb_linux_kernels_are_rejected(release):
    assert is_mongodb_compatible_kernel(release) is False


@pytest.mark.parametrize("release", ["6.8.0-1020-azure", "7.0.14", "7.1.0"])
def test_compatible_linux_kernels_outside_mongodb_failure_interval_are_allowed(release):
    assert is_mongodb_compatible_kernel(release) is True


def test_unparseable_linux_kernel_is_not_assumed_compatible():
    with pytest.raises(ValueError, match="cannot parse"):
        is_mongodb_compatible_kernel("ubuntu-latest")


def test_both_mongo_compose_healthchecks_exit_nonzero_unless_ta_rs_primary():
    for relative in ("compose.yaml", "compose.p09-acceptance.yaml"):
        compose = (ROOT / relative).read_text(encoding="utf-8")
        assert "quit(1)" in compose
        assert 'expectedSet = "ta-rs"' in compose
        assert "status.set !== expectedSet" in compose
        assert "hello.setName !== expectedSet" in compose
        assert "myState !== 1" in compose
        assert "isWritablePrimary !== true" in compose
