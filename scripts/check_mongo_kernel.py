"""Reject Linux kernel releases known to prevent the MongoDB 8.0 CI service from starting."""

from __future__ import annotations

import platform
import re
import sys


def is_mongodb_compatible_kernel(release: str) -> bool:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", release)
    if match is None:
        raise ValueError(f"cannot parse Linux kernel version: {release}")
    major, minor, patch = (int(part) for part in match.groups())
    incompatible = (major == 6 and minor >= 19) or (major == 7 and minor == 0 and patch <= 13)
    return not incompatible


def main() -> int:
    if sys.platform != "linux":
        print(f"Skipping Linux kernel guard on {sys.platform}")
        return 0
    release = platform.release()
    print(f"Linux kernel: {release}")
    try:
        compatible = is_mongodb_compatible_kernel(release)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not compatible:
        print(f"MongoDB 8.0 is incompatible with Linux kernel {release}", file=sys.stderr)
        return 1
    print(f"MongoDB-compatible Linux kernel: {release}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
