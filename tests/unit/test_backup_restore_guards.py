import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_restore_inspects_archive_namespaces_before_writing_and_limits_include():
    source = (ROOT / "scripts" / "restore.ps1").read_text(encoding="utf-8")
    dry_run = source.find("--dryRun")
    write_run = source.find("mongorestore", dry_run + 1)
    assert dry_run >= 0 and write_run > dry_run
    assert "--nsInclude" in source
    assert "manifest.database_namespaces" in source
    assert "Restore target is not empty" in source


def test_backup_requires_exact_storage_inventory_for_ready_artifacts():
    source = (ROOT / "scripts" / "backup.ps1").read_text(encoding="utf-8")
    assert "storage_key" in source and "status" in source
    assert "ready artifact" in source.lower()
    assert "expectedStorageKeys" in source
    assert "storage files differ from ready artifact records" in source


def test_restore_checks_exact_file_set_and_artifact_associations():
    source = (ROOT / "scripts" / "restore.ps1").read_text(encoding="utf-8")
    assert "manifest.artifact_refs" in source
    assert "manifest.files" in source
    assert "unexpected storage file" in source.lower()
    assert "storage_key" in source


def _powershell(tmp_path: Path, body: str):
    pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not pwsh:
        pytest.skip("PowerShell 7 is required for backup target guards")
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    for name in ("backup.ps1", "restore.ps1", "backup_target.ps1"):
        source = ROOT / "scripts" / name
        if source.exists():
            shutil.copy2(source, scripts / name)
    wrapper = checkout / "verify.ps1"
    wrapper.write_text("$ErrorActionPreference='Stop'\n" + body, encoding="utf-8")
    return subprocess.run([pwsh, "-NoProfile", "-File", str(wrapper)], cwd=checkout,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)


@pytest.mark.parametrize("name,arguments", [
    ("backup", "-DatabaseName technologyagent_test_source -Destination './backup'"),
    ("restore", "-BackupDirectory './backup' -TargetDatabase technologyagent_test_target -TargetStorageDirectory './target'"),
])
@pytest.mark.parametrize("target", ["", "-MongoContainer technologyagent-mongodb -MongoPort 27027",
                                   "-MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27027"])
def test_isolated_backup_restore_rejects_implicit_or_wrong_target_before_io(tmp_path, name, arguments, target):
    result = _powershell(tmp_path, f"""
$env:COMPOSE_PROJECT_NAME='technologyagent-p09-acceptance'
function docker {{ throw 'DOCKER_MUST_NOT_RUN' }}
try {{ & ./scripts/{name}.ps1 {arguments} -MaintenanceConfirmed {target}; throw 'SHOULD_NOT_RUN' }}
catch {{ if ($_.Exception.Message -notmatch 'explicit isolated Mongo target') {{ throw }}; Write-Output 'target-rejected-before-io' }}
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "target-rejected-before-io" in result.stdout


def test_all_backup_restore_docker_calls_use_selected_container_and_port(tmp_path):
    result = _powershell(tmp_path, r"""
$env:COMPOSE_PROJECT_NAME='technologyagent-p09-acceptance'
$global:BackupTargetTestCalls=[Collections.Generic.List[object]]::new()
$artifact=[ordered]@{_id='art_test';owner_id='local-owner';run_id='run_test';status='ready';storage_key='reports/a.json';size_bytes=8}
function docker {
    $a=@($args | ForEach-Object { [string]$_ }); $global:BackupTargetTestCalls.Add($a); $global:LASTEXITCODE=0
    if ($a[0] -eq 'cp') {
        if ($a[1].StartsWith('technologyagent-p09-acceptance-mongodb:')) { [IO.File]::WriteAllText($a[2],'synthetic archive') }
        return
    }
    if ($a -contains 'mongosh') {
        $code=$a[-1]
        if ($code -match 'hello') { '{"setName":"ta-rs","isWritablePrimary":true}'; return }
        if ($code -match 'getCollectionNames\(\).length') { '0'; return }
        if ($code -match 'collections:') { @{collections=@('artifacts','runs');artifact_refs=@($artifact)}|ConvertTo-Json -Depth 5 -Compress; return }
        ConvertTo-Json -InputObject @($artifact) -Depth 5 -Compress; return
    }
    if ($a -contains '--dryRun') {
        foreach ($name in @('artifacts','runs')) {
            $ns='technologyagent_test_source.'+$name; $quote=[string][char]96
            'found collection '+$quote+$ns+$quote+' bson to restore to '+$quote+$ns+$quote
        }
    }
}
New-Item -ItemType Directory -Path './source/reports' -Force | Out-Null
[IO.File]::WriteAllText((Join-Path (Get-Location) 'source/reports/a.json'),'report-1')
& ./scripts/backup.ps1 -DatabaseName technologyagent_test_source -Destination './backup' -StorageRoot './source' -MaintenanceConfirmed -MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028
& ./scripts/restore.ps1 -BackupDirectory './backup' -TargetDatabase technologyagent_test_target -TargetStorageDirectory './target' -MaintenanceConfirmed -MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028
@{calls=@($global:BackupTargetTestCalls.ToArray());restored=(Get-Content './target/reports/a.json' -Raw)}|ConvertTo-Json -Depth 5 -Compress
""")
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed["restored"] == "report-1"
    calls = observed["calls"]
    assert len(calls) >= 11
    for call in calls:
        if call[0] == "exec":
            assert call[1] == "technologyagent-p09-acceptance-mongodb", call
            if call[2] != "rm":
                assert call[call.index("--port") + 1] == "27028", call
        elif call[0] == "cp":
            assert any(arg.startswith("technologyagent-p09-acceptance-mongodb:") for arg in call[1:]), call
        else:
            pytest.fail(f"unexpected Docker command: {call}")


@pytest.mark.parametrize("hello", [
    '{"isWritablePrimary":true}',
    '{"setName":"ta-rs","isWritablePrimary":false}',
])
def test_backup_rejects_standalone_or_non_primary_before_dump(tmp_path, hello):
    result = _powershell(tmp_path, f"""
$env:COMPOSE_PROJECT_NAME='technologyagent-p09-acceptance'
function docker {{ if ($args -contains 'mongodump') {{ throw 'DUMP_MUST_NOT_RUN' }}; $global:LASTEXITCODE=0; '{hello}' }}
try {{ & ./scripts/backup.ps1 -DatabaseName technologyagent_test_source -Destination './backup' -MaintenanceConfirmed -MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028; throw 'SHOULD_NOT_RUN' }}
catch {{ if ($_.Exception.Message -notmatch 'writable ta-rs PRIMARY') {{ throw }}; Write-Output 'primary-rejected' }}
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "primary-rejected" in result.stdout


def test_restore_refuses_active_application_before_accessing_archive_or_database(tmp_path):
    result = _powershell(tmp_path, r"""
$env:COMPOSE_PROJECT_NAME='technologyagent-p09-acceptance'
New-Item -ItemType Directory -Path './.runtime' | Out-Null
'{"processes":[{"name":"synthetic-process","pid":1}]}'|Set-Content './.runtime/processes.json'
function docker { throw 'DOCKER_MUST_NOT_RUN' }
try { & ./scripts/restore.ps1 -BackupDirectory './absent' -TargetDatabase technologyagent_test_target -TargetStorageDirectory './target' -MaintenanceConfirmed -MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028; throw 'SHOULD_NOT_RUN' }
catch { if ($_.Exception.Message -notmatch 'process registry is not empty') { throw }; Write-Output 'active-app-rejected' }
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "active-app-rejected" in result.stdout
