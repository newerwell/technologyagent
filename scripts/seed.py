"""P01 seed CLI：默认幂等 upsert 合成数据；--reset 仅限测试库。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from backend.app.config import load_settings
from backend.app.repositories.mongo import MongoResources
from backend.app.services.seeding import DEFAULT_FIXTURE_DIR, SeedError, seed, write_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed P01 synthetic fixtures")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--database", default=None)
    parser.add_argument("--reset", action="store_true", help="only for technologyagent_test_* databases")
    parser.add_argument("--write-manifest", action="store_true", help="regenerate fixtures/v1/manifest.json")
    args = parser.parse_args(argv)

    try:
        if args.write_manifest:
            manifest = write_manifest(args.fixture_dir)
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0

        settings = load_settings()
        if args.database:
            settings = settings.model_copy(update={"mongodb_database": args.database})

        async def run():
            resources = await MongoResources.open(settings)
            try:
                return await seed(resources.db, args.fixture_dir, reset=args.reset)
            finally:
                await resources.close()

        summary = asyncio.run(run())
    except SeedError as exc:
        print(f"seed failed: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"seed failed: {type(exc).__name__}: {exc}")
        return 1

    print(summary.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
