from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _run_pwsh(script: Path) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not pwsh:
        pytest.skip("PowerShell 7 is required for the acceptance environment helper")
    return subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )


def test_acceptance_modes_are_isolated_inherited_and_restorable(tmp_path: Path) -> None:
    helper = (ROOT / "scripts" / "p09_acceptance_env.ps1").as_posix().replace("'", "''")
    expected_uri = "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true"
    script = tmp_path / "verify-p09-environment.ps1"
    script.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "$env:MONGODB_DATABASE = 'technologyagent_test_original'",
                "$env:INVENTORY_SNAPSHOT_PATH = ''",
                "$originalModelPresent = Test-Path Env:MODEL_MODE",
                "$originalModel = $env:MODEL_MODE",
                f". '{helper}' -Mode offline",
                "$offline = [ordered]@{ database=$env:MONGODB_DATABASE; model=$env:MODEL_MODE; live=$env:RUN_LIVE_MODEL; uri=$env:MONGODB_URI; test_uri=$env:MONGODB_TEST_URI; compose=$env:COMPOSE_FILE; project=$env:COMPOSE_PROJECT_NAME; snapshot=$env:INVENTORY_SNAPSHOT_PATH; sources=@($env:INVENTORY_DATA_SOURCE,$env:PARTS_DATA_SOURCE,$env:SUPPLIERS_DATA_SOURCE,$env:ORDERS_DATA_SOURCE) }",
                f". '{helper}' -Mode browser",
                "$browser = [ordered]@{ database=$env:MONGODB_DATABASE; model=$env:MODEL_MODE; live=$env:RUN_LIVE_MODEL }",
                f". '{helper}' -Mode live",
                "$live = [ordered]@{ database=$env:MONGODB_DATABASE; model=$env:MODEL_MODE; live=$env:RUN_LIVE_MODEL }",
                "$child = & pwsh -NoProfile -Command '[ordered]@{ database=$env:MONGODB_DATABASE; uri=$env:MONGODB_URI; compose=$env:COMPOSE_FILE } | ConvertTo-Json -Compress'",
                f". '{helper}' -Restore",
                "$restored = [ordered]@{ database=$env:MONGODB_DATABASE; snapshot_present=(Test-Path Env:INVENTORY_SNAPSHOT_PATH); snapshot=$env:INVENTORY_SNAPSHOT_PATH; mode_present=(Test-Path Env:MODEL_MODE); mode=$env:MODEL_MODE }",
                "[ordered]@{ offline=$offline; browser=$browser; live=$live; child=($child | ConvertFrom-Json); restored=$restored } | ConvertTo-Json -Depth 5 -Compress",
            ]
        ),
        encoding="utf-8",
    )
    result = _run_pwsh(script)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed["offline"] == {
        "database": "technologyagent_test_p09_verify",
        "model": "fake",
        "live": "0",
        "uri": expected_uri,
        "test_uri": expected_uri,
        "compose": str(ROOT / "compose.p09-acceptance.yaml"),
        "project": "technologyagent-p09-acceptance",
        "snapshot": "",
        "sources": ["local_seed"] * 4,
    }
    assert observed["browser"] == {
        "database": "technologyagent_test_p09_browser",
        "model": "fake",
        "live": "0",
    }
    assert observed["live"] == {
        "database": "technologyagent_test_p09_live",
        "model": "live",
        "live": "1",
    }
    assert observed["child"] == {
        "database": "technologyagent_test_p09_live",
        "uri": expected_uri,
        "compose": str(ROOT / "compose.p09-acceptance.yaml"),
    }
    assert observed["restored"] == {
        "database": "technologyagent_test_original",
        "snapshot_present": True,
        "snapshot": "",
        "mode_present": "MODEL_MODE" in os.environ,
        "mode": os.environ.get("MODEL_MODE"),
    }


def test_acceptance_environment_rejects_unknown_mode_without_running(tmp_path: Path) -> None:
    helper = (ROOT / "scripts" / "p09_acceptance_env.ps1").as_posix().replace("'", "''")
    script = tmp_path / "reject-p09-mode.ps1"
    script.write_text(
        f". '{helper}' -Mode unsafe\nWrite-Output 'SHOULD_NOT_RUN'\n",
        encoding="utf-8",
    )
    result = _run_pwsh(script)
    assert result.returncode != 0
    assert "SHOULD_NOT_RUN" not in result.stdout


def test_start_refuses_non_test_database_before_creating_runtime_files(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not pwsh:
        pytest.skip("PowerShell 7 is required for start.ps1 validation")
    checkout = tmp_path / "synthetic-checkout"
    (checkout / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "start.ps1", checkout / "start.ps1")
    shutil.copy2(ROOT / "scripts" / "import_dotenv.ps1", checkout / "scripts" / "import_dotenv.ps1")
    (checkout / ".env").write_text("MONGODB_DATABASE=technologyagent_test_from_file\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "COMPOSE_PROJECT_NAME": "technologyagent-p09-acceptance",
            "COMPOSE_FILE": str(checkout / "compose.p09-acceptance.yaml"),
            "MONGODB_DATABASE": "technologyagent_dev",
            "MONGODB_URI": "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true",
            "MONGODB_TEST_URI": "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true",
        }
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(checkout / "start.ps1")],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        env=environment,
    )
    assert result.returncode != 0
    assert "technologyagent_test_*" in result.stderr
    assert not (checkout / ".runtime").exists()
