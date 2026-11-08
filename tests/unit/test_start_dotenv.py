from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_dotenv_does_not_replace_explicit_empty_environment_value(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not pwsh:
        pytest.skip("PowerShell 7 is required for the start.ps1 environment contract")

    dotenv = tmp_path / ".env.synthetic"
    dotenv.write_text("TA_TEST_EMPTY=from-file\nTA_TEST_MISSING=from-file\n", encoding="utf-8")
    script = tmp_path / "verify-dotenv.ps1"
    helper = (ROOT / "scripts" / "import_dotenv.ps1").as_posix().replace("'", "''")
    env_file = dotenv.as_posix().replace("'", "''")
    script.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "$env:TA_TEST_EMPTY = ''",
                "Remove-Item Env:TA_TEST_MISSING -ErrorAction SilentlyContinue",
                f". '{helper}'",
                f"Import-DotEnv -Path '{env_file}'",
                "[ordered]@{ empty = $env:TA_TEST_EMPTY; missing = $env:TA_TEST_MISSING } | ConvertTo-Json -Compress",
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {"empty": "", "missing": "from-file"}
