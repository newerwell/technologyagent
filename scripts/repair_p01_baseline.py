"""显式修正旧 P01 本地库的 3 条库存基线；默认 dry-run，不自动执行。"""

from __future__ import annotations

import argparse
import asyncio
import json

from backend.app.config import load_settings
from backend.app.repositories.mongo import MongoResources
from backend.app.services.baseline_repair import repair_p01_baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair old P01 baseline inventory rows")
    parser.add_argument("--database", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply after dry-run inspection; refuses conflicts and never resets the database",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.database:
        settings = settings.model_copy(update={"mongodb_database": args.database})

    async def run():
        resources = await MongoResources.open(settings)
        try:
            preview = await repair_p01_baseline(resources, apply=False)
            print("DRY-RUN / BACKUP / CHANGES")
            print(json.dumps(preview.model_dump(mode="json"), ensure_ascii=False, indent=2))
            if not args.apply:
                return 0 if not preview.conflicts else 1
            if preview.conflicts:
                print("refusing to apply: conflicts require human review")
                return 1
            result = await repair_p01_baseline(resources, apply=True)
            print("APPLIED")
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
            if result.conflicts:
                return 1
            return 0 if result.applied or not result.changes else 1
        finally:
            await resources.close()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
