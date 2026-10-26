from pathlib import Path


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
