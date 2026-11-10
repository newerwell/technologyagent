"""P09 验收报告的源码归属与批次标识。

只读取 Git 状态与路径，不读取、不哈希被忽略目录中的 env/用户数据/storage/日志。
Git 不可用时明确返回 known=False，最终门禁不接受该值。
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRODUCT_DIRECTORIES = (
    "backend/", "mcp_server/", "frontend/src/", "tests/", "scripts/", "fixtures/", ".github/",
)
PRODUCT_FILES = (
    "pyproject.toml", "uv.lock", "pytest.ini", "start.ps1", "stop.ps1",
    "frontend/package.json", "frontend/package-lock.json",
    "frontend/next.config.ts", "frontend/next.config.mjs", "frontend/tsconfig.json",
    "frontend/playwright.config.ts", "frontend/playwright.clean.config.ts",
    "frontend/eslint.config.mjs",
)
DOC_DIRECTORIES = ("docs/", "evidence/")
IGNORED_DIRECTORIES = (
    ".runtime/", ".venv/", "storage/", "data/", "node_modules/", "frontend/node_modules/",
    "frontend/.next/", ".dsh-meow/", "backups/", "downloads/",
)
IGNORED_FILENAMES = {".env", ".env.local"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ignored(path: str) -> bool:
    if path.startswith(IGNORED_DIRECTORIES):
        return True
    name = path.rsplit("/", 1)[-1]
    return name in IGNORED_FILENAMES or name.endswith((".log", ".db"))


def _is_product(path: str) -> bool:
    return path.startswith(PRODUCT_DIRECTORIES) or path in PRODUCT_FILES or path.startswith("compose")


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    # Keep the leading status column; only trailing newlines are removed.
    return result.returncode, (result.stdout or "").rstrip("\r\n")


def _changed_paths(root: Path) -> list[str] | None:
    code, output = _git(root, "status", "--porcelain=v1")
    if code != 0:
        return None
    paths: list[str] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        path = path.replace("\\", "/")
        if path and not _ignored(path):
            paths.append(path)
    return sorted(set(paths))


def _snapshot(root: Path) -> dict[str, Any]:
    code, sha = _git(root, "rev-parse", "HEAD")
    if code != 0:
        return {
            "git_available": False, "source_sha": None, "branch": None,
            "product_dirty": None, "product_changed_paths": [], "docs_changed_paths": [],
            "git_error": sha[:300],
        }
    _, branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    changed = _changed_paths(root)
    if changed is None:
        return {
            "git_available": False, "source_sha": None, "branch": None,
            "product_dirty": None, "product_changed_paths": [], "docs_changed_paths": [],
            "git_error": "git status failed",
        }
    product = [path for path in changed if _is_product(path)]
    docs = [path for path in changed if path.startswith(DOC_DIRECTORIES)]
    return {
        "git_available": True,
        "source_sha": sha,
        "branch": branch or None,
        "detached": (branch or "") == "HEAD",
        "product_dirty": bool(product),
        "product_changed_paths": product,
        "docs_changed_paths": docs,
        "docs_only_dirty": bool(docs) and not product,
        "other_changed_paths": [path for path in changed if path not in product and path not in docs],
    }


def collect_acceptance_provenance(repository_root: Path) -> dict[str, Any]:
    """Record the candidate source identity before an acceptance run starts."""
    root = Path(repository_root).resolve()
    snapshot = _snapshot(root)
    return {
        "known": bool(snapshot.pop("git_available")),
        "checkout_path": str(root),
        "started_at": _now(),
        **snapshot,
    }


def finalize_acceptance_provenance(provenance: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    """Record the end SHA and product drift; never rewrite the original report verdict."""
    root = Path(repository_root).resolve()
    snapshot = _snapshot(root)
    end_sha = snapshot.get("source_sha")
    start_sha = provenance.get("source_sha")
    provenance["finished_at"] = _now()
    provenance["end_source_sha"] = end_sha
    provenance["end_product_dirty"] = snapshot.get("product_dirty")
    provenance["source_drift"] = end_sha != start_sha
    drift_paths: list[str] = []
    if provenance["source_drift"] and start_sha and end_sha:
        code, output = _git(root, "diff", "--name-only", start_sha, end_sha)
        if code == 0:
            drift_paths = [path for path in output.splitlines() if path.strip()]
    provenance["drift_paths"] = drift_paths
    return provenance
