"""N06：验收报告的候选人 SHA、脏状态与漂移检测（最小临时 Git 仓库）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.acceptance_provenance import (
    collect_acceptance_provenance,
    finalize_acceptance_provenance,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace",
    )
    return (result.stdout or "").strip()


def _init_repo(root: Path) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "p09@example.test")
    _git(root, "config", "user.name", "P09 Test")
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "README.md").write_text("# docs\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = \"p09\"\n", encoding="utf-8")
    (root / ".gitignore").write_text(".runtime/\n.env\nstorage/\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return _git(root, "rev-parse", "HEAD")


def test_clean_checkout_records_candidate_sha(tmp_path):
    sha = _init_repo(tmp_path)

    provenance = collect_acceptance_provenance(tmp_path)

    assert provenance["known"] is True
    assert provenance["source_sha"] == sha
    assert provenance["product_dirty"] is False
    assert provenance["product_changed_paths"] == []
    assert provenance["checkout_path"].endswith(str(tmp_path.resolve()).split("\\")[-1])


def test_tracked_and_untracked_product_code_is_dirty(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "backend" / "app" / "main.py").write_text("VALUE = 2\n", encoding="utf-8")

    tracked = collect_acceptance_provenance(tmp_path)
    assert tracked["product_dirty"] is True
    assert "backend/app/main.py" in tracked["product_changed_paths"]

    (tmp_path / "tests" / "test_new.py").write_text("def test_new():\n    pass\n", encoding="utf-8")
    untracked = collect_acceptance_provenance(tmp_path)
    assert untracked["product_dirty"] is True
    assert "tests/test_new.py" in untracked["product_changed_paths"]


def test_docs_only_change_is_listed_separately(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "docs" / "README.md").write_text("# docs\n\nmore\n", encoding="utf-8")

    provenance = collect_acceptance_provenance(tmp_path)

    assert provenance["product_dirty"] is False
    assert provenance["docs_changed_paths"] == ["docs/README.md"]
    assert provenance["docs_only_dirty"] is True


def test_ignored_env_and_runtime_paths_are_not_read(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime" / "run.log").write_text("x\n", encoding="utf-8")
    (tmp_path / "storage").mkdir()
    (tmp_path / "storage" / "artifact.bin").write_bytes(b"x")

    provenance = collect_acceptance_provenance(tmp_path)

    assert provenance["product_dirty"] is False
    assert provenance["other_changed_paths"] == []


def test_git_unavailable_is_unknown_not_guessed(tmp_path, monkeypatch):
    import scripts.acceptance_provenance as provenance_module

    def unavailable_run(*args, **kwargs):
        raise FileNotFoundError("git executable not available")

    monkeypatch.setattr(provenance_module.subprocess, "run", unavailable_run)

    provenance = collect_acceptance_provenance(tmp_path)

    assert provenance["known"] is False
    assert provenance["source_sha"] is None
    assert provenance["git_error"]


def test_source_drift_between_start_and_end_is_explicit(tmp_path):
    _init_repo(tmp_path)
    provenance = collect_acceptance_provenance(tmp_path)

    (tmp_path / "backend" / "app" / "main.py").write_text("VALUE = 3\n", encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "drift")
    finalized = finalize_acceptance_provenance(provenance, tmp_path)

    assert finalized["source_drift"] is True
    assert finalized["end_source_sha"] != finalized["source_sha"]
    assert "backend/app/main.py" in finalized["drift_paths"]
    assert finalized["finished_at"] >= finalized["started_at"]